"""API routes for node discovery and workflow CRUD, import, export, validation, and execution."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from ..core.auth import get_current_user, get_current_user_optional
from ..core.dag import WorkflowValidationError, validate_workflow
from ..core.projects import PROJECT_REPOSITORY
from ..core.registry import REGISTRY
from ..core import runs as run_module
from ..core.workflow_repository import WORKFLOW_REPOSITORY, WorkflowNotFoundError, VersionNotFoundError
from ..models.schemas import (
    NodeSpecOut,
    ValidateOut,
    WorkflowImportIn,
    WorkflowIn,
    WorkflowOut,
    WorkflowSaveIn,
    WorkflowSummaryOut,
    WorkflowVersionCreateIn,
    WorkflowVersionOut,
)
from ..workflows.generate import generate_from_text
from ..core.template_store import TEMPLATE_STORE, TemplateNotFoundError, TemplatePermissionError

router = APIRouter(dependencies=[Depends(get_current_user)])


def _payload(workflow: WorkflowIn) -> dict:
    return workflow.model_dump(mode="json")


def _validate_payload(workflow: WorkflowIn) -> None:
    payload = _payload(workflow)
    try:
        validate_workflow(payload["nodes"], payload["edges"])
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _check_project_membership(project_id: Optional[str], user: Optional[dict]) -> None:
    """认证用户创建/更新工作流时，校验其对目标项目的访问权。"""
    if project_id is None or user is None:
        return
    if user["role"] == "admin":
        return
    if PROJECT_REPOSITORY.member_role(project_id, user["id"]) is None:
        raise HTTPException(status_code=403, detail="无权访问该项目")


def _check_workflow_access(item: dict, user: Optional[dict]) -> None:
    """读取/修改工作流时校验访问权；未认证或遗留公共工作流保持放行。"""
    if user is None:
        return
    if user["role"] == "admin":
        return
    if item.get("owner_id") == user["id"]:
        return
    project_id = item.get("project_id")
    if project_id and PROJECT_REPOSITORY.member_role(project_id, user["id"]):
        return
    raise HTTPException(status_code=403, detail="无权访问该工作流")


@router.get("/nodes", response_model=list[NodeSpecOut], summary="节点库（已注册节点规格）")
def list_nodes() -> list[dict]:
    return REGISTRY.specs()


@router.get("/workflows/templates", summary="内置示例工作流模板库")
def list_workflow_templates() -> list[dict]:
    """返回内置策略模板（nodes + edges），前端可直接加载到画布。无需鉴权。"""
    from ..templates import list_templates

    return list_templates()


class WorkflowTemplateSaveIn(BaseModel):
    name: str = Field(..., description="模板名称", min_length=1)
    description: str = Field("", description="模板说明")
    nodes: list[dict] = Field(default_factory=list, description="节点列表")
    edges: list[dict] = Field(default_factory=list, description="连接列表")
    tags: list[str] = Field(default_factory=list, description="标签")


@router.get("/workflows/templates/mine", summary="我的工作流模板（V3.1 模板市场）")
def my_templates(user: Optional[dict] = Depends(get_current_user)) -> list[dict]:
    """返回当前用户保存的个人模板列表（内置模板另见 /workflows/templates）。"""
    return TEMPLATE_STORE.list_user(user["id"])


@router.post(
    "/workflows/templates",
    status_code=status.HTTP_201_CREATED,
    summary="保存工作流为个人模板",
)
def save_template(
    body: WorkflowTemplateSaveIn,
    user: Optional[dict] = Depends(get_current_user),
) -> dict:
    """把当前画布（或部分工作流）保存为可复用模板，持久化到个人模板库。"""
    try:
        validate_workflow(body.nodes, body.edges)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=f"模板图非法: {exc}") from exc
    return TEMPLATE_STORE.save(
        body.name, body.description, body.nodes, body.edges, body.tags, user["id"]
    )


@router.get("/workflows/templates/{template_id}", summary="获取单个用户模板")
def get_user_template(
    template_id: str,
    user: Optional[dict] = Depends(get_current_user),
) -> dict:
    tpl = TEMPLATE_STORE.get(template_id)
    if tpl is None or tpl["builtin"]:
        raise HTTPException(status_code=404, detail="模板不存在")
    if tpl["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权访问该模板")
    return tpl


@router.delete(
    "/workflows/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除用户模板",
)
def delete_user_template(
    template_id: str,
    user: Optional[dict] = Depends(get_current_user),
) -> Response:
    try:
        TEMPLATE_STORE.delete(template_id, user["id"])
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="模板不存在") from None
    except TemplatePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class WorkflowGenerateRequest(BaseModel):
    prompt: str = Field(..., description="自然语言策略描述", min_length=1)
    use_llm: bool = Field(True, description="是否优先使用已配置的 LLM 生成（失败回退规则模板）")


@router.post("/workflows/generate", summary="自然语言生成工作流（V3.0 AI 策略工作台）")
def generate_workflow(req: WorkflowGenerateRequest) -> dict:
    """把策略描述转换为工作流 JSON（nodes + edges），可直接导入编辑器。

    - 配置了真实 LLM 时优先用模型生成；未配置或生成不合法则回退到规则模板。
    - 返回包含 ``source``（rule/llm）与 ``warnings``，前端据此提示。
    """
    if not req.prompt.strip():
        raise HTTPException(status_code=422, detail="策略描述不能为空")
    result = generate_from_text(req.prompt, use_llm=req.use_llm)
    # 再次兜底校验，确保返回的一定可导入
    try:
        validate_workflow(result["nodes"], result["edges"])
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=500, detail=f"生成结果非法: {exc}") from exc
    return result


@router.get("/workflows", response_model=list[WorkflowSummaryOut], summary="工作流列表")
def list_workflows(
    project_id: Optional[str] = None,
    scope: str = "all",
    user: Optional[dict] = Depends(get_current_user_optional),
) -> list[dict]:
    if user and user["role"] != "admin":
        if scope == "mine":
            return WORKFLOW_REPOSITORY.list(project_id=project_id, owner_id=user["id"])
        # 普通用户只可见自己创建或所在项目下的工作流
        projects = [p["id"] for p in PROJECT_REPOSITORY.list_for_user(user["id"])]
        return [
            wf
            for wf in WORKFLOW_REPOSITORY.list(project_id=project_id)
            if wf.get("owner_id") == user["id"] or wf.get("project_id") in projects
        ]
    return WORKFLOW_REPOSITORY.list(project_id=project_id)


@router.post(
    "/workflows",
    response_model=WorkflowOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建工作流",
)
def create_workflow(
    workflow: WorkflowSaveIn,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    _validate_payload(workflow)
    _check_project_membership(workflow.project_id, user)
    owner_id = user["id"] if user else None
    return WORKFLOW_REPOSITORY.create(_payload(workflow), owner_id=owner_id)


@router.post(
    "/workflows/import",
    response_model=WorkflowOut,
    status_code=status.HTTP_201_CREATED,
    summary="导入工作流 JSON",
)
def import_workflow(
    workflow: WorkflowImportIn,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    _validate_payload(workflow)
    _check_project_membership(workflow.project_id, user)
    owner_id = user["id"] if user else None
    return WORKFLOW_REPOSITORY.create(_payload(workflow), owner_id=owner_id)


@router.get("/workflows/{workflow_id}/export", response_model=WorkflowSaveIn, summary="导出工作流 JSON")
def export_workflow(
    workflow_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    item = get_workflow_inner(workflow_id, user)
    return {key: item[key] for key in ("name", "description", "nodes", "edges")}


def get_workflow_inner(workflow_id: str, user: Optional[dict]) -> dict:
    try:
        item = WORKFLOW_REPOSITORY.get(workflow_id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="工作流不存在") from None
    _check_workflow_access(item, user)
    return item


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut, summary="工作流详情")
def get_workflow(
    workflow_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    return get_workflow_inner(workflow_id, user)


@router.put("/workflows/{workflow_id}", response_model=WorkflowOut, summary="保存工作流")
def update_workflow(
    workflow_id: str,
    workflow: WorkflowSaveIn,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    item = get_workflow_inner(workflow_id, user)
    _validate_payload(workflow)
    _check_project_membership(workflow.project_id or item.get("project_id"), user)
    try:
        return WORKFLOW_REPOSITORY.update(
            workflow_id,
            _payload(workflow),
            owner_id=user["id"] if user else None,
        )
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="工作流不存在") from None


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除工作流")
def delete_workflow(
    workflow_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> Response:
    get_workflow_inner(workflow_id, user)
    try:
        WORKFLOW_REPOSITORY.delete(workflow_id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="工作流不存在") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workflows/{workflow_id}/versions", response_model=list[WorkflowVersionOut], summary="版本历史列表")
def list_workflow_versions(
    workflow_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> list[dict]:
    get_workflow_inner(workflow_id, user)
    return WORKFLOW_REPOSITORY.list_versions(workflow_id)


@router.post(
    "/workflows/{workflow_id}/versions",
    response_model=WorkflowVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建版本快照",
)
def create_workflow_version(
    workflow_id: str,
    body: WorkflowVersionCreateIn,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    get_workflow_inner(workflow_id, user)
    try:
        return WORKFLOW_REPOSITORY.snapshot(workflow_id, label=body.label)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="工作流不存在") from None


@router.post(
    "/workflows/{workflow_id}/versions/{version}/restore",
    response_model=WorkflowOut,
    summary="恢复到指定版本",
)
def restore_workflow_version(
    workflow_id: str,
    version: int,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    get_workflow_inner(workflow_id, user)
    try:
        return WORKFLOW_REPOSITORY.restore(workflow_id, version)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="工作流不存在") from None
    except VersionNotFoundError:
        raise HTTPException(status_code=404, detail="指定版本不存在") from None


@router.post("/workflows/validate", response_model=ValidateOut, summary="校验工作流图")
def validate(workflow: WorkflowIn) -> ValidateOut:
    try:
        graph = validate_workflow(
            [n.model_dump() for n in workflow.nodes],
            [e.model_dump() for e in workflow.edges],
        )
    except WorkflowValidationError as exc:
        return ValidateOut(valid=False, errors=[str(exc)])
    return ValidateOut(valid=True, topo_order=graph.topo_order())


@router.post("/workflows/run", summary="执行工作流（同步返回运行结果）")
def run(workflow: WorkflowIn) -> dict:
    try:
        validate_workflow(
            [n.model_dump() for n in workflow.nodes],
            [e.model_dump() for e in workflow.edges],
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = run_module.RUN_SERVICE.execute_sync(
        [n.model_dump() for n in workflow.nodes],
        [e.model_dump() for e in workflow.edges],
        workflow_name="run",
    )
    return result.to_dict()

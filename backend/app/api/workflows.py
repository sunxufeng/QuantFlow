"""API routes for node discovery and workflow CRUD, import, export, validation, and execution."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..core.auth import get_current_user_optional
from ..core.dag import WorkflowValidationError, validate_workflow
from ..core.projects import PROJECT_REPOSITORY
from ..core.registry import REGISTRY
from ..core import runs as run_module
from ..core.workflow_repository import WORKFLOW_REPOSITORY, WorkflowNotFoundError
from ..models.schemas import (
    NodeSpecOut,
    ValidateOut,
    WorkflowImportIn,
    WorkflowIn,
    WorkflowOut,
    WorkflowSaveIn,
    WorkflowSummaryOut,
)

router = APIRouter()


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

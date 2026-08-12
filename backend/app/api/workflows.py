"""API routes for node discovery and workflow CRUD, import, export, validation, and execution."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from ..core.dag import WorkflowValidationError, validate_workflow
from ..core.executor import WorkflowExecutor
from ..core.registry import REGISTRY
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
executor = WorkflowExecutor(max_workers=4)


def _payload(workflow: WorkflowIn) -> dict:
    return workflow.model_dump(mode="json")


def _validate_payload(workflow: WorkflowIn) -> None:
    payload = _payload(workflow)
    try:
        validate_workflow(payload["nodes"], payload["edges"])
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/nodes", response_model=list[NodeSpecOut], summary="节点库（已注册节点规格）")
def list_nodes() -> list[dict]:
    return REGISTRY.specs()


@router.get("/workflows", response_model=list[WorkflowSummaryOut], summary="工作流列表")
def list_workflows() -> list[dict]:
    return WORKFLOW_REPOSITORY.list()


@router.post(
    "/workflows",
    response_model=WorkflowOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建工作流",
)
def create_workflow(workflow: WorkflowSaveIn) -> dict:
    _validate_payload(workflow)
    return WORKFLOW_REPOSITORY.create(_payload(workflow))


@router.post(
    "/workflows/import",
    response_model=WorkflowOut,
    status_code=status.HTTP_201_CREATED,
    summary="导入工作流 JSON",
)
def import_workflow(workflow: WorkflowImportIn) -> dict:
    _validate_payload(workflow)
    return WORKFLOW_REPOSITORY.create(_payload(workflow))


@router.get("/workflows/{workflow_id}/export", response_model=WorkflowSaveIn, summary="导出工作流 JSON")
def export_workflow(workflow_id: str) -> dict:
    item = get_workflow(workflow_id)
    return {key: item[key] for key in ("name", "description", "nodes", "edges")}


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut, summary="工作流详情")
def get_workflow(workflow_id: str) -> dict:
    try:
        return WORKFLOW_REPOSITORY.get(workflow_id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="工作流不存在") from None


@router.put("/workflows/{workflow_id}", response_model=WorkflowOut, summary="保存工作流")
def update_workflow(workflow_id: str, workflow: WorkflowSaveIn) -> dict:
    _validate_payload(workflow)
    try:
        return WORKFLOW_REPOSITORY.update(workflow_id, _payload(workflow))
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="工作流不存在") from None


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除工作流")
def delete_workflow(workflow_id: str) -> Response:
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
        graph = validate_workflow(
            [n.model_dump() for n in workflow.nodes],
            [e.model_dump() for e in workflow.edges],
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = executor.run(graph)
    return result.to_dict()

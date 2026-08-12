"""Pydantic 请求/响应模型（工作流运行 API 契约）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CanvasPosition(BaseModel):
    x: float
    y: float


class WorkflowNodeIn(BaseModel):
    id: str = Field(..., description="节点唯一 id")
    node_type: str = Field(..., description="节点类型（注册键）")
    params: Dict[str, Any] = Field(default_factory=dict)
    position: Optional[CanvasPosition] = Field(default=None, description="画布坐标")


class WorkflowEdgeIn(BaseModel):
    id: str = Field("", description="边 id（可空）")
    source: str
    source_port: str
    target: str
    target_port: str


class WorkflowIn(BaseModel):
    nodes: List[WorkflowNodeIn] = Field(..., min_length=1, description="节点列表")
    edges: List[WorkflowEdgeIn] = Field(default_factory=list, description="连线列表")


class WorkflowSaveIn(WorkflowIn):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class WorkflowOut(WorkflowSaveIn):
    id: str
    version: int
    created_at: str
    updated_at: str


class WorkflowSummaryOut(BaseModel):
    id: str
    name: str
    description: str
    version: int
    created_at: str
    updated_at: str


class WorkflowImportIn(WorkflowIn):
    name: str = Field(default="Imported workflow", min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class NodeSpecOut(BaseModel):
    node_type: str
    label: str
    category: str
    description: str
    version: str
    inputs: List[Dict[str, Any]]
    outputs: List[Dict[str, Any]]
    params: List[Dict[str, Any]]


class ValidateOut(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    topo_order: List[str] = Field(default_factory=list)

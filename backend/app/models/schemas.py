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
    project_id: Optional[str] = Field(default=None, description="所属项目（M4，可选）")


class WorkflowOut(WorkflowSaveIn):
    id: str
    version: int
    owner_id: Optional[str] = None
    created_at: str
    updated_at: str


class WorkflowSummaryOut(BaseModel):
    id: str
    name: str
    description: str
    version: int
    project_id: Optional[str] = None
    created_at: str
    updated_at: str


class WorkflowImportIn(WorkflowIn):
    name: str = Field(default="Imported workflow", min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    project_id: Optional[str] = Field(default=None, description="所属项目（M4，可选）")


class WorkflowVersionCreateIn(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120, description="版本备注（可选）")


class WorkflowVersionOut(BaseModel):
    id: str
    version: int
    label: Optional[str] = None
    saved_at: str
    workflow_version: int
    name: str
    description: str = ""
    node_count: int = 0
    edge_count: int = 0


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


# ---- M4：用户 / 认证 / 项目 ----

class RegisterIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(..., min_length=6, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    created_at: str


class AuthTokenOut(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ProjectIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)


class ProjectOut(ProjectIn):
    id: str
    owner_id: str
    member_count: int = 0
    created_at: str
    updated_at: str


class ProjectMemberIn(BaseModel):
    username: str = Field(..., description="被添加成员的用户名")
    role: str = Field("member", pattern=r"^(owner|admin|member|viewer)$")


class ProjectMemberOut(BaseModel):
    project_id: str
    user_id: str
    username: str
    role: str
    created_at: str

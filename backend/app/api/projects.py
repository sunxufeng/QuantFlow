"""项目与成员管理 API（M4-2）。

权限模型：
- owner：全部操作（含删除项目）；
- admin：项目信息/成员管理；
- member：查看项目详情与成员；
- viewer：只读（详情/成员列表）；
- 平台级 admin（全局角色）可查看全部项目（list_all 需 admin）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.auth import get_current_user
from ..core.projects import (
    PROJECT_REPOSITORY,
    ProjectMemberNotFoundError,
    ProjectNotFoundError,
    UserAlreadyMemberError,
)
from ..core.users import USER_REPOSITORY
from ..models.schemas import (
    ProjectIn,
    ProjectMemberIn,
    ProjectMemberOut,
    ProjectOut,
)

router = APIRouter(prefix="/projects", tags=["projects"])

_MANAGE_ROLES = ("owner", "admin")


def _require_member(project_id: str, user: dict) -> str:
    """校验用户在项目内，返回其项目角色；否则 403。"""
    role = PROJECT_REPOSITORY.member_role(project_id, user["id"])
    if role is None and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return role or "admin"


def _require_project_role(project_id: str, user: dict, roles) -> None:
    role = _require_member(project_id, user)
    if role not in roles:
        raise HTTPException(status_code=403, detail=f"需要项目角色 {'/'.join(roles)}")


@router.get("", response_model=list[ProjectOut], summary="我的项目列表")
def list_projects(user: dict = Depends(get_current_user)) -> list[dict]:
    if user["role"] == "admin":
        return PROJECT_REPOSITORY.list_all()
    return PROJECT_REPOSITORY.list_for_user(user["id"])


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, summary="创建项目")
def create_project(
    payload: ProjectIn, user: dict = Depends(get_current_user)
) -> dict:
    return PROJECT_REPOSITORY.create(user["id"], payload.name, payload.description)


@router.get("/{project_id}", response_model=ProjectOut, summary="项目详情")
def get_project(project_id: str, user: dict = Depends(get_current_user)) -> dict:
    _require_member(project_id, user)
    try:
        return PROJECT_REPOSITORY.get_or_404(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None


@router.put("/{project_id}", response_model=ProjectOut, summary="更新项目")
def update_project(
    project_id: str, payload: ProjectIn, user: dict = Depends(get_current_user)
) -> dict:
    _require_project_role(project_id, user, _MANAGE_ROLES)
    try:
        return PROJECT_REPOSITORY.update(
            project_id, payload.name, payload.description
        )
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除项目（仅 owner）")
def delete_project(project_id: str, user: dict = Depends(get_current_user)) -> None:
    _require_project_role(project_id, user, ("owner",))
    try:
        PROJECT_REPOSITORY.delete(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None


@router.get("/{project_id}/members", response_model=list[ProjectMemberOut], summary="成员列表")
def list_members(project_id: str, user: dict = Depends(get_current_user)) -> list[dict]:
    _require_member(project_id, user)
    try:
        return PROJECT_REPOSITORY.list_members(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="添加成员（owner/admin）",
)
def add_member(
    project_id: str,
    payload: ProjectMemberIn,
    user: dict = Depends(get_current_user),
) -> dict:
    _require_project_role(project_id, user, _MANAGE_ROLES)
    member = USER_REPOSITORY.get_by_username(payload.username)
    if member is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        added = PROJECT_REPOSITORY.add_member(project_id, member["id"], payload.role)
    except UserAlreadyMemberError:
        raise HTTPException(status_code=409, detail="该用户已在项目中") from None
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    return {
        "project_id": added["project_id"],
        "user_id": added["user_id"],
        "username": member["username"],
        "role": added["role"],
        "created_at": added["created_at"],
    }


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="移除成员（owner/admin，不可移除 owner）",
)
def remove_member(
    project_id: str, user_id: str, user: dict = Depends(get_current_user)
) -> None:
    _require_project_role(project_id, user, _MANAGE_ROLES)
    try:
        PROJECT_REPOSITORY.remove_member(project_id, user_id)
    except ProjectMemberNotFoundError:
        raise HTTPException(status_code=404, detail="成员不存在") from None
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

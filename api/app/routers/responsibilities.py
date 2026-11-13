from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    AuditLog,
    Project,
    Responsibility,
    ResponsibilityStatus,
    User,
    UserRole,
)

router = APIRouter(prefix="/projects/{project_id}/responsibilities", tags=["responsibilities"])


class ResponsibilityActionRequest(BaseModel):
    action: Literal["confirm_owner", "accept", "create"]
    responsibility_id: uuid.UUID | None = None
    confirmed_owner_id: uuid.UUID | None = None
    item: str | None = None
    description: str | None = None


def _serialize_responsibility(r: Responsibility, user_map: dict[uuid.UUID, User]) -> dict:
    def _u(uid: uuid.UUID | None) -> dict | None:
        if not uid or uid not in user_map:
            return None
        u = user_map[uid]
        return {"id": str(u.id), "name": u.name, "role": u.role.value}

    return {
        "id": str(r.id),
        "project_id": str(r.project_id),
        "item": r.item,
        "description": r.description,
        "status": r.status.value,
        "suggested_expert": _u(r.suggested_expert_id),
        "suggested_basis": r.suggested_basis,
        "confirmed_owner": _u(r.confirmed_owner_id),
        "accepted_by": _u(r.accepted_by_id),
    }


@router.get("")
def list_responsibilities(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = db.scalars(
        select(Responsibility)
        .where(Responsibility.project_id == project_id)
        .order_by(Responsibility.created_at.asc())
    ).all()
    users = db.scalars(select(User)).all()
    user_map = {u.id: u for u in users}

    return {
        "project_id": str(project_id),
        "responsibilities": [_serialize_responsibility(r, user_map) for r in items],
    }


@router.post("")
def update_responsibility(
    project_id: uuid.UUID,
    payload: ResponsibilityActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if payload.action == "create":
        if not payload.item or not payload.item.strip():
            raise HTTPException(status_code=422, detail="item is required to create a responsibility.")
        resp = Responsibility(
            project_id=project_id,
            item=payload.item.strip(),
            description=payload.description,
            status=ResponsibilityStatus.unassigned,
        )
        db.add(resp)
        db.flush()
    else:
        if not payload.responsibility_id:
            raise HTTPException(status_code=422, detail="responsibility_id is required.")
        resp = db.get(Responsibility, payload.responsibility_id)
        if not resp or resp.project_id != project_id:
            raise HTTPException(status_code=404, detail="Responsibility not found")

        if payload.action == "confirm_owner":
            if current_user.role != UserRole.reviewer:
                raise HTTPException(status_code=403, detail="Only a reviewer can confirm an owner.")
            if not payload.confirmed_owner_id:
                raise HTTPException(status_code=422, detail="confirmed_owner_id is required.")
            owner = db.get(User, payload.confirmed_owner_id)
            if not owner:
                raise HTTPException(status_code=404, detail="Confirmed owner user not found.")
            # Distinct roles: confirming an owner does NOT auto-accept for the successor
            resp.confirmed_owner_id = owner.id
            resp.accepted_by_id = None
            resp.status = ResponsibilityStatus.confirmed

        elif payload.action == "accept":
            if current_user.role != UserRole.successor:
                raise HTTPException(status_code=403, detail="Only a successor can accept responsibility.")
            if not resp.confirmed_owner_id:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot accept responsibility before a reviewer confirms the owner.",
                )
            if resp.confirmed_owner_id != current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the confirmed owner can accept this responsibility.",
                )
            resp.accepted_by_id = current_user.id
            resp.status = ResponsibilityStatus.accepted

    db.add(
        AuditLog(
            project_id=project_id,
            actor_id=current_user.id,
            action=f"responsibility_{payload.action}",
            entity_type="responsibility",
            entity_id=resp.id,
            details={
                "status": resp.status.value,
                "suggested_expert_id": str(resp.suggested_expert_id) if resp.suggested_expert_id else None,
                "confirmed_owner_id": str(resp.confirmed_owner_id) if resp.confirmed_owner_id else None,
                "accepted_by_id": str(resp.accepted_by_id) if resp.accepted_by_id else None,
            },
        )
    )
    db.commit()

    users = db.scalars(select(User)).all()
    user_map = {u.id: u for u in users}
    return _serialize_responsibility(resp, user_map)

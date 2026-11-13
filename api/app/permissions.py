import uuid

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import AuditLog, Claim, Source, SourceChunk, User


def can_access_record(user: User, allowed_roles: list[str], allowed_user_ids: list) -> bool:
    """
    Central access-check function used by retrieval, generation, citations,
    source previews, search, and export. No bypass paths.
    """
    if user.role.value in (allowed_roles or []):
        return True
    if user.id in (allowed_user_ids or []):
        return True
    return False


def assert_access_or_403(
    db: Session,
    user: User,
    project_id: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID,
    allowed_roles: list[str],
    allowed_user_ids: list,
) -> None:
    """Centralized 403 enforcement + audit logging for direct URL/ID access attempts."""
    if can_access_record(user, allowed_roles, allowed_user_ids):
        return
    db.add(
        AuditLog(
            project_id=project_id,
            actor_id=user.id,
            action="access_denied",
            entity_type=entity_type,
            entity_id=entity_id,
            details={"viewer_role": user.role.value},
        )
    )
    db.commit()
    raise HTTPException(status_code=403, detail="Evidence or source is not available to you.")


def redact_evidence_if_denied(
    user: User,
    src: Source,
    chunk: SourceChunk,
    evidence_payload: dict,
) -> dict:
    """
    If caller lacks permission on either Source or SourceChunk, return a neutral
    placeholder with zero text or metadata leaked.
    """
    src_ok = can_access_record(user, src.allowed_roles, src.allowed_user_ids)
    chunk_ok = can_access_record(user, chunk.allowed_roles, chunk.allowed_user_ids)
    if src_ok and chunk_ok:
        return evidence_payload
    return {
        "restricted": True,
        "message": "Evidence not available to you",
    }


def source_access_filter(user: User) -> ColumnElement[bool]:
    """SQL predicate applied BEFORE retrieval and BEFORE sending anything to the LLM."""
    return or_(
        Source.allowed_roles.contains([user.role.value]),
        Source.allowed_user_ids.contains([user.id]),
    )


def chunk_access_filter(user: User) -> ColumnElement[bool]:
    """SQL predicate applied BEFORE retrieval and BEFORE sending anything to the LLM."""
    return or_(
        SourceChunk.allowed_roles.contains([user.role.value]),
        SourceChunk.allowed_user_ids.contains([user.id]),
    )


def claim_access_filter(user: User) -> ColumnElement[bool]:
    """SQL predicate applied to claims, summaries, citations, and exports."""
    return or_(
        Claim.allowed_roles.contains([user.role.value]),
        Claim.allowed_user_ids.contains([user.id]),
    )

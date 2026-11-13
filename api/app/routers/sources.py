from datetime import datetime, timezone
import difflib
import json
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.ingestion.chunker import chunk_text, save_to_storage
from app.ingestion.github_connector import fetch_github_sources
from app.ingestion.normalizer import normalize_uploaded_content
from app.models import (
    AuditLog,
    Claim,
    ClaimEvidence,
    Project,
    Source,
    SourceChunk,
    SourceType,
    User,
    UserRole,
)
from app.permissions import (
    assert_access_or_403,
    can_access_record,
    chunk_access_filter,
    source_access_filter,
)

router = APIRouter(prefix="/sources", tags=["sources"])

VALID_ROLES = {r.value for r in UserRole}


class GitHubIngestRequest(BaseModel):
    project_id: uuid.UUID
    repo: str = Field(..., description="owner/repo or GitHub URL")
    use_fixture: bool = True
    allowed_roles: list[str] = Field(default_factory=lambda: ["outgoing", "reviewer", "successor"])
    allowed_user_ids: list[uuid.UUID] = Field(default_factory=list)


def _validate_access_policy(allowed_roles: list[str], allowed_user_ids: list[uuid.UUID]) -> tuple[list[str], list[uuid.UUID]]:
    clean_roles = [r.strip() for r in allowed_roles if r.strip()]
    invalid = [r for r in clean_roles if r not in VALID_ROLES]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid roles in access policy: {invalid}")
    if not clean_roles and not allowed_user_ids:
        raise HTTPException(
            status_code=422,
            detail="Explicit access policy required: provide at least one allowed_role or allowed_user_id.",
        )
    return clean_roles, allowed_user_ids


def _persist_source_with_chunks(
    db: Session,
    project_id: uuid.UUID,
    source_type: SourceType,
    title: str,
    uri: str,
    version_sha: str | None,
    source_date: datetime | None,
    content: str,
    filename: str,
    allowed_roles: list[str],
    allowed_user_ids: list[uuid.UUID],
) -> tuple[Source, int]:
    storage_path = save_to_storage(project_id, filename, content)
    policy = {
        "allowed_roles": allowed_roles,
        "allowed_user_ids": [str(uid) for uid in allowed_user_ids],
    }
    source = Source(
        project_id=project_id,
        type=source_type,
        title=title,
        uri=uri,
        version_sha=version_sha,
        storage_path=storage_path,
        source_date=source_date,
        fetched_at=datetime.now(timezone.utc),
        access_policy=policy,
        allowed_roles=allowed_roles,
        allowed_user_ids=allowed_user_ids,
    )
    db.add(source)
    db.flush()

    chunks = chunk_text(content)
    for ch in chunks:
        db.add(
            SourceChunk(
                source_id=source.id,
                project_id=project_id,
                chunk_index=ch.chunk_index,
                text=ch.text,
                start_offset=ch.start_offset,
                end_offset=ch.end_offset,
                line_start=ch.line_start,
                line_end=ch.line_end,
                access_policy=policy,
                allowed_roles=allowed_roles,
                allowed_user_ids=allowed_user_ids,
            )
        )
    return source, len(chunks)


@router.post("/github")
def ingest_github(
    payload: GitHubIngestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    roles, user_ids = _validate_access_policy(payload.allowed_roles, payload.allowed_user_ids)
    docs = fetch_github_sources(payload.repo, use_fixture=payload.use_fixture)

    created_sources = []
    for doc in docs:
        src, chunk_count = _persist_source_with_chunks(
            db=db,
            project_id=project.id,
            source_type=doc.source_type,
            title=doc.title,
            uri=doc.uri,
            version_sha=doc.version_sha,
            source_date=doc.source_date,
            content=doc.content,
            filename=doc.filename,
            allowed_roles=roles,
            allowed_user_ids=user_ids,
        )
        created_sources.append(
            {
                "id": str(src.id),
                "type": src.type.value,
                "title": src.title,
                "uri": src.uri,
                "version_sha": src.version_sha,
                "chunk_count": chunk_count,
            }
        )

    db.add(
        AuditLog(
            project_id=project.id,
            actor_id=current_user.id,
            action="github_ingested",
            entity_type="project",
            entity_id=project.id,
            details={
                "repo": payload.repo,
                "use_fixture": payload.use_fixture,
                "sources_created": len(created_sources),
            },
        )
    )
    db.commit()
    return {"sources_created": len(created_sources), "sources": created_sources}


@router.post("/upload")
async def upload_source(
    project_id: uuid.UUID = Form(...),
    title: str | None = Form(default=None),
    source_date: str | None = Form(default=None),
    allowed_roles: str = Form(default="[]", description="JSON array or comma-separated roles"),
    allowed_user_ids: str = Form(default="[]", description="JSON array or comma-separated UUIDs"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Parse explicit access policy (uploads never inherit original permissions)
    def _parse_list(raw: str) -> list[str]:
        raw = (raw or "").strip()
        if not raw:
            return []
        if raw.startswith("["):
            parsed = json.loads(raw)
            return [str(x).strip() for x in parsed if str(x).strip()]
        return [x.strip() for x in raw.split(",") if x.strip()]

    try:
        parsed_roles = _parse_list(allowed_roles)
        parsed_user_ids = [uuid.UUID(u) for u in _parse_list(allowed_user_ids)]
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid access policy format: {exc}") from exc

    roles, user_ids = _validate_access_policy(parsed_roles, parsed_user_ids)

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    filename = file.filename or "upload.txt"
    try:
        inferred_type, normalized_text = normalize_uploaded_content(filename, raw_bytes)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON task export: {exc}") from exc

    parsed_date: datetime | None = None
    if source_date:
        try:
            parsed_date = datetime.fromisoformat(source_date.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid source_date ISO format: {exc}") from exc

    src, chunk_count = _persist_source_with_chunks(
        db=db,
        project_id=project.id,
        source_type=SourceType(inferred_type),
        title=title or filename,
        uri=f"upload://{filename}",
        version_sha=None,
        source_date=parsed_date,
        content=normalized_text,
        filename=filename,
        allowed_roles=roles,
        allowed_user_ids=user_ids,
    )

    db.add(
        AuditLog(
            project_id=project.id,
            actor_id=current_user.id,
            action="source_uploaded",
            entity_type="source",
            entity_id=src.id,
            details={
                "filename": filename,
                "type": src.type.value,
                "allowed_roles": roles,
                "chunk_count": chunk_count,
            },
        )
    )
    db.commit()

    return {
        "id": str(src.id),
        "type": src.type.value,
        "title": src.title,
        "uri": src.uri,
        "allowed_roles": src.allowed_roles,
        "allowed_user_ids": [str(u) for u in src.allowed_user_ids],
        "chunk_count": chunk_count,
    }


@router.get("")
def list_sources(
    project_id: uuid.UUID | None = Query(default=None),
    include_chunks: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Source).where(source_access_filter(current_user))
    if project_id:
        stmt = stmt.where(Source.project_id == project_id)
    stmt = stmt.order_by(Source.source_date.asc().nulls_last(), Source.fetched_at.asc())

    sources = db.scalars(stmt).all()
    result = []
    for s in sources:
        item = {
            "id": str(s.id),
            "project_id": str(s.project_id),
            "type": s.type.value,
            "title": s.title,
            "uri": s.uri,
            "version_sha": s.version_sha,
            "source_date": s.source_date.isoformat() if s.source_date else None,
            "fetched_at": s.fetched_at.isoformat(),
            "access_policy": s.access_policy,
        }
        if include_chunks:
            chunks = db.scalars(
                select(SourceChunk)
                .where(SourceChunk.source_id == s.id, chunk_access_filter(current_user))
                .order_by(SourceChunk.chunk_index.asc())
            ).all()
            item["chunks"] = [
                {
                    "id": str(c.id),
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    "start_offset": c.start_offset,
                    "end_offset": c.end_offset,
                    "line_start": c.line_start,
                    "line_end": c.line_end,
                }
                for c in chunks
            ]
        result.append(item)
    return {"viewer_role": current_user.role.value, "count": len(result), "sources": result}


@router.get("/search")
def search_sources(
    project_id: uuid.UUID = Query(...),
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permission-scoped text search across permitted sources and chunks."""
    rows = db.execute(
        select(SourceChunk, Source)
        .join(Source, SourceChunk.source_id == Source.id)
        .where(
            SourceChunk.project_id == project_id,
            source_access_filter(current_user),
            chunk_access_filter(current_user),
            SourceChunk.text.ilike(f"%{q}%"),
        )
        .order_by(Source.source_date.asc().nulls_last(), SourceChunk.chunk_index.asc())
    ).all()

    return {
        "viewer_role": current_user.role.value,
        "query": q,
        "count": len(rows),
        "results": [
            {
                "chunk_id": str(chunk.id),
                "source_id": str(src.id),
                "source_title": src.title,
                "source_uri": src.uri,
                "version_sha": src.version_sha,
                "text": chunk.text,
            }
            for chunk, src in rows
        ],
    }


@router.get("/chunks/{chunk_id}")
def get_chunk_preview(
    chunk_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chunk = db.get(SourceChunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    src = db.get(Source, chunk.source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    assert_access_or_403(
        db, current_user, src.project_id, "source", src.id, src.allowed_roles, src.allowed_user_ids
    )
    assert_access_or_403(
        db,
        current_user,
        chunk.project_id,
        "source_chunk",
        chunk.id,
        chunk.allowed_roles,
        chunk.allowed_user_ids,
    )

    return {
        "chunk_id": str(chunk.id),
        "source_id": str(src.id),
        "source_title": src.title,
        "source_uri": src.uri,
        "version_sha": src.version_sha,
        "text": chunk.text,
        "start_offset": chunk.start_offset,
        "end_offset": chunk.end_offset,
    }


class SourceUpdateRequest(BaseModel):
    new_content: str = Field(..., min_length=1)
    new_version_sha: str | None = None


@router.post("/{source_id}/update")
def update_source_and_invalidate(
    source_id: uuid.UUID,
    payload: SourceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    assert_access_or_403(
        db,
        current_user,
        source.project_id,
        "source",
        source.id,
        source.allowed_roles,
        source.allowed_user_ids,
    )

    old_content = ""
    if source.storage_path and Path(source.storage_path).exists():
        old_content = Path(source.storage_path).read_text(encoding="utf-8")
    else:
        old_chunks = db.scalars(
            select(SourceChunk)
            .where(SourceChunk.source_id == source.id)
            .order_by(SourceChunk.chunk_index.asc())
        ).all()
        old_content = "\n\n".join(c.text for c in old_chunks)

    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(),
            payload.new_content.splitlines(),
            fromfile=f"{source.title} (previous)",
            tofile=f"{source.title} (updated)",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff_lines) if diff_lines else "(no textual diff)"

    source.storage_path = save_to_storage(source.project_id, source.title, payload.new_content)
    if payload.new_version_sha:
        source.version_sha = payload.new_version_sha
    source.fetched_at = datetime.now(timezone.utc)

    dependent_claims = db.scalars(
        select(Claim)
        .join(ClaimEvidence, ClaimEvidence.claim_id == Claim.id)
        .join(SourceChunk, ClaimEvidence.chunk_id == SourceChunk.id)
        .where(SourceChunk.source_id == source.id)
        .distinct()
    ).all()

    stale_ids: list[str] = []
    for cl in dependent_claims:
        cl.is_stale = True
        cl.stale_reason = f"Dependent source '{source.title}' was updated; re-review required."
        cl.source_diff = diff_text
        stale_ids.append(str(cl.id))

    db.add(
        AuditLog(
            project_id=source.project_id,
            actor_id=current_user.id,
            action="source_updated_claims_stale",
            entity_type="source",
            entity_id=source.id,
            details={"stale_claim_ids": stale_ids, "new_version_sha": source.version_sha},
        )
    )
    db.commit()

    return {
        "source_id": str(source.id),
        "stale_claims_flagged": len(stale_ids),
        "stale_claim_ids": stale_ids,
        "diff": diff_text,
    }


@router.get("/{source_id}")
def get_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    assert_access_or_403(
        db,
        current_user,
        source.project_id,
        "source",
        source.id,
        source.allowed_roles,
        source.allowed_user_ids,
    )

    chunks = db.scalars(
        select(SourceChunk)
        .where(SourceChunk.source_id == source.id, chunk_access_filter(current_user))
        .order_by(SourceChunk.chunk_index.asc())
    ).all()

    return {
        "id": str(source.id),
        "project_id": str(source.project_id),
        "type": source.type.value,
        "title": source.title,
        "uri": source.uri,
        "version_sha": source.version_sha,
        "source_date": source.source_date.isoformat() if source.source_date else None,
        "fetched_at": source.fetched_at.isoformat(),
        "access_policy": source.access_policy,
        "chunks": [
            {
                "id": str(c.id),
                "chunk_index": c.chunk_index,
                "text": c.text,
                "start_offset": c.start_offset,
                "end_offset": c.end_offset,
                "line_start": c.line_start,
                "line_end": c.line_end,
            }
            for c in chunks
        ],
    }

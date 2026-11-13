from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Claim, Conflict, Project, Responsibility, Source, User
from app.permissions import claim_access_filter, source_access_filter
from app.routers.claims import router as claims_router
from app.routers.clarifications import router as clarifications_router
from app.routers.conflicts import router as conflicts_router
from app.routers.handovers import router as handovers_router
from app.routers.rehearsal import router as rehearsal_router
from app.routers.responsibilities import router as responsibilities_router
from app.routers.sources import router as sources_router

app = FastAPI(title="Relay API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources_router)
app.include_router(handovers_router)
app.include_router(conflicts_router)
app.include_router(claims_router)
app.include_router(clarifications_router)
app.include_router(responsibilities_router)
app.include_router(rehearsal_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/users")
def list_users(db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.role.asc(), User.name.asc())).all()
    return [
        {"id": str(u.id), "name": u.name, "email": u.email, "role": u.role.value}
        for u in users
    ]


@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "repo_url": p.repo_url,
            "departing_user_id": str(p.departing_user_id),
            "successor_user_id": str(p.successor_user_id),
            "reviewer_user_id": str(p.reviewer_user_id) if p.reviewer_user_id else None,
        }
        for p in projects
    ]


@app.get("/api/projects/{project_id}/overview")
def project_overview(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Permission-scoped queries BEFORE retrieval
    sources = db.scalars(
        select(Source)
        .where(Source.project_id == project.id, source_access_filter(current_user))
        .order_by(Source.source_date.asc().nulls_last())
    ).all()

    claims = db.scalars(
        select(Claim)
        .where(Claim.project_id == project.id, claim_access_filter(current_user))
        .order_by(Claim.created_at.asc())
    ).all()

    conflicts = db.scalars(select(Conflict).where(Conflict.project_id == project.id)).all()
    responsibilities = db.scalars(
        select(Responsibility).where(Responsibility.project_id == project.id)
    ).all()

    return {
        "viewer": {
            "id": str(current_user.id),
            "name": current_user.name,
            "role": current_user.role.value,
        },
        "project": {"id": str(project.id), "name": project.name, "description": project.description},
        "counts": {
            "permitted_sources": len(sources),
            "permitted_claims": len(claims),
            "conflicts": len(conflicts),
            "responsibilities": len(responsibilities),
        },
        "sources": [
            {
                "id": str(s.id),
                "type": s.type.value,
                "title": s.title,
                "version_sha": s.version_sha,
                "source_date": s.source_date.isoformat() if s.source_date else None,
                "allowed_roles": s.allowed_roles,
            }
            for s in sources
        ],
        "claims": [
            {
                "id": str(c.id),
                "text": c.text,
                "type": c.type.value,
                "evidence_state": c.evidence_state.value,
                "limitation_note": c.limitation_note,
            }
            for c in claims
        ],
    }

"""Idempotent seed script for the 'Payments Migration' synthetic demo project."""

from datetime import datetime, timezone
from pathlib import Path
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AuditLog,
    Claim,
    ClaimEvidence,
    ClaimType,
    Conflict,
    ConflictStatus,
    EvidenceStance,
    EvidenceState,
    HandoverStatus,
    HandoverVersion,
    Project,
    RehearsalTask,
    Responsibility,
    ResponsibilityStatus,
    Source,
    SourceChunk,
    SourceType,
    User,
    UserRole,
)


def dt(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


def save_object(rel_path: str, content: str) -> str:
    base = Path(settings.object_storage_dir)
    target = base / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return str(target)


def make_chunk(
    source: Source,
    chunk_index: int,
    text: str,
    full_text: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> SourceChunk:
    start = full_text.find(text)
    if start == -1:
        start = 0
    end = start + len(text)
    return SourceChunk(
        source_id=source.id,
        project_id=source.project_id,
        chunk_index=chunk_index,
        text=text,
        start_offset=start,
        end_offset=end,
        line_start=line_start,
        line_end=line_end,
        access_policy=source.access_policy,
        allowed_roles=source.allowed_roles,
        allowed_user_ids=source.allowed_user_ids,
    )


def seed(db: Session) -> dict:
    existing = db.scalar(select(Project).where(Project.name == "Payments Migration"))
    if existing:
        return {"status": "already_seeded", "project_id": str(existing.id)}

    # 1. Demo Users
    maya = User(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name="Maya Lin",
        email="maya.lin@relay.demo",
        role=UserRole.outgoing,
    )
    jordan = User(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        name="Jordan Patel",
        email="jordan.patel@relay.demo",
        role=UserRole.reviewer,
    )
    alex = User(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        name="Alex Rivera",
        email="alex.rivera@relay.demo",
        role=UserRole.successor,
    )
    db.add_all([maya, jordan, alex])
    db.flush()

    # 2. Project
    project = Project(
        id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        name="Payments Migration",
        description=(
            "Migrate checkout & webhook processing from legacy Stripe v1 adapter to Stripe v2 "
            "with idempotent retries and dead-letter queue recovery."
        ),
        repo_url="https://github.com/acme-student-team/payments-service",
        departing_user_id=maya.id,
        successor_user_id=alex.id,
        reviewer_user_id=jordan.id,
    )
    db.add(project)
    db.flush()

    # 3. Handover Version v1 (draft)
    handover_v1 = HandoverVersion(
        project_id=project.id,
        version=1,
        status=HandoverStatus.draft,
        summary_notes="Initial reconstructed handover for Payments Migration.",
    )
    db.add(handover_v1)
    db.flush()

    standard_roles = ["outgoing", "reviewer", "successor"]
    manager_only_roles = ["reviewer"]

    # 4. Sources + Chunks
    # Source A: Outdated README.md
    readme_text = (
        "# Payments Service\n\n"
        "## Payments Migration Status\n"
        "Payments Migration Status: COMPLETE. All checkout traffic is routed through Stripe v2 "
        "and legacy v1 endpoints are decommissioned.\n"
    )
    readme_src = Source(
        project_id=project.id,
        type=SourceType.github_file,
        title="README.md",
        uri="github://acme-student-team/payments-service/README.md",
        version_sha="a1b2c3d4e5f6789012345678901234567890abcd",
        storage_path=save_object("payments-migration/README.md", readme_text),
        source_date=dt(2026, 10, 1),
        access_policy={"allowed_roles": standard_roles, "allowed_user_ids": []},
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    db.add(readme_src)
    db.flush()

    readme_quote = (
        "Payments Migration Status: COMPLETE. All checkout traffic is routed through Stripe v2 "
        "and legacy v1 endpoints are decommissioned."
    )
    readme_chunk = make_chunk(readme_src, 0, readme_quote, readme_text, line_start=4, line_end=5)
    db.add(readme_chunk)

    # Source B: Later Meeting Note (migration paused + rollback procedure)
    note_text = (
        "# Backend Sync — 2026-10-28\n"
        "Attendees: Maya Lin, Jordan Patel\n\n"
        "## Payments Migration\n"
        "Payments migration is PAUSED at 35% traffic due to an idempotency key mismatch on retry.\n"
        "Rollback procedure: set PAYMENTS_V2_ENABLED=false in infra/flags.yaml, redeploy checkout-api, "
        "and drain the retry queue before re-enabling v1.\n"
    )
    note_src = Source(
        project_id=project.id,
        type=SourceType.meeting_note,
        title="notes/2026-10-28-sync.md",
        uri="upload://notes/2026-10-28-sync.md",
        version_sha=None,
        storage_path=save_object("payments-migration/2026-10-28-sync.md", note_text),
        source_date=dt(2026, 10, 28),
        access_policy={"allowed_roles": standard_roles, "allowed_user_ids": []},
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    db.add(note_src)
    db.flush()

    note_quote_paused = "Payments migration is PAUSED at 35% traffic due to an idempotency key mismatch on retry."
    note_quote_rollback = (
        "Rollback procedure: set PAYMENTS_V2_ENABLED=false in infra/flags.yaml, redeploy checkout-api, "
        "and drain the retry queue before re-enabling v1."
    )
    note_chunk_0 = make_chunk(note_src, 0, note_quote_paused, note_text, line_start=5, line_end=5)
    note_chunk_1 = make_chunk(note_src, 1, note_quote_rollback, note_text, line_start=6, line_end=7)
    db.add_all([note_chunk_0, note_chunk_1])

    # Source C: Unfinished PR #142
    pr_text = (
        "PR #142: WIP: Fix Stripe v2 idempotency key formatting\n"
        "Author: Maya Lin\n"
        "Status: OPEN (Draft)\n\n"
        "Normalizes UUIDv4 idempotency keys before retry. Still failing webhook replay integration tests "
        "in tests/test_webhook_replay.py; DO NOT MERGE until DLQ replay is verified.\n"
    )
    pr_src = Source(
        project_id=project.id,
        type=SourceType.github_pr,
        title="PR #142: Fix Stripe v2 idempotency key formatting",
        uri="github://acme-student-team/payments-service/pull/142",
        version_sha="f9e8d7c6b5a4321098765432109876543210fedc",
        storage_path=save_object("payments-migration/pr-142.txt", pr_text),
        source_date=dt(2026, 11, 2),
        access_policy={"allowed_roles": standard_roles, "allowed_user_ids": []},
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    db.add(pr_src)
    db.flush()

    pr_quote = (
        "Still failing webhook replay integration tests in tests/test_webhook_replay.py; "
        "DO NOT MERGE until DLQ replay is verified."
    )
    pr_chunk = make_chunk(pr_src, 0, pr_quote, pr_text, line_start=5, line_end=6)
    db.add(pr_chunk)

    # Source D: Task CSV Export (includes task with no clear owner)
    csv_text = (
        "task_id,title,status,owner,notes\n"
        "TASK-88,Verify webhook dead-letter queue replay after idempotency fix,blocked,,No assignee set yet\n"
        "TASK-89,Rotate Stripe v2 webhook signing secret before 100% rollout,todo,Maya Lin,Needs handoff\n"
    )
    csv_src = Source(
        project_id=project.id,
        type=SourceType.task_export,
        title="tasks/migration-tasks.csv",
        uri="upload://tasks/migration-tasks.csv",
        version_sha=None,
        storage_path=save_object("payments-migration/migration-tasks.csv", csv_text),
        source_date=dt(2026, 11, 3),
        access_policy={"allowed_roles": standard_roles, "allowed_user_ids": []},
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    db.add(csv_src)
    db.flush()

    csv_quote_88 = "TASK-88,Verify webhook dead-letter queue replay after idempotency fix,blocked,,No assignee set yet"
    csv_quote_89 = "TASK-89,Rotate Stripe v2 webhook signing secret before 100% rollout,todo,Maya Lin,Needs handoff"
    csv_chunk_0 = make_chunk(csv_src, 0, csv_quote_88, csv_text, line_start=2, line_end=2)
    csv_chunk_1 = make_chunk(csv_src, 1, csv_quote_89, csv_text, line_start=3, line_end=3)
    db.add_all([csv_chunk_0, csv_chunk_1])

    # Source E: Manager-only Restricted Note (Successor Alex MUST NOT see this)
    mgr_text = (
        "# Manager 1:1 Note — 2026-11-05 (RESTRICTED)\n"
        "CONFIDENTIAL (Manager Only): Stripe enterprise rate-card renegotiation is pending legal sign-off. "
        "Maya's departure accelerates the need to freeze new payment features until Q1.\n"
    )
    mgr_src = Source(
        project_id=project.id,
        type=SourceType.meeting_note,
        title="notes/2026-11-05-manager-1on1.md",
        uri="upload://notes/2026-11-05-manager-1on1.md",
        version_sha=None,
        storage_path=save_object("payments-migration/2026-11-05-manager-1on1.md", mgr_text),
        source_date=dt(2026, 11, 5),
        access_policy={"allowed_roles": manager_only_roles, "allowed_user_ids": [str(jordan.id)]},
        allowed_roles=manager_only_roles,
        allowed_user_ids=[jordan.id],
    )
    db.add(mgr_src)
    db.flush()

    mgr_quote = (
        "CONFIDENTIAL (Manager Only): Stripe enterprise rate-card renegotiation is pending legal sign-off. "
        "Maya's departure accelerates the need to freeze new payment features until Q1."
    )
    mgr_chunk = make_chunk(mgr_src, 0, mgr_quote, mgr_text, line_start=2, line_end=3)
    db.add(mgr_chunk)
    db.flush()

    # 5. Claims + Evidence
    claim_readme = Claim(
        project_id=project.id,
        handover_version_id=handover_v1.id,
        text="README states the Payments Migration to Stripe v2 is complete and legacy v1 endpoints are decommissioned.",
        type=ClaimType.state,
        evidence_state=EvidenceState.conflicting,
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    claim_paused = Claim(
        project_id=project.id,
        handover_version_id=handover_v1.id,
        text="Payments migration is actually paused at 35% traffic due to an idempotency key mismatch on retry.",
        type=ClaimType.state,
        evidence_state=EvidenceState.conflicting,
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    claim_rollback = Claim(
        project_id=project.id,
        handover_version_id=handover_v1.id,
        text="To roll back Stripe v2, set PAYMENTS_V2_ENABLED=false in infra/flags.yaml, redeploy checkout-api, and drain the retry queue.",
        type=ClaimType.decision,
        evidence_state=EvidenceState.supported,
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    claim_pr = Claim(
        project_id=project.id,
        handover_version_id=handover_v1.id,
        text="PR #142 (idempotency key formatting fix) is unfinished and failing webhook replay integration tests; do not merge.",
        type=ClaimType.unfinished,
        evidence_state=EvidenceState.supported,
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    claim_unowned_task = Claim(
        project_id=project.id,
        handover_version_id=handover_v1.id,
        text="TASK-88 (Verify webhook dead-letter queue replay after idempotency fix) is blocked and has no assigned owner.",
        type=ClaimType.ownership,
        evidence_state=EvidenceState.supported,
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    claim_delay_unknown = Claim(
        project_id=project.id,
        handover_version_id=handover_v1.id,
        text="Reason for the production deployment delay from Oct 15 to Nov 10 is unknown.",
        type=ClaimType.risk,
        evidence_state=EvidenceState.missing,
        limitation_note=(
            "No source in the repository, meeting notes, or task export explains why the Oct 15 deployment "
            "window was delayed. Intent/rationale is not inferred from code alone."
        ),
        allowed_roles=standard_roles,
        allowed_user_ids=[],
    )
    claim_mgr_only = Claim(
        project_id=project.id,
        handover_version_id=handover_v1.id,
        text="Stripe enterprise rate-card renegotiation is pending legal sign-off; feature freeze planned until Q1.",
        type=ClaimType.risk,
        evidence_state=EvidenceState.supported,
        allowed_roles=manager_only_roles,
        allowed_user_ids=[jordan.id],
    )
    db.add_all([
        claim_readme,
        claim_paused,
        claim_rollback,
        claim_pr,
        claim_unowned_task,
        claim_delay_unknown,
        claim_mgr_only,
    ])
    db.flush()

    db.add_all([
        ClaimEvidence(
            claim_id=claim_readme.id,
            chunk_id=readme_chunk.id,
            quote_span=readme_quote,
            quote_start_offset=readme_chunk.start_offset,
            quote_end_offset=readme_chunk.end_offset,
            stance=EvidenceStance.supports,
        ),
        ClaimEvidence(
            claim_id=claim_paused.id,
            chunk_id=note_chunk_0.id,
            quote_span=note_quote_paused,
            quote_start_offset=note_chunk_0.start_offset,
            quote_end_offset=note_chunk_0.end_offset,
            stance=EvidenceStance.supports,
        ),
        ClaimEvidence(
            claim_id=claim_paused.id,
            chunk_id=pr_chunk.id,
            quote_span=pr_quote,
            quote_start_offset=pr_chunk.start_offset,
            quote_end_offset=pr_chunk.end_offset,
            stance=EvidenceStance.context,
        ),
        ClaimEvidence(
            claim_id=claim_rollback.id,
            chunk_id=note_chunk_1.id,
            quote_span=note_quote_rollback,
            quote_start_offset=note_chunk_1.start_offset,
            quote_end_offset=note_chunk_1.end_offset,
            stance=EvidenceStance.supports,
        ),
        ClaimEvidence(
            claim_id=claim_pr.id,
            chunk_id=pr_chunk.id,
            quote_span=pr_quote,
            quote_start_offset=pr_chunk.start_offset,
            quote_end_offset=pr_chunk.end_offset,
            stance=EvidenceStance.supports,
        ),
        ClaimEvidence(
            claim_id=claim_unowned_task.id,
            chunk_id=csv_chunk_0.id,
            quote_span=csv_quote_88,
            quote_start_offset=csv_chunk_0.start_offset,
            quote_end_offset=csv_chunk_0.end_offset,
            stance=EvidenceStance.supports,
        ),
        ClaimEvidence(
            claim_id=claim_mgr_only.id,
            chunk_id=mgr_chunk.id,
            quote_span=mgr_quote,
            quote_start_offset=mgr_chunk.start_offset,
            quote_end_offset=mgr_chunk.end_offset,
            stance=EvidenceStance.supports,
        ),
    ])

    # 6. Conflict Ledger entry
    conflict = Conflict(
        project_id=project.id,
        title="Migration status conflict: README says COMPLETE vs. Oct 28 note & PR #142 say PAUSED/WIP",
        claim_ids=[claim_readme.id, claim_paused.id],
        status=ConflictStatus.open,
    )
    db.add(conflict)

    # 7. Responsibilities (suggested expert != confirmed owner != accepted successor)
    resp_adapter = Responsibility(
        project_id=project.id,
        item="Stripe v2 idempotency & webhook adapter (PR #142)",
        description="Finish idempotency key normalization and fix webhook replay integration tests.",
        suggested_expert_id=maya.id,
        suggested_basis="Commit history in payments-service (suggests expertise, not accountability).",
        status=ResponsibilityStatus.suggested,
    )
    resp_dlq = Responsibility(
        project_id=project.id,
        item="TASK-88: Webhook dead-letter queue replay verification",
        description="Unassigned task blocking PR #142 merge.",
        suggested_expert_id=None,
        suggested_basis="No owner listed in tasks/migration-tasks.csv.",
        status=ResponsibilityStatus.unassigned,
    )
    db.add_all([resp_adapter, resp_dlq])

    # 8. Rehearsal Tasks (3 verification tasks for the successor)
    db.add_all([
        RehearsalTask(
            project_id=project.id,
            task_order=1,
            title="Find the current rollback procedure",
            prompt="How do you roll back Stripe v2 traffic if checkout errors spike?",
            expected_topic="rollback_procedure",
        ),
        RehearsalTask(
            project_id=project.id,
            task_order=2,
            title="Identify the next blocker and owner",
            prompt="What is currently blocking PR #142 from merging, and who owns the blocking task?",
            expected_topic="next_blocker_owner",
        ),
        RehearsalTask(
            project_id=project.id,
            task_order=3,
            title="Explain a superseded decision",
            prompt="Why is the README claim that the migration is COMPLETE inaccurate, and what is the actual state?",
            expected_topic="superseded_decision",
        ),
    ])

    # 9. Audit Log
    db.add(
        AuditLog(
            project_id=project.id,
            actor_id=maya.id,
            action="seed_initialized",
            entity_type="project",
            entity_id=project.id,
            details={"sources_seeded": 5, "claims_seeded": 7, "conflicts_seeded": 1},
        )
    )

    db.commit()
    return {"status": "seeded", "project_id": str(project.id)}


if __name__ == "__main__":
    with SessionLocal() as session:
        result = seed(session)
        print(result)

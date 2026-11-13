# Relay — Source-Backed Project Handover

Relay prevents critical engineering knowledge from leaving with departing maintainers. It reconstructs a source-backed handover, exposes conflicting and missing evidence, enforces reviewer sign-off, delivers only permission-scoped claims and citations to the successor, and verifies readiness through a 3-task continuation rehearsal.

---

## Architecture

```
  [GitHub Repo / Offline Fixture]   [Uploaded MD/TXT/CSV/JSON + Explicit Policy]
                 \                                 /
                  v                               v
           +---------------------------------------------+
           |  Ingestion & Deterministic Chunker          |
           |  (SHA-pinned URIs, span offsets, ./storage) |
           +---------------------------------------------+
                                  |
                                  v
           +---------------------------------------------+
           |  Central Permission Gate (app/permissions)  |
           |  Enforced BEFORE retrieval, LLM, search,    |
           |  citations, previews, and exports           |
           +---------------------------------------------+
                                  |
                                  v
           +---------------------------------------------+
           |  Structured JSON Extraction + Verbatim      |
           |  Quote Validator + Conflict/Gap Detector    |
           +---------------------------------------------+
                                  |
                 +----------------+----------------+
                 v                                 v
      [Reviewer Console (/reviewer)]    [Successor Delivery (/successor)]
      - Inspect SHA-pinned evidence     - Approved handover only
      - Resolve conflicts w/ notes      - Neutral "evidence not available"
      - Adaptive clarifications         - 3-task continuation rehearsal
      - Stale-claim diff & re-review    - Objective readiness summary
      - Approve handover version        - Acknowledge receipt
```

---

## Setup & Running Locally

### 1. Start PostgreSQL
```bash
cp .env.example .env
docker compose up -d postgres
```

### 2. Backend (`/api`): Install, Migrate, Seed, Run
```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend (`/web`): Install & Run
```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000` (Reviewer Console at `/reviewer`, Successor Delivery & Rehearsal at `/successor`).

---

## Evaluation Harness & Automated Tests

- **Labelled Evaluation Set**: `api/fixtures/eval_dataset.json` (20 factual claims, 5 conflicts, 5 missing-information cases, 10 access-control cases).
- **Run Evaluation Report** (prints real observed counts):
  ```bash
  cd api && python -m scripts.run_eval
  ```
- **Run Pytest Suite** (unit + integration):
  ```bash
  cd api && pytest -v
  ```

---

## Demo Walkthrough ("Payments Migration")

You can run the automated API walkthrough (`cd api && python -m scripts.run_demo`) or step through it in the UI:

1. **Reviewer (`Jordan Patel`) on `/reviewer`**:
   - Inspects the **Conflicts Ledger**: outdated `README.md` (Oct 1, `COMPLETE`) vs. `notes/2026-10-28-sync.md` (`PAUSED at 35%`) and `PR #142` (`WIP / DO NOT MERGE`).
   - Checks the **Missing Evidence** gap: deployment delay rationale from Oct 15 to Nov 10 is marked `missing` (`unknown` — never invented from code).
   - Resolves the conflict with a required explanation note, confirms critical claims, confirms ownership in the **Responsibility Table**, and clicks **Approve v1**.
2. **Successor (`Alex Rivera`) on `/successor`**:
   - Sees only the approved handover; the manager-only restricted note (`notes/2026-11-05-manager-1on1.md`) is absent from claims, search, previews, and Markdown exports (any restricted citation renders as `"Evidence not available to you"`).
   - Completes the **3 Continuation Rehearsal Tasks** (rollback procedure, next blocker & owner, superseded decision explained), records gaps/time, accepts or blocks responsibilities, views the **Readiness Summary**, and clicks **Acknowledge Receipt**.

---

## Known Limitations
- **Filtered text retrieval**: Uses SQL/keyword filtering rather than vector embeddings; large repositories require scoping to relevant docs/issues/PRs.
- **Offline mock vs. live LLM**: When `OPENAI_API_KEY` is unset, extraction uses the deterministic offline mock engine; set `OPENAI_API_KEY` in `.env` to use live structured-JSON extraction.
- **Single-repo GitHub scope**: `POST /sources/github` targets one repository at a time (live via `GITHUB_TOKEN` or offline via `api/fixtures/github_payments_service.json`).
- **Local object storage**: Raw source snapshots are written to `./storage` on local disk rather than S3.

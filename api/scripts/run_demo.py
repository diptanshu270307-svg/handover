"""End-to-end demo script: Reviewer -> Conflict Resolution & Approval -> Successor Delivery & Rehearsal."""

import json
import os
import httpx

API_URL = os.environ.get("RELAY_API_URL", "http://localhost:8000")
PROJECT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REVIEWER_ID = "22222222-2222-2222-2222-222222222222"
SUCCESSOR_ID = "33333333-3333-3333-3333-333333333333"


def main() -> None:
    with httpx.Client(base_url=API_URL, timeout=15.0) as client:
        print("=== 1. REVIEWER (Jordan Patel) ===")
        hv = client.get(
            f"/handovers/latest?project_id={PROJECT_ID}",
            headers={"X-User-Id": REVIEWER_ID},
        ).json()
        print(f"Loaded Handover v{hv['version']} ({hv['status']}), {len(hv['claims'])} claims")

        conflicts = client.get(
            f"/conflicts?project_id={PROJECT_ID}",
            headers={"X-User-Id": REVIEWER_ID},
        ).json()["conflicts"]
        print(f"Conflicts visible: {len(conflicts)}")
        for cf in conflicts:
            print(f"  - [{cf['status'].upper()}] {cf['title']}")
            if cf["status"] == "open":
                paused = next(s for s in cf["sides"] if "paused" in s["text"].lower())
                client.post(
                    f"/conflicts/{cf['id']}/resolve",
                    headers={"X-User-Id": REVIEWER_ID},
                    json={
                        "winning_claim_id": paused["claim_id"],
                        "resolution_note": "Oct 28 note & PR #142 reflect live 35% traffic; README is outdated.",
                    },
                ).raise_for_status()
                print("    -> Resolved conflict in favor of PAUSED state.")

        gaps = client.get(
            f"/conflicts/gaps?project_id={PROJECT_ID}",
            headers={"X-User-Id": REVIEWER_ID},
        ).json()
        print("Missing-information gaps:")
        for g in gaps["missing_claims"]:
            print(f"  - {g['text']} ({g['limitation_note']})")

        # Confirm remaining critical claims so approval succeeds
        hv = client.get(
            f"/handovers/latest?project_id={PROJECT_ID}",
            headers={"X-User-Id": REVIEWER_ID},
        ).json()
        for cl in hv["claims"]:
            if cl["evidence_state"] in ("supported", "conflicting"):
                client.post(
                    f"/claims/{cl['id']}/review",
                    headers={"X-User-Id": REVIEWER_ID},
                    json={"action": "confirm"},
                ).raise_for_status()

        app_resp = client.post(
            f"/handovers/{hv['id']}/approve",
            headers={"X-User-Id": REVIEWER_ID},
            json={},
        )
        app_resp.raise_for_status()
        print(f"Approved Handover v{hv['version']}: {app_resp.json()['status']}")

        print("\n=== 2. SUCCESSOR (Alex Rivera) ===")
        succ_hv = client.get(
            f"/handovers/approved?project_id={PROJECT_ID}",
            headers={"X-User-Id": SUCCESSOR_ID},
        ).json()
        leaked = any("rate-card" in json.dumps(c).lower() for c in succ_hv["claims"])
        print(f"Approved handover loaded for successor. Restricted note leaked? {leaked}")

        search_res = client.get(
            f"/sources/search?project_id={PROJECT_ID}&q=renegotiation",
            headers={"X-User-Id": SUCCESSOR_ID},
        ).json()
        print(f"Search for restricted keyword 'renegotiation' as successor: {search_res['count']} hits")

        reh = client.get(
            f"/projects/{PROJECT_ID}/rehearsal",
            headers={"X-User-Id": SUCCESSOR_ID},
        ).json()
        for task in reh["tasks"]:
            client.post(
                f"/projects/{PROJECT_ID}/rehearsal/submit",
                headers={"X-User-Id": SUCCESSOR_ID},
                json={
                    "rehearsal_task_id": task["id"],
                    "answer_text": f"Completed '{task['title']}' using handover citations.",
                    "evidence_claim_ids": [succ_hv["claims"][0]["id"]],
                    "gaps_hit": [],
                    "duration_seconds": 25,
                },
            ).raise_for_status()

        readiness = client.get(
            f"/projects/{PROJECT_ID}/rehearsal/readiness",
            headers={"X-User-Id": SUCCESSOR_ID},
        ).json()
        print(f"Rehearsal Readiness Summary: {json.dumps(readiness)}")

        ack = client.post(
            f"/handovers/{succ_hv['id']}/acknowledge",
            headers={"X-User-Id": SUCCESSOR_ID},
            json={"notes": "Reviewed approved handover and completed 3 rehearsal tasks."},
        ).json()
        print(f"Receipt Acknowledged at {ack['acknowledged_at']}")


if __name__ == "__main__":
    main()

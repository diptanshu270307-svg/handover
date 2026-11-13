export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type UserRole = "outgoing" | "reviewer" | "successor";

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  repo_url: string | null;
  departing_user_id: string;
  successor_user_id: string;
  reviewer_user_id: string | null;
}

export interface EvidencePassage {
  restricted?: boolean;
  message?: string;
  id?: string;
  chunk_id?: string;
  source_id?: string;
  source_title?: string;
  source_type?: string;
  source_uri?: string;
  version_sha?: string | null;
  source_date?: string | null;
  quote_span?: string;
  quote_start_offset?: number;
  quote_end_offset?: number;
  stance?: string;
}

export interface ClaimReviewItem {
  id: string;
  action: string;
  old_text: string | null;
  new_text: string | null;
  note: string | null;
  created_at: string;
}

export interface ClaimItem {
  id: string;
  type: "state" | "decision" | "unfinished" | "dependency" | "ownership" | "risk" | "next_action";
  text: string;
  evidence_state: "supported" | "conflicting" | "missing" | "superseded" | "human_confirmed";
  limitation_note: string | null;
  is_stale?: boolean;
  stale_reason?: string | null;
  source_diff?: string | null;
  evidence: EvidencePassage[];
  reviews: ClaimReviewItem[];
}

export interface ClarificationItem {
  id: string;
  project_id: string;
  target_type: "gap" | "conflict";
  claim_id: string | null;
  conflict_id: string | null;
  question: string;
  asked_to: { id: string; name: string; role: string } | null;
  answer_text: string | null;
  answered_by: { id: string; name: string; role: string } | null;
  answered_at: string | null;
  status: "open" | "answered";
}

export interface ReadinessSummary {
  project_id: string;
  readiness_status: "not_started" | "needs_followup" | "ready";
  tasks_total: number;
  tasks_completed: number;
  tasks_passed: number;
  total_duration_seconds: number;
  gaps_encountered: string[];
  responsibilities_total: number;
  responsibilities_accepted: number;
  responsibilities_blocked: number;
}

export interface HandoverData {
  id: string;
  project_id: string;
  version: number;
  status: "draft" | "in_review" | "approved" | "superseded";
  approved_by: string | null;
  approved_at: string | null;
  summary_notes: string | null;
  viewer_role: UserRole;
  claims: ClaimItem[];
  receipts: {
    id: string;
    successor_id: string;
    acknowledged_at: string;
    notes: string | null;
  }[];
}

export interface ConflictSide {
  claim_id: string;
  text: string;
  type: string;
  evidence_state: string;
  passages: EvidencePassage[];
}

export interface ConflictItem {
  id: string;
  project_id: string;
  title: string;
  status: "open" | "resolved";
  winning_claim_id: string | null;
  resolution_note: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  sides: ConflictSide[];
}

export interface ResponsibilityItem {
  id: string;
  project_id: string;
  item: string;
  description: string | null;
  status: "unassigned" | "suggested" | "confirmed" | "accepted";
  suggested_expert: { id: string; name: string; role: string } | null;
  suggested_basis: string | null;
  confirmed_owner: { id: string; name: string; role: string } | null;
  accepted_by: { id: string; name: string; role: string } | null;
}

export interface RehearsalTask {
  id: string;
  task_order: number;
  title: string;
  prompt: string;
  expected_topic: string;
}

export interface RehearsalResult {
  id: string;
  rehearsal_task_id: string;
  successor_id: string;
  answer_text: string;
  evidence_chunk_ids: string[];
  evidence_claim_ids: string[];
  gaps_hit: string[];
  passed: boolean | null;
  completed_at: string;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  userId?: string
): Promise<T> {
  const headers = new Headers(options.headers);
  if (userId) headers.set("X-User-Id", userId);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers, cache: "no-store" });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      detail = err.detail || detail;
    } catch {
      // ignore non-json
    }
    throw new Error(detail);
  }
  return res.json();
}

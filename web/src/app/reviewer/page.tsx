"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ConflictsPanel } from "@/components/ConflictsPanel";
import { EvidenceBadge } from "@/components/EvidenceBadge";
import { EvidenceDrawer } from "@/components/EvidenceDrawer";
import { ResponsibilityTable } from "@/components/ResponsibilityTable";
import {
  apiFetch,
  type ClaimItem,
  type ClarificationItem,
  type ConflictItem,
  type HandoverData,
  type Project,
  type ResponsibilityItem,
  type User,
} from "@/lib/api";

const CLAIM_GROUPS: { key: ClaimItem["type"]; label: string }[] = [
  { key: "state", label: "Current State" },
  { key: "decision", label: "Decisions" },
  { key: "unfinished", label: "Unfinished Work" },
  { key: "dependency", label: "Dependencies" },
  { key: "ownership", label: "Ownership Gaps" },
  { key: "risk", label: "Risks" },
  { key: "next_action", label: "3 Next Actions" },
];

const CRITICAL_TYPES = new Set(["state", "decision", "risk", "ownership"]);

export default function ReviewerPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeUserId, setActiveUserId] = useState<string>("");
  const [activeProjectId, setActiveProjectId] = useState<string>("");

  const [handover, setHandover] = useState<HandoverData | null>(null);
  const [conflicts, setConflicts] = useState<ConflictItem[]>([]);
  const [responsibilities, setResponsibilities] = useState<ResponsibilityItem[]>([]);
  const [clarifications, setClarifications] = useState<ClarificationItem[]>([]);
  const [clarificationDrafts, setClarificationDrafts] = useState<Record<string, string>>({});

  const [tab, setTab] = useState<"claims" | "conflicts" | "responsibilities" | "clarifications">("claims");
  const [drawerClaim, setDrawerClaim] = useState<ClaimItem | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<string>("");
  const [limitationId, setLimitationId] = useState<string | null>(null);
  const [limitationDraft, setLimitationDraft] = useState<string>("");

  const [busy, setBusy] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [banner, setBanner] = useState<{ kind: "error" | "ok"; text: string } | null>(null);

  const activeUser = useMemo(
    () => users.find((u) => u.id === activeUserId) || null,
    [users, activeUserId]
  );

  const loadBootstrap = useCallback(async () => {
    const [uList, pList] = await Promise.all([
      apiFetch<User[]>("/api/users"),
      apiFetch<Project[]>("/api/projects"),
    ]);
    setUsers(uList);
    setProjects(pList);
    const defaultReviewer = uList.find((u) => u.role === "reviewer") || uList[0];
    if (defaultReviewer) setActiveUserId(defaultReviewer.id);
    if (pList[0]) setActiveProjectId(pList[0].id);
  }, []);

  const loadWorkspace = useCallback(async (projectId: string, userId: string) => {
    if (!projectId || !userId) return;
    setLoading(true);
    try {
      const [hv, cf, resp, clar] = await Promise.all([
        apiFetch<HandoverData>(`/handovers/latest?project_id=${projectId}`, {}, userId),
        apiFetch<{ conflicts: ConflictItem[] }>(`/conflicts?project_id=${projectId}`, {}, userId),
        apiFetch<{ responsibilities: ResponsibilityItem[] }>(
          `/projects/${projectId}/responsibilities`,
          {},
          userId
        ),
        apiFetch<{ clarifications: ClarificationItem[] }>(
          `/clarifications?project_id=${projectId}`,
          {},
          userId
        ),
      ]);
      setHandover(hv);
      setConflicts(cf.conflicts);
      setResponsibilities(resp.responsibilities);
      setClarifications(clar.clarifications);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBootstrap().catch((e) => setBanner({ kind: "error", text: e.message }));
  }, [loadBootstrap]);

  useEffect(() => {
    if (activeProjectId && activeUserId) {
      loadWorkspace(activeProjectId, activeUserId).catch((e) =>
        setBanner({ kind: "error", text: e.message })
      );
    }
  }, [activeProjectId, activeUserId, loadWorkspace]);

  const openConflictCount = conflicts.filter((c) => c.status === "open").length;
  const staleCount = (handover?.claims || []).filter((c) => c.is_stale).length;
  const unreviewedCriticalCount = (handover?.claims || []).filter(
    (c) =>
      CRITICAL_TYPES.has(c.type) &&
      (c.evidence_state === "supported" || c.evidence_state === "conflicting")
  ).length;

  const canApprove =
    activeUser?.role === "reviewer" &&
    handover?.status !== "approved" &&
    openConflictCount === 0 &&
    staleCount === 0 &&
    unreviewedCriticalCount === 0;

  const handleClaimAction = async (
    claimId: string,
    action: "confirm" | "edit" | "reject" | "add_limitation",
    extra?: { new_text?: string; limitation_note?: string }
  ) => {
    setBanner(null);
    await apiFetch(
      `/claims/${claimId}/review`,
      {
        method: "POST",
        body: JSON.stringify({ action, ...extra }),
      },
      activeUserId
    );
    setEditingId(null);
    setLimitationId(null);
    await loadWorkspace(activeProjectId, activeUserId);
  };

  const handleResolveConflict = async (conflictId: string, winningClaimId: string, note: string) => {
    setBanner(null);
    await apiFetch(
      `/conflicts/${conflictId}/resolve`,
      {
        method: "POST",
        body: JSON.stringify({ winning_claim_id: winningClaimId, resolution_note: note }),
      },
      activeUserId
    );
    setBanner({ kind: "ok", text: "Conflict resolved and superseded claim updated." });
    await loadWorkspace(activeProjectId, activeUserId);
  };

  const handleGenerate = async () => {
    setBusy(true);
    setBanner(null);
    try {
      await apiFetch(
        "/handovers/generate",
        {
          method: "POST",
          body: JSON.stringify({ project_id: activeProjectId, use_mock: true }),
        },
        activeUserId
      );
      setBanner({ kind: "ok", text: "Generated new permission-scoped handover draft." });
      await loadWorkspace(activeProjectId, activeUserId);
    } catch (e) {
      setBanner({ kind: "error", text: e instanceof Error ? e.message : "Generation failed" });
    } finally {
      setBusy(false);
    }
  };

  const handleApprove = async () => {
    if (!handover) return;
    setBusy(true);
    setBanner(null);
    try {
      await apiFetch(`/handovers/${handover.id}/approve`, { method: "POST", body: "{}" }, activeUserId);
      setBanner({ kind: "ok", text: `Handover v${handover.version} approved.` });
      await loadWorkspace(activeProjectId, activeUserId);
    } catch (e) {
      setBanner({ kind: "error", text: e instanceof Error ? e.message : "Approval blocked" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-800 bg-[#0f2942] text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-center gap-4">
            <Link href="/" className="text-lg font-bold tracking-tight text-white">
              Relay
            </Link>
            <span className="rounded bg-teal-500/20 px-2 py-0.5 text-xs font-medium text-teal-200">
              Reviewer Console
            </span>
            {handover && (
              <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-xs font-medium text-slate-200">
                v{handover.version} · {handover.status}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <select
              value={activeUserId}
              onChange={(e) => setActiveUserId(e.target.value)}
              className="rounded-lg border border-slate-600 bg-[#163a5c] px-3 py-1.5 text-xs text-white"
            >
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({u.role})
                </option>
              ))}
            </select>

            <button
              onClick={handleGenerate}
              disabled={busy}
              className="rounded-lg border border-teal-400/40 bg-teal-600/20 px-3 py-1.5 text-xs font-semibold text-teal-200 hover:bg-teal-600/30 disabled:opacity-50"
            >
              Regenerate Draft
            </button>

            <button
              onClick={handleApprove}
              disabled={busy || !canApprove}
              title={
                !canApprove
                  ? "Resolve all open conflicts and review critical claims before approving."
                  : "Approve handover version"
              }
              className="rounded-lg bg-teal-500 px-4 py-1.5 text-xs font-semibold text-slate-950 hover:bg-teal-400 disabled:cursor-not-allowed disabled:bg-slate-600 disabled:text-slate-300"
            >
              {handover?.status === "approved" ? "Approved" : `Approve v${handover?.version ?? 1}`}
            </button>

            <Link
              href="/successor"
              className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-white/10"
            >
              Successor View →
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-6 py-6">
        {banner && (
          <div
            className={`rounded-lg border px-4 py-2.5 text-xs font-medium ${
              banner.kind === "error"
                ? "border-rose-200 bg-rose-50 text-rose-800"
                : "border-emerald-200 bg-emerald-50 text-emerald-800"
            }`}
          >
            {banner.text}
          </div>
        )}

        {handover?.status !== "approved" &&
          (openConflictCount > 0 || unreviewedCriticalCount > 0 || staleCount > 0) && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
              <span className="font-semibold">Approval Blocked: </span>
              {openConflictCount > 0 && `${openConflictCount} unresolved conflict(s). `}
              {staleCount > 0 && `${staleCount} stale claim(s) need re-review after source update. `}
              {unreviewedCriticalCount > 0 &&
                `${unreviewedCriticalCount} critical claim(s) still need reviewer confirmation/edit/rejection.`}
            </div>
          )}

        <div className="flex items-center gap-2 overflow-x-auto border-b border-slate-200">
          {(
            [
              { id: "claims", label: `Handover Claims (${handover?.claims.length ?? 0})` },
              {
                id: "conflicts",
                label: `Conflicts Ledger (${openConflictCount} open)`,
              },
              {
                id: "responsibilities",
                label: `Responsibilities (${responsibilities.length})`,
              },
              {
                id: "clarifications",
                label: `Clarifications (${clarifications.length})`,
              },
            ] as const
          ).map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`border-b-2 px-4 py-2.5 text-xs font-semibold transition ${
                tab === t.id
                  ? "border-teal-600 text-[#0f2942]"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {loading && !handover && (
          <div className="space-y-3">
            {[1, 2, 3].map((n) => (
              <div key={n} className="h-24 animate-pulse rounded-xl border border-slate-200 bg-white" />
            ))}
          </div>
        )}

        {tab === "claims" && !loading && (
          <div className="space-y-6">
            {CLAIM_GROUPS.map((group) => {
              const items = (handover?.claims || []).filter((c) => c.type === group.key);
              if (items.length === 0) return null;

              return (
                <section key={group.key} className="space-y-2.5">
                  <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                    {group.label}
                  </h2>
                  <div className="space-y-2.5">
                    {items.map((claim) => {
                      const isReviewer = activeUser?.role === "reviewer" && handover?.status !== "approved";
                      return (
                        <div
                          key={claim.id}
                          className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="flex-1 space-y-1.5">
                              <div className="flex items-center gap-2">
                                <EvidenceBadge state={claim.evidence_state} />
                                {claim.is_stale && (
                                  <span className="rounded-full bg-orange-50 px-2.5 py-0.5 text-xs font-medium text-orange-800 ring-1 ring-orange-300">
                                    Stale · Re-review required
                                  </span>
                                )}
                                <span className="text-[11px] text-slate-400">
                                  {claim.evidence.length} source passage(s)
                                </span>
                              </div>

                              {editingId === claim.id ? (
                                <div className="mt-2 flex gap-2">
                                  <input
                                    type="text"
                                    value={editDraft}
                                    onChange={(e) => setEditDraft(e.target.value)}
                                    className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-xs"
                                  />
                                  <button
                                    onClick={() =>
                                      handleClaimAction(claim.id, "edit", { new_text: editDraft })
                                    }
                                    className="rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white"
                                  >
                                    Save
                                  </button>
                                  <button
                                    onClick={() => setEditingId(null)}
                                    className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600"
                                  >
                                    Cancel
                                  </button>
                                </div>
                              ) : (
                                <p className="text-sm font-medium text-slate-900">{claim.text}</p>
                              )}

                              {claim.limitation_note && (
                                <p className="text-xs text-rose-700">
                                  <span className="font-semibold">Limitation:</span>{" "}
                                  {claim.limitation_note}
                                </p>
                              )}

                              {claim.is_stale && claim.source_diff && (
                                <details className="mt-2 rounded-lg border border-orange-200 bg-orange-50/60 p-2.5 text-xs">
                                  <summary className="cursor-pointer font-semibold text-orange-900">
                                    {claim.stale_reason || "Source changed — view diff"}
                                  </summary>
                                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-slate-800">
                                    {claim.source_diff}
                                  </pre>
                                </details>
                              )}

                              {limitationId === claim.id && (
                                <div className="mt-2 flex gap-2">
                                  <input
                                    type="text"
                                    value={limitationDraft}
                                    onChange={(e) => setLimitationDraft(e.target.value)}
                                    placeholder="Add explicit limitation or gap note..."
                                    className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-xs"
                                  />
                                  <button
                                    onClick={() =>
                                      handleClaimAction(claim.id, "add_limitation", {
                                        limitation_note: limitationDraft,
                                      })
                                    }
                                    className="rounded-md bg-[#0f2942] px-3 py-1.5 text-xs font-medium text-white"
                                  >
                                    Save Note
                                  </button>
                                  <button
                                    onClick={() => setLimitationId(null)}
                                    className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600"
                                  >
                                    Cancel
                                  </button>
                                </div>
                              )}
                            </div>

                            <div className="flex flex-wrap items-center gap-1.5">
                              <button
                                onClick={() => setDrawerClaim(claim)}
                                className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-[#0f2942] hover:bg-slate-100"
                              >
                                Evidence
                              </button>
                              {isReviewer && (
                                <>
                                  <button
                                    onClick={() => handleClaimAction(claim.id, "confirm")}
                                    className="rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
                                  >
                                    Confirm
                                  </button>
                                  <button
                                    onClick={() => {
                                      setEditingId(claim.id);
                                      setEditDraft(claim.text);
                                    }}
                                    className="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200"
                                  >
                                    Edit
                                  </button>
                                  <button
                                    onClick={() => handleClaimAction(claim.id, "reject")}
                                    className="rounded-md bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100"
                                  >
                                    Reject
                                  </button>
                                  <button
                                    onClick={() => {
                                      setLimitationId(claim.id);
                                      setLimitationDraft(claim.limitation_note || "");
                                    }}
                                    className="rounded-md bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
                                  >
                                    Limitation
                                  </button>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        )}

        {tab === "conflicts" && (
          <ConflictsPanel
            conflicts={conflicts}
            viewerRole={activeUser?.role || "reviewer"}
            onResolve={handleResolveConflict}
          />
        )}

        {tab === "responsibilities" && (
          <ResponsibilityTable
            items={responsibilities}
            users={users}
            currentUser={activeUser}
            onConfirmOwner={async (id, ownerId) => {
              await apiFetch(
                `/projects/${activeProjectId}/responsibilities`,
                {
                  method: "POST",
                  body: JSON.stringify({
                    action: "confirm_owner",
                    responsibility_id: id,
                    confirmed_owner_id: ownerId,
                  }),
                },
                activeUserId
              );
              await loadWorkspace(activeProjectId, activeUserId);
            }}
            onAccept={async (id) => {
              await apiFetch(
                `/projects/${activeProjectId}/responsibilities`,
                {
                  method: "POST",
                  body: JSON.stringify({ action: "accept", responsibility_id: id }),
                },
                activeUserId
              );
              await loadWorkspace(activeProjectId, activeUserId);
            }}
          />
        )}

        {tab === "clarifications" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4">
              <div>
                <p className="text-sm font-semibold text-[#0f2942]">
                  Adaptive Clarification Questions
                </p>
                <p className="text-xs text-slate-500">
                  Targeted questions for the departing maintainer on open conflicts and missing gaps.
                </p>
              </div>
              <button
                onClick={async () => {
                  await apiFetch(
                    `/clarifications/generate?project_id=${activeProjectId}`,
                    { method: "POST" },
                    activeUserId
                  );
                  await loadWorkspace(activeProjectId, activeUserId);
                }}
                className="rounded-lg bg-[#0f2942] px-4 py-2 text-xs font-semibold text-white hover:bg-[#163a5c]"
              >
                Generate Questions
              </button>
            </div>

            {clarifications.map((cl) => (
              <div key={cl.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between text-xs">
                  <span className="rounded bg-slate-100 px-2 py-0.5 font-semibold uppercase text-slate-600">
                    {cl.target_type}
                  </span>
                  <span className="text-slate-400">
                    Asked to: {cl.asked_to?.name || "Departing Maintainer"} · {cl.status}
                  </span>
                </div>
                <p className="mt-2 text-sm font-medium text-slate-900">{cl.question}</p>
                {cl.answer_text ? (
                  <div className="mt-3 rounded-lg border border-teal-200 bg-teal-50/60 p-3 text-xs text-teal-950">
                    <span className="font-semibold">
                      {cl.answered_by?.name} ({cl.answered_by?.role}):{" "}
                    </span>
                    {cl.answer_text}
                  </div>
                ) : (
                  <div className="mt-3 flex gap-2">
                    <input
                      type="text"
                      value={clarificationDrafts[cl.id] || ""}
                      onChange={(e) =>
                        setClarificationDrafts((prev) => ({ ...prev, [cl.id]: e.target.value }))
                      }
                      placeholder="Record attributed answer from departing maintainer..."
                      className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
                    />
                    <button
                      onClick={async () => {
                        const ans = (clarificationDrafts[cl.id] || "").trim();
                        if (!ans) return;
                        await apiFetch(
                          `/clarifications/${cl.id}/answer`,
                          { method: "POST", body: JSON.stringify({ answer_text: ans }) },
                          activeUserId
                        );
                        await loadWorkspace(activeProjectId, activeUserId);
                      }}
                      className="rounded-lg bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-teal-700"
                    >
                      Save Answer
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>

      <EvidenceDrawer claim={drawerClaim} onClose={() => setDrawerClaim(null)} />
    </div>
  );
}

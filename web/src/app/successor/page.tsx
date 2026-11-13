"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EvidenceBadge } from "@/components/EvidenceBadge";
import { EvidenceDrawer } from "@/components/EvidenceDrawer";
import { RehearsalPanel } from "@/components/RehearsalPanel";
import { ResponsibilityTable } from "@/components/ResponsibilityTable";
import {
  apiFetch,
  type ClaimItem,
  type HandoverData,
  type Project,
  type ReadinessSummary,
  type RehearsalResult,
  type RehearsalTask,
  type ResponsibilityItem,
  type User,
} from "@/lib/api";

export default function SuccessorPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [activeUserId, setActiveUserId] = useState<string>("");
  const [projectId, setProjectId] = useState<string>("");

  const [handover, setHandover] = useState<HandoverData | null>(null);
  const [notApprovedMsg, setNotApprovedMsg] = useState<string | null>(null);
  const [responsibilities, setResponsibilities] = useState<ResponsibilityItem[]>([]);
  const [rehearsalTasks, setRehearsalTasks] = useState<RehearsalTask[]>([]);
  const [rehearsalResults, setRehearsalResults] = useState<RehearsalResult[]>([]);
  const [readiness, setReadiness] = useState<ReadinessSummary | null>(null);
  const [drawerClaim, setDrawerClaim] = useState<ClaimItem | null>(null);
  const [receiptNotes, setReceiptNotes] = useState<string>("");
  const [exportText, setExportText] = useState<string | null>(null);
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
    const successor = uList.find((u) => u.role === "successor") || uList[0];
    if (successor) setActiveUserId(successor.id);
    if (pList[0]) setProjectId(pList[0].id);
  }, []);

  const loadApproved = useCallback(async (pid: string, uid: string) => {
    if (!pid || !uid) return;
    setLoading(true);
    setNotApprovedMsg(null);
    try {
      try {
        const hv = await apiFetch<HandoverData>(`/handovers/approved?project_id=${pid}`, {}, uid);
        setHandover(hv);
      } catch (err) {
        setHandover(null);
        setNotApprovedMsg(err instanceof Error ? err.message : "No approved handover available yet.");
      }
      const [resp, reh, ready] = await Promise.all([
        apiFetch<{ responsibilities: ResponsibilityItem[] }>(
          `/projects/${pid}/responsibilities`,
          {},
          uid
        ),
        apiFetch<{ tasks: RehearsalTask[]; results: RehearsalResult[] }>(
          `/projects/${pid}/rehearsal`,
          {},
          uid
        ),
        apiFetch<ReadinessSummary>(`/projects/${pid}/rehearsal/readiness`, {}, uid),
      ]);
      setResponsibilities(resp.responsibilities);
      setRehearsalTasks(reh.tasks);
      setRehearsalResults(reh.results);
      setReadiness(ready);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBootstrap().catch((e) => setBanner({ kind: "error", text: e.message }));
  }, [loadBootstrap]);

  useEffect(() => {
    if (projectId && activeUserId) {
      loadApproved(projectId, activeUserId).catch((e) =>
        setBanner({ kind: "error", text: e.message })
      );
    }
  }, [projectId, activeUserId, loadApproved]);

  const myReceipt = handover?.receipts.find((r) => r.successor_id === activeUserId);

  const handleAcknowledge = async () => {
    if (!handover) return;
    setBanner(null);
    try {
      await apiFetch(
        `/handovers/${handover.id}/acknowledge`,
        {
          method: "POST",
          body: JSON.stringify({ notes: receiptNotes.trim() || "Received and reviewed." }),
        },
        activeUserId
      );
      setBanner({ kind: "ok", text: "Handover receipt acknowledged." });
      await loadApproved(projectId, activeUserId);
    } catch (err) {
      setBanner({ kind: "error", text: err instanceof Error ? err.message : "Acknowledgement failed" });
    }
  };

  const handleExport = async () => {
    if (!handover) return;
    const res = await apiFetch<{ content: string }>(
      `/handovers/${handover.id}/export`,
      {},
      activeUserId
    );
    setExportText(res.content);
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
              Successor Delivery
            </span>
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
            <Link
              href="/reviewer"
              className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-white/10"
            >
              ← Reviewer Console
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

        {loading && (
          <div className="space-y-3">
            {[1, 2].map((n) => (
              <div key={n} className="h-24 animate-pulse rounded-xl border border-slate-200 bg-white" />
            ))}
          </div>
        )}

        {!loading && notApprovedMsg && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
            <p className="font-semibold">Awaiting Reviewer Approval</p>
            <p className="mt-1 text-xs">{notApprovedMsg}</p>
          </div>
        )}

        {handover && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-teal-700">
                  Approved Handover v{handover.version}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Scoped to your role ({handover.viewer_role}). Restricted sources remain hidden.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={handleExport}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-[#0f2942] hover:bg-slate-50"
                >
                  Export Markdown
                </button>
                {myReceipt ? (
                  <span className="rounded-lg bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-200">
                    Acknowledged {new Date(myReceipt.acknowledged_at).toLocaleString()}
                  </span>
                ) : activeUser?.role === "successor" ? (
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={receiptNotes}
                      onChange={(e) => setReceiptNotes(e.target.value)}
                      placeholder="Optional receipt note..."
                      className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
                    />
                    <button
                      onClick={handleAcknowledge}
                      className="rounded-lg bg-teal-600 px-4 py-2 text-xs font-semibold text-white hover:bg-teal-700"
                    >
                      Acknowledge Receipt
                    </button>
                  </div>
                ) : null}
              </div>
            </div>

            {exportText && (
              <pre className="overflow-x-auto rounded-xl border border-slate-200 bg-slate-900 p-4 text-xs text-slate-100">
                {exportText}
              </pre>
            )}

            <div className="space-y-3">
              {handover.claims.map((claim) => {
                const hasRestrictedEvidence = claim.evidence.some((e) => e.restricted);
                return (
                  <div
                    key={claim.id}
                    className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                            {claim.type.replace("_", " ")}
                          </span>
                          <EvidenceBadge state={claim.evidence_state} />
                          {hasRestrictedEvidence && (
                            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200">
                              Evidence not available to you
                            </span>
                          )}
                        </div>
                        <p className="text-sm font-medium text-slate-900">{claim.text}</p>
                        {claim.limitation_note && (
                          <p className="text-xs text-rose-700">
                            <span className="font-semibold">Limitation:</span> {claim.limitation_note}
                          </p>
                        )}
                      </div>
                      <button
                        onClick={() => setDrawerClaim(claim)}
                        className="rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-[#0f2942] hover:bg-slate-100"
                      >
                        Inspect Evidence
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        <section className="space-y-3">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Successor Continuation Rehearsal
          </h2>
          <RehearsalPanel
            tasks={rehearsalTasks}
            results={rehearsalResults}
            claims={handover?.claims || []}
            responsibilities={responsibilities}
            readiness={readiness}
            onSubmitTask={async (payload) => {
              await apiFetch(
                `/projects/${projectId}/rehearsal/submit`,
                { method: "POST", body: JSON.stringify(payload) },
                activeUserId
              );
              await loadApproved(projectId, activeUserId);
            }}
          />
        </section>

        <section className="space-y-2">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Responsibility Acceptance
          </h2>
          <ResponsibilityTable
            items={responsibilities}
            users={users}
            currentUser={activeUser}
            onConfirmOwner={async () => {}}
            onAccept={async (id) => {
              await apiFetch(
                `/projects/${projectId}/responsibilities`,
                {
                  method: "POST",
                  body: JSON.stringify({ action: "accept", responsibility_id: id }),
                },
                activeUserId
              );
              await loadApproved(projectId, activeUserId);
            }}
          />
        </section>
      </main>

      <EvidenceDrawer claim={drawerClaim} onClose={() => setDrawerClaim(null)} />
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import type {
  ClaimItem,
  ReadinessSummary,
  RehearsalResult,
  RehearsalTask,
  ResponsibilityItem,
} from "@/lib/api";

interface RehearsalPanelProps {
  tasks: RehearsalTask[];
  results: RehearsalResult[];
  claims: ClaimItem[];
  responsibilities: ResponsibilityItem[];
  readiness: ReadinessSummary | null;
  onSubmitTask: (payload: {
    rehearsal_task_id: string;
    answer_text: string;
    evidence_claim_ids: string[];
    gaps_hit: string[];
    duration_seconds: number;
    responsibility_decisions: { responsibility_id: string; decision: "accept" | "block"; note?: string }[];
  }) => Promise<void>;
}

const READINESS_BADGE: Record<ReadinessSummary["readiness_status"], { label: string; cls: string }> = {
  not_started: { label: "Not Started", cls: "bg-slate-100 text-slate-700 ring-slate-200" },
  needs_followup: { label: "Needs Follow-up", cls: "bg-amber-50 text-amber-800 ring-amber-300" },
  ready: { label: "Ready for Handover", cls: "bg-emerald-50 text-emerald-800 ring-emerald-200" },
};

export function RehearsalPanel({
  tasks,
  results,
  claims,
  responsibilities,
  readiness,
  onSubmitTask,
}: RehearsalPanelProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [selectedClaims, setSelectedClaims] = useState<Record<string, string[]>>({});
  const [gapsInput, setGapsInput] = useState<Record<string, string>>({});
  const [respDecisions, setRespDecisions] = useState<Record<string, "accept" | "block">>({});
  const [elapsedSec, setElapsedSec] = useState<number>(0);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);

  useEffect(() => {
    const id = setInterval(() => setElapsedSec((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const latestByTask = new Map<string, RehearsalResult>();
  for (const r of results) {
    if (!latestByTask.has(r.rehearsal_task_id)) {
      latestByTask.set(r.rehearsal_task_id, r);
    }
  }

  const badge = readiness ? READINESS_BADGE[readiness.readiness_status] : READINESS_BADGE.not_started;

  return (
    <div className="space-y-4">
      {readiness && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-[#0f2942]">
                Continuation Readiness Summary
              </h3>
              <p className="text-xs text-slate-500">
                Computed from task outcomes, evidence cited, gaps hit, and responsibility decisions.
              </p>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ${badge.cls}`}>
              {badge.label}
            </span>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
            <div className="rounded-lg bg-slate-50 p-3">
              <p className="text-[11px] text-slate-500">Tasks Passed</p>
              <p className="mt-0.5 text-base font-bold text-slate-900">
                {readiness.tasks_passed} / {readiness.tasks_total}
              </p>
            </div>
            <div className="rounded-lg bg-slate-50 p-3">
              <p className="text-[11px] text-slate-500">Total Time</p>
              <p className="mt-0.5 text-base font-bold text-slate-900">
                {readiness.total_duration_seconds}s
              </p>
            </div>
            <div className="rounded-lg bg-slate-50 p-3">
              <p className="text-[11px] text-slate-500">Gaps Hit</p>
              <p className="mt-0.5 text-base font-bold text-slate-900">
                {readiness.gaps_encountered.length}
              </p>
            </div>
            <div className="rounded-lg bg-slate-50 p-3">
              <p className="text-[11px] text-slate-500">Accepted</p>
              <p className="mt-0.5 text-base font-bold text-emerald-700">
                {readiness.responsibilities_accepted} / {readiness.responsibilities_total}
              </p>
            </div>
            <div className="rounded-lg bg-slate-50 p-3">
              <p className="text-[11px] text-slate-500">Blocked</p>
              <p className="mt-0.5 text-base font-bold text-rose-700">
                {readiness.responsibilities_blocked}
              </p>
            </div>
          </div>
        </div>
      )}

      {tasks.map((task) => {
        const prev = latestByTask.get(task.id);
        const picked = selectedClaims[task.id] || [];

        return (
          <div key={task.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-teal-700">
                  Rehearsal Task {task.task_order}
                </p>
                <h4 className="text-sm font-semibold text-[#0f2942]">{task.title}</h4>
              </div>
              {prev ? (
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${
                    prev.passed
                      ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
                      : "bg-amber-50 text-amber-800 ring-amber-300"
                  }`}
                >
                  {prev.passed ? "Passed" : "Needs Follow-up"} · {prev.duration_seconds ?? 0}s
                </span>
              ) : (
                <span className="text-xs text-slate-400">Session timer: {elapsedSec}s</span>
              )}
            </div>

            <p className="mt-1.5 text-xs text-slate-600">{task.prompt}</p>

            <div className="mt-3 space-y-3">
              <textarea
                rows={2}
                value={answers[task.id] ?? prev?.answer_text ?? ""}
                onChange={(e) => setAnswers((p) => ({ ...p, [task.id]: e.target.value }))}
                placeholder="Write your answer grounded in the handover evidence..."
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-teal-600 focus:outline-none"
              />

              {claims.length > 0 && (
                <div>
                  <p className="text-[11px] font-semibold text-slate-500">Cite Supporting Claims:</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {claims.slice(0, 6).map((c) => {
                      const active = picked.includes(c.id);
                      return (
                        <button
                          key={c.id}
                          type="button"
                          onClick={() =>
                            setSelectedClaims((prevMap) => ({
                              ...prevMap,
                              [task.id]: active
                                ? picked.filter((id) => id !== c.id)
                                : [...picked, c.id],
                            }))
                          }
                          className={`max-w-xs truncate rounded-md border px-2 py-1 text-[11px] ${
                            active
                              ? "border-teal-600 bg-teal-50 font-medium text-teal-900"
                              : "border-slate-200 bg-slate-50 text-slate-600"
                          }`}
                          title={c.text}
                        >
                          {c.text}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <input
                  type="text"
                  value={gapsInput[task.id] || ""}
                  onChange={(e) => setGapsInput((p) => ({ ...p, [task.id]: e.target.value }))}
                  placeholder="Gaps encountered (comma-separated, optional)..."
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
                />

                {task.task_order === 2 && responsibilities.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2">
                    {responsibilities.map((r) => (
                      <div key={r.id} className="flex items-center gap-1 text-[11px]">
                        <span className="max-w-[140px] truncate font-medium text-slate-700">
                          {r.item}:
                        </span>
                        <select
                          value={respDecisions[r.id] || "accept"}
                          onChange={(e) =>
                            setRespDecisions((p) => ({
                              ...p,
                              [r.id]: e.target.value as "accept" | "block",
                            }))
                          }
                          className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px]"
                        >
                          <option value="accept">Accept</option>
                          <option value="block">Block</option>
                        </select>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex justify-end">
                <button
                  disabled={busyTaskId === task.id}
                  onClick={async () => {
                    const text = (answers[task.id] ?? prev?.answer_text ?? "").trim();
                    if (!text) return;
                    setBusyTaskId(task.id);
                    try {
                      const gaps = (gapsInput[task.id] || "")
                        .split(",")
                        .map((g) => g.trim())
                        .filter(Boolean);
                      const decs =
                        task.task_order === 2
                          ? responsibilities.map((r) => ({
                              responsibility_id: r.id,
                              decision: respDecisions[r.id] || "accept",
                            }))
                          : [];
                      await onSubmitTask({
                        rehearsal_task_id: task.id,
                        answer_text: text,
                        evidence_claim_ids: picked,
                        gaps_hit: gaps,
                        duration_seconds: elapsedSec,
                        responsibility_decisions: decs,
                      });
                    } finally {
                      setBusyTaskId(null);
                    }
                  }}
                  className="rounded-lg bg-[#0f2942] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#163a5c] disabled:opacity-50"
                >
                  {busyTaskId === task.id ? "Submitting..." : "Submit Rehearsal Task"}
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

"use client";

import { useState } from "react";
import type { ConflictItem, UserRole } from "@/lib/api";

interface ConflictsPanelProps {
  conflicts: ConflictItem[];
  viewerRole: UserRole;
  onResolve: (conflictId: string, winningClaimId: string, note: string) => Promise<void>;
}

export function ConflictsPanel({ conflicts, viewerRole, onResolve }: ConflictsPanelProps) {
  const [selectedWinner, setSelectedWinner] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (conflicts.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
        No conflicts detected.
      </div>
    );
  }

  const handleSubmit = async (cf: ConflictItem) => {
    const winner = selectedWinner[cf.id] || cf.sides[0]?.claim_id;
    const note = (notes[cf.id] || "").trim();
    if (!winner || note.length < 3) {
      setError("Select the accurate claim and enter a brief explanation (min 3 chars).");
      return;
    }
    setError(null);
    setBusyId(cf.id);
    try {
      await onResolve(cf.id, winner, note);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve conflict");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-800">
          {error}
        </div>
      )}

      {conflicts.map((cf) => {
        const isOpen = cf.status === "open";
        const chosen = selectedWinner[cf.id] || cf.sides[0]?.claim_id || "";

        return (
          <div
            key={cf.id}
            className={`rounded-xl border bg-white p-5 shadow-sm ${
              isOpen ? "border-amber-300" : "border-slate-200"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-[#0f2942]">{cf.title}</h3>
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${
                  isOpen
                    ? "bg-amber-50 text-amber-800 ring-amber-300"
                    : "bg-emerald-50 text-emerald-800 ring-emerald-200"
                }`}
              >
                {isOpen ? "Open Conflict" : "Resolved"}
              </span>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              {cf.sides.map((side) => {
                const isWinner = cf.winning_claim_id === side.claim_id;
                const isSelected = isOpen && chosen === side.claim_id;

                return (
                  <div
                    key={side.claim_id}
                    onClick={() => {
                      if (isOpen && viewerRole === "reviewer") {
                        setSelectedWinner((prev) => ({ ...prev, [cf.id]: side.claim_id }));
                      }
                    }}
                    className={`rounded-lg border p-4 transition ${
                      isWinner
                        ? "border-emerald-400 bg-emerald-50/40"
                        : isSelected
                          ? "border-teal-600 bg-teal-50/30 ring-1 ring-teal-500"
                          : "border-slate-200 bg-slate-50/60"
                    } ${isOpen && viewerRole === "reviewer" ? "cursor-pointer hover:border-teal-500" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <span className="font-semibold uppercase tracking-wide text-slate-500">
                        {isWinner ? "Confirmed Truth" : side.evidence_state}
                      </span>
                      {isOpen && viewerRole === "reviewer" && (
                        <input
                          type="radio"
                          name={`winner-${cf.id}`}
                          checked={isSelected}
                          onChange={() =>
                            setSelectedWinner((prev) => ({ ...prev, [cf.id]: side.claim_id }))
                          }
                          className="accent-teal-600"
                        />
                      )}
                    </div>
                    <p className="mt-1.5 text-sm font-medium text-slate-900">{side.text}</p>

                    <div className="mt-3 space-y-2">
                      {side.passages.map((p, idx) => (
                        <div key={idx} className="rounded border border-slate-200 bg-white p-2.5 text-xs">
                          <div className="flex items-center justify-between text-[11px] text-slate-500">
                            <span className="font-semibold text-[#0f2942]">{p.source_title}</span>
                            <span>
                              {p.source_date ? new Date(p.source_date).toLocaleDateString() : "No date"}
                              {p.version_sha ? ` · ${p.version_sha.slice(0, 7)}` : ""}
                            </span>
                          </div>
                          <p className="mt-1 italic text-slate-700">&ldquo;{p.quote_span}&rdquo;</p>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {isOpen && viewerRole === "reviewer" && (
              <div className="mt-4 flex flex-col gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:items-center">
                <input
                  type="text"
                  value={notes[cf.id] || ""}
                  onChange={(e) => setNotes((prev) => ({ ...prev, [cf.id]: e.target.value }))}
                  placeholder="Required explanation (e.g., README is outdated; Oct 28 note reflects live traffic)..."
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-teal-600 focus:outline-none"
                />
                <button
                  onClick={() => handleSubmit(cf)}
                  disabled={busyId === cf.id}
                  className="rounded-lg bg-[#0f2942] px-4 py-2 text-xs font-semibold text-white hover:bg-[#163a5c] disabled:opacity-50"
                >
                  {busyId === cf.id ? "Resolving..." : "Resolve Conflict"}
                </button>
              </div>
            )}

            {!isOpen && cf.resolution_note && (
              <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50/70 px-4 py-2.5 text-xs text-emerald-950">
                <span className="font-semibold">Resolution Note: </span>
                {cf.resolution_note}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

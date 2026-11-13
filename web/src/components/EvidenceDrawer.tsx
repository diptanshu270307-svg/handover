"use client";

import type { ClaimItem } from "@/lib/api";
import { EvidenceBadge } from "./EvidenceBadge";

interface EvidenceDrawerProps {
  claim: ClaimItem | null;
  onClose: () => void;
}

export function EvidenceDrawer({ claim, onClose }: EvidenceDrawerProps) {
  if (!claim) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40 backdrop-blur-[1px]">
      <div className="flex h-full w-full max-w-lg flex-col bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 bg-[#0f2942] px-6 py-4 text-white">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-teal-300">
              Evidence &amp; Provenance
            </p>
            <h2 className="text-sm font-semibold capitalize">{claim.type.replace("_", " ")} Claim</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-md px-2.5 py-1 text-xs font-medium text-slate-200 hover:bg-white/10"
          >
            Close
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto p-6">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <EvidenceBadge state={claim.evidence_state} />
            </div>
            <p className="text-sm font-medium text-slate-900">{claim.text}</p>
            {claim.limitation_note && (
              <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
                <span className="font-semibold">Limitation: </span>
                {claim.limitation_note}
              </div>
            )}
          </div>

          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Source Passages ({claim.evidence.length})
            </h3>
            {claim.evidence.length === 0 ? (
              <p className="mt-2 rounded-lg border border-dashed border-slate-200 p-4 text-xs text-slate-500">
                No supporting passage. Marked as missing evidence.
              </p>
            ) : (
              <div className="mt-2 space-y-3">
                {claim.evidence.map((ev, idx) =>
                  ev.restricted ? (
                    <div
                      key={idx}
                      className="rounded-lg border border-slate-200 bg-slate-100 p-4 text-xs text-slate-600"
                    >
                      {ev.message || "Evidence not available to you"}
                    </div>
                  ) : (
                    <div key={ev.id || idx} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span className="font-semibold text-[#0f2942]">{ev.source_title}</span>
                        <span className="rounded bg-slate-200/80 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                          {ev.version_sha ? `sha:${ev.version_sha.slice(0, 7)}` : ev.source_type}
                        </span>
                      </div>
                      <blockquote className="mt-2 border-l-2 border-teal-500 pl-3 text-xs italic text-slate-800">
                        &ldquo;{ev.quote_span}&rdquo;
                      </blockquote>
                      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
                        <span>{ev.source_date ? new Date(ev.source_date).toLocaleDateString() : "No date"}</span>
                        <span className="truncate font-mono text-teal-700" title={ev.source_uri}>
                          {ev.source_uri}
                        </span>
                      </div>
                    </div>
                  )
                )}
              </div>
            )}
          </div>

          {claim.reviews.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Review History ({claim.reviews.length})
              </h3>
              <div className="mt-2 space-y-2">
                {claim.reviews.map((rv) => (
                  <div key={rv.id} className="rounded-md border border-slate-200 bg-white p-3 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold capitalize text-slate-800">
                        {rv.action.replace("_", " ")}
                      </span>
                      <span className="text-[11px] text-slate-400">
                        {new Date(rv.created_at).toLocaleString()}
                      </span>
                    </div>
                    {rv.note && <p className="mt-1 text-slate-600">{rv.note}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

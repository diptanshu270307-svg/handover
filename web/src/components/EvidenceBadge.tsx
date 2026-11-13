import type { ClaimItem } from "@/lib/api";

const STYLES: Record<ClaimItem["evidence_state"], { label: string; cls: string }> = {
  supported: {
    label: "Supported",
    cls: "bg-teal-50 text-teal-800 ring-teal-200",
  },
  human_confirmed: {
    label: "Confirmed",
    cls: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  },
  conflicting: {
    label: "Conflicting",
    cls: "bg-amber-50 text-amber-800 ring-amber-300",
  },
  missing: {
    label: "Missing Evidence",
    cls: "bg-rose-50 text-rose-800 ring-rose-200",
  },
  superseded: {
    label: "Superseded",
    cls: "bg-slate-100 text-slate-500 ring-slate-200 line-through",
  },
};

export function EvidenceBadge({ state }: { state: ClaimItem["evidence_state"] }) {
  const cfg = STYLES[state] || STYLES.supported;
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

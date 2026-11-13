"use client";

import { useState } from "react";
import type { ResponsibilityItem, User } from "@/lib/api";

interface ResponsibilityTableProps {
  items: ResponsibilityItem[];
  users: User[];
  currentUser: User | null;
  onConfirmOwner: (responsibilityId: string, ownerId: string) => Promise<void>;
  onAccept: (responsibilityId: string) => Promise<void>;
}

const STATUS_STYLE: Record<ResponsibilityItem["status"], string> = {
  unassigned: "bg-rose-50 text-rose-800 ring-rose-200",
  suggested: "bg-amber-50 text-amber-800 ring-amber-200",
  confirmed: "bg-teal-50 text-teal-800 ring-teal-200",
  accepted: "bg-emerald-50 text-emerald-800 ring-emerald-200",
};

export function ResponsibilityTable({
  items,
  users,
  currentUser,
  onConfirmOwner,
  onAccept,
}: ResponsibilityTableProps) {
  const [selectedOwners, setSelectedOwners] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const defaultCandidate = users.find((u) => u.role === "successor")?.id || users[0]?.id || "";

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-[680px] w-full text-left text-xs">
        <thead className="border-b border-slate-200 bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-4 py-3">Workstream / Item</th>
            <th className="px-4 py-3">Suggested Expert</th>
            <th className="px-4 py-3">Confirmed Owner</th>
            <th className="px-4 py-3">Accepted Successor</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3 text-right">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((r) => {
            const pick = selectedOwners[r.id] || r.confirmed_owner?.id || defaultCandidate;
            const canConfirm = currentUser?.role === "reviewer" && r.status !== "accepted";
            const canAccept =
              currentUser?.role === "successor" &&
              r.status === "confirmed" &&
              r.confirmed_owner?.id === currentUser.id;

            return (
              <tr key={r.id} className="hover:bg-slate-50/70">
                <td className="px-4 py-3">
                  <p className="font-semibold text-slate-900">{r.item}</p>
                  {r.description && <p className="mt-0.5 text-[11px] text-slate-500">{r.description}</p>}
                </td>
                <td className="px-4 py-3">
                  <p className="font-medium text-slate-800">
                    {r.suggested_expert ? r.suggested_expert.name : "None"}
                  </p>
                  {r.suggested_basis && (
                    <p className="mt-0.5 text-[11px] text-slate-400">{r.suggested_basis}</p>
                  )}
                </td>
                <td className="px-4 py-3">
                  {canConfirm ? (
                    <select
                      value={pick}
                      onChange={(e) =>
                        setSelectedOwners((prev) => ({ ...prev, [r.id]: e.target.value }))
                      }
                      className="rounded border border-slate-300 bg-white px-2 py-1 text-xs"
                    >
                      {users.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.name} ({u.role})
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="font-medium text-slate-800">
                      {r.confirmed_owner ? r.confirmed_owner.name : "Unconfirmed"}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span className="font-medium text-slate-800">
                    {r.accepted_by ? r.accepted_by.name : "Pending acceptance"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-medium capitalize ring-1 ${STATUS_STYLE[r.status]}`}
                  >
                    {r.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {canConfirm && (
                    <button
                      disabled={busyId === r.id || !pick}
                      onClick={async () => {
                        setBusyId(r.id);
                        try {
                          await onConfirmOwner(r.id, pick);
                        } finally {
                          setBusyId(null);
                        }
                      }}
                      className="rounded-md bg-[#0f2942] px-3 py-1 text-xs font-medium text-white hover:bg-[#163a5c] disabled:opacity-50"
                    >
                      Confirm Owner
                    </button>
                  )}
                  {canAccept && (
                    <button
                      disabled={busyId === r.id}
                      onClick={async () => {
                        setBusyId(r.id);
                        try {
                          await onAccept(r.id);
                        } finally {
                          setBusyId(null);
                        }
                      }}
                      className="rounded-md bg-teal-600 px-3 py-1 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-50"
                    >
                      Accept Ownership
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

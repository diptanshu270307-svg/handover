import Link from "next/link";

export default function HomePage() {
  return (
    <main className="min-h-screen bg-slate-50 px-6 py-12">
      <div className="mx-auto max-w-4xl rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-teal-600">
              Relay Handover System
            </p>
            <h1 className="mt-1 text-2xl font-bold text-[#0f2942]">
              Payments Migration — Demo Workspace
            </h1>
          </div>
          <span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-medium text-teal-800 ring-1 ring-teal-200">
            Source-Backed &amp; Permission-Scoped
          </span>
        </div>

        <p className="mt-3 text-sm text-slate-600">
          Inspect extracted claims with SHA-pinned citations, resolve conflicting evidence, confirm
          ownership, and run the successor continuation rehearsal.
        </p>

        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/reviewer"
            className="rounded-lg bg-[#0f2942] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#163a5c]"
          >
            Open Reviewer Console
          </Link>
          <Link
            href="/successor"
            className="rounded-lg border border-teal-600 bg-teal-50 px-5 py-2.5 text-sm font-semibold text-teal-800 hover:bg-teal-100"
          >
            Open Successor View &amp; Rehearsal
          </Link>
        </div>

        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">Outgoing Maintainer</p>
            <p className="mt-1 font-semibold text-slate-900">Maya Lin</p>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">Reviewer (Manager)</p>
            <p className="mt-1 font-semibold text-slate-900">Jordan Patel</p>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
            <p className="text-xs font-medium text-slate-500">Successor</p>
            <p className="mt-1 font-semibold text-slate-900">Alex Rivera</p>
          </div>
        </div>
      </div>
    </main>
  );
}

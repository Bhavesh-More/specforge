import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { useHealingEvents, useMutations } from "../hooks/useSpecForgeAPI";
import type { HealingEvent } from "../types";

function StatusBadge({ status }: { status: "APPLIED" | "PENDING_APPROVAL" | "REJECTED" }) {
  if (status === "APPLIED") {
    return (
      <span className="inline-flex px-2 py-[2px] rounded-pill text-xs text-sf-green bg-[rgba(62,207,142,0.1)] border border-[rgba(62,207,142,0.3)]">
        Applied
      </span>
    );
  }
  if (status === "PENDING_APPROVAL") {
    return (
      <span className="inline-flex px-2 py-[2px] rounded-pill text-xs text-sf-amber bg-[rgba(245,158,11,0.1)] border border-[rgba(245,158,11,0.3)]">
        Pending Approval
      </span>
    );
  }
  return (
    <span className="inline-flex px-2 py-[2px] rounded-pill text-xs text-sf-text-muted bg-sf-surface border border-sf-border-standard">
      Rejected
    </span>
  );
}

export function HealingPage() {
  const { data: events, isLoading } = useHealingEvents();
  const { approveHealingEvent, rejectHealingEvent } = useMutations();
  const [selected, setSelected] = useState<HealingEvent | null>(null);

  if (isLoading) return <Skeleton />;
  if (!events?.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <span className="text-5xl text-sf-border-standard">◆</span>
        <p className="text-base text-sf-text">No healing events</p>
        <p className="text-sm text-sf-text-muted">Healing events appear when nodes fail</p>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Table */}
      <div className="flex-1 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-sf-border shrink-0">
          <h2 className="text-lg text-sf-text">Healing Events</h2>
        </div>

        <div className="flex-1 overflow-y-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-sf-border">
                {["Triggered", "Node", "Template", "Trigger Type", "Patches", "Status"].map((col) => (
                  <th
                    key={col}
                    className="text-left font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-[10px]"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr
                  key={event.id}
                  onClick={() => setSelected(event)}
                  className="border-b border-sf-border cursor-pointer transition-colors duration-100 hover:bg-[rgba(255,255,255,0.03)]"
                >
                  <td className="px-4 py-3 text-xs text-sf-text-muted">
                    {formatDistanceToNow(new Date(event.triggered_at), { addSuffix: true })}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-sf-text">{event.node_id}</td>
                  <td className="px-4 py-3 text-xs text-sf-text-muted">{event.template_id.slice(0, 8)}…</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex px-2 py-[2px] rounded-pill text-xs font-mono uppercase text-sf-text-muted bg-sf-surface border border-sf-border-standard">
                      {event.trigger_type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-sf-text-muted">{event.patches.length}</td>
                  <td className="px-4 py-3">
                    <StatusBadge
                      status={
                        event.applied
                          ? "APPLIED"
                          : event.approved_by
                            ? "APPLIED"
                            : "PENDING_APPROVAL"
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail panel */}
      {selected && (
        <div className="w-[640px] shrink-0 flex flex-col h-full bg-sf-bg border-l border-sf-border-standard overflow-hidden animate-slide-in-right">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-sf-border">
            <div>
              <div className="text-base text-sf-text">Healing Event</div>
              <div className="font-mono text-xs text-sf-text-muted mt-0.5">{selected.node_id}</div>
            </div>
            <button
              onClick={() => setSelected(null)}
              className="p-1 text-sf-text-muted hover:text-sf-text transition-colors"
            >
              ✕
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-5 space-y-6">
            {/* Failure examples */}
            <div>
              <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
                Failure Examples
              </div>
              <div className="space-y-2">
                {selected.failure_examples.map((ex, i) => (
                  <pre
                    key={i}
                    className="bg-sf-bg-deep border border-sf-border-standard rounded-btn p-3 font-mono text-[11px] text-sf-red whitespace-pre-wrap"
                  >
                    {ex}
                  </pre>
                ))}
              </div>
            </div>

            <div className="border-t border-sf-border pt-5">
              {/* Rule file diff */}
              <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
                Rule File Diff
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="font-mono text-[10px] uppercase text-sf-text-muted mb-1.5">BEFORE</div>
                  <pre className="bg-sf-bg-deep border border-sf-border-standard rounded-btn p-3 font-mono text-[11px] text-sf-text-secondary whitespace-pre-wrap">
                    {selected.patches[0] ?? "# Original content"}
                  </pre>
                </div>
                <div>
                  <div className="font-mono text-[10px] uppercase text-sf-green mb-1.5">AFTER</div>
                  <pre className="bg-[rgba(62,207,142,0.03)] border border-[rgba(62,207,142,0.2)] rounded-btn p-3 font-mono text-[11px] text-sf-text-secondary whitespace-pre-wrap">
                    {selected.patches[1] ?? "# Patched content"}
                  </pre>
                </div>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 px-5 py-4 border-t border-sf-border">
            <button
              onClick={() => {
                rejectHealingEvent.mutate(selected.id);
                setSelected(null);
              }}
              className="px-4 py-[6px] rounded-btn text-sm text-sf-red border border-sf-red"
            >
              Reject
            </button>
            <button
              onClick={() => {
                approveHealingEvent.mutate(selected.id);
                setSelected(null);
              }}
              className="flex items-center gap-2 px-5 py-[6px] rounded-pill text-sm font-medium text-sf-green bg-transparent border border-[rgba(62,207,142,0.3)]"
            >
              Approve & Apply
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="px-6 py-4 space-y-3">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="h-12 rounded bg-sf-surface animate-pulse" />
      ))}
    </div>
  );
}

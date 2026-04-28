import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { useExecutions } from "../hooks/useSpecForgeAPI";
import { ExecutionDetailPanel } from "../components/ExecutionDetailPanel";
import type { ExecutionRun } from "../types";

const STATUS_CLASSES: Record<string, string> = {
  PENDING: "bg-[rgba(245,158,11,0.1)] border-[rgba(245,158,11,0.3)] text-sf-amber",
  RUNNING: "bg-[rgba(59,130,246,0.1)] border-[rgba(59,130,246,0.3)] text-sf-blue",
  COMPLETED: "bg-[rgba(62,207,142,0.1)] border-[rgba(62,207,142,0.3)] text-sf-green",
  FAILED: "bg-[rgba(239,68,68,0.1)] border-[rgba(239,68,68,0.3)] text-sf-red",
  CANCELLED: "bg-sf-surface border-sf-border-standard text-sf-text-muted",
};

function StatusBadge({ status }: { status: string }) {
  const isRunning = status === "RUNNING";
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-[2px] rounded-pill text-xs font-medium border ${STATUS_CLASSES[status]}`}>
      {isRunning && (
        <span className="w-1 h-1 rounded-full bg-sf-blue animate-pulse" />
      )}
      {status}
    </span>
  );
}

export function ExecutionsPage() {
  const { data: runs, isLoading } = useExecutions();
  const [selected, setSelected] = useState<ExecutionRun | null>(null);

  if (isLoading) return <Skeleton />;
  if (!runs?.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <span className="text-5xl text-sf-border-standard">◆</span>
        <p className="text-base text-sf-text">No executions yet</p>
        <p className="text-sm text-sf-text-muted">Run a template to see results here</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-6 py-4 border-b border-sf-border shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-lg text-sf-text">Executions</h2>
          <span className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted">
            {runs.length} runs
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-sf-border">
              {["Run ID", "Template", "Status", "Started", "Duration", "Nodes"].map((col) => (
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
            {runs.map((run) => (
              <tr
                key={run.id}
                onClick={() => setSelected(run)}
                className="border-b border-sf-border cursor-pointer transition-colors duration-100 hover:bg-[rgba(255,255,255,0.03)]"
              >
                <td className="px-4 py-3 font-mono text-xs text-sf-text-muted">
                  {run.id.slice(0, 8)}…
                </td>
                <td className="px-4 py-3 text-sm text-sf-text">{run.template_name}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={run.status} />
                </td>
                <td className="px-4 py-3 text-xs text-sf-text-muted">
                  {formatDistanceToNow(new Date(run.started_at), { addSuffix: true })}
                </td>
                <td className="px-4 py-3 text-xs text-sf-text-muted">
                  {run.total_execution_time_ms != null
                    ? `${(run.total_execution_time_ms / 1000).toFixed(1)}s`
                    : "—"}
                </td>
                <td className="px-4 py-3 text-xs text-sf-text-muted">
                  {run.node_results?.length ?? 0}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <ExecutionDetailPanel
          runId={selected.id}
          onClose={() => setSelected(null)}
        />
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

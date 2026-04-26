import { formatDistanceToNow } from "date-fns";
import { X, CheckCircle, XCircle, Loader, Circle } from "lucide-react";
import type { ExecutionRun, NodeStatus, ExecutionTier } from "../types";

const TIER_COLORS: Record<ExecutionTier, string> = {
  FAST: "text-sf-green",
  REPAIR: "text-sf-amber",
  DEEP: "text-sf-purple",
};

function StatusIcon({ status }: { status: NodeStatus }) {
  const iconProps = { size: 14 };
  switch (status) {
    case "PASSED_TIER1":
    case "PASSED_TIER2":
    case "PASSED_TIER3":
      return <CheckCircle {...iconProps} className="text-sf-green" />;
    case "FAILED":
      return <XCircle {...iconProps} className="text-sf-red" />;
    case "RUNNING":
      return <Loader {...iconProps} className="text-sf-blue animate-spin" />;
    default:
      return <Circle {...iconProps} className="text-sf-text-muted" />;
  }
}

interface Props {
  run: ExecutionRun;
  onClose: () => void;
}

export function ExecutionDetailPanel({ run, onClose }: Props) {
  const total = run.node_results?.length ?? 0;
  const completed = run.node_results?.filter(
    (n) => n.status.startsWith("PASSED") || n.status === "FAILED"
  ).length ?? 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.8)" }}
    >
      <div className="bg-sf-bg border border-sf-border-standard rounded-card w-full max-w-[1100px] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-sf-border">
          <div className="flex items-center gap-4">
            <span className="font-mono text-xs text-sf-text-muted">{run.id.slice(0, 8)}…</span>
            <span className="text-sm text-sf-text">{run.template_name}</span>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge2 status={run.status} />
            <button onClick={onClose} className="p-1 text-sf-text-muted hover:text-sf-text transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body — 3 columns */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left */}
          <div className="w-[200px] shrink-0 border-r border-sf-border overflow-y-auto p-4">
            <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
              Run Info
            </div>
            {[
              ["Run ID", run.id.slice(0, 8) + "…"],
              ["Template", run.template_name],
              ["Status", run.status],
              ["Started", formatDistanceToNow(new Date(run.started_at), { addSuffix: true })],
              [
                "Duration",
                run.total_execution_time_ms != null
                  ? `${(run.total_execution_time_ms / 1000).toFixed(1)}s`
                  : "—",
              ],
            ].map(([key, value]) => (
              <div key={key} className="flex flex-col py-2 border-b border-sf-border text-sm">
                <span className="text-xs text-sf-text-muted mb-0.5">{key}</span>
                <span className="text-sf-text font-mono text-xs">{value}</span>
              </div>
            ))}
          </div>

          {/* Center */}
          <div className="flex-1 overflow-y-auto p-4">
            <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
              Node Progress
            </div>
            <div className="space-y-2">
              {(run.node_results ?? []).map((node) => (
                <div
                  key={node.id}
                  className="flex items-center gap-3 bg-sf-surface border border-sf-border-standard rounded-btn p-3"
                >
                  <StatusIcon status={node.status as NodeStatus} />
                  <div className="flex-1">
                    <div className="font-mono text-xs text-sf-text">{node.node_id}</div>
                    <span className={`text-[10px] font-mono uppercase ${TIER_COLORS[node.tier_used]}`}>
                      {node.tier_used}
                    </span>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-[11px] text-sf-text-muted">
                      {node.execution_time_ms}ms
                    </div>
                    <div className="font-mono text-[10px] text-sf-text-muted">
                      #{node.attempt_count}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right */}
          <div className="w-[320px] shrink-0 bg-sf-bg-deep border-l border-sf-border flex flex-col">
            <div className="px-4 py-3 border-b border-sf-border">
              <span className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted">
                State.md
              </span>
            </div>
            <div className="flex-1 overflow-y-auto p-4 font-mono text-[11px] leading-[1.6] text-sf-text-secondary">
              {run.state_file_path ? (
                <pre className="whitespace-pre-wrap">{`# Execution State\n\nRun: ${run.id}\nTemplate: ${run.template_name}\nStatus: ${run.status}\n\n${completed}/${total} nodes complete`}</pre>
              ) : (
                <span className="text-sf-text-muted">No state file yet</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusBadge2({ status }: { status: string }) {
  const isRunning = status === "RUNNING";
  const classes =
    status === "RUNNING"
      ? "bg-[rgba(59,130,246,0.1)] border-[rgba(59,130,246,0.3)] text-sf-blue"
      : status === "COMPLETED"
        ? "bg-[rgba(62,207,142,0.1)] border-[rgba(62,207,142,0.3)] text-sf-green"
        : "bg-[rgba(239,68,68,0.1)] border-[rgba(239,68,68,0.3)] text-sf-red";

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-[2px] rounded-pill text-xs font-medium border ${classes}`}>
      {isRunning && <span className="w-1 h-1 rounded-full bg-sf-blue animate-pulse" />}
      {status}
    </span>
  );
}

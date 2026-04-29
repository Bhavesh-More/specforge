import { useEffect, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { X, CheckCircle, XCircle, Loader, Circle, ChevronRight } from "lucide-react";
import { useExecution } from "../hooks/useSpecForgeAPI";

const STATUS_ICON: Record<string, { icon: "check" | "x" | "loading" | "pending"; className: string }> = {
  passed_tier1: { icon: "check", className: "text-sf-green" },
  passed_tier2: { icon: "check", className: "text-sf-green" },
  passed_tier3: { icon: "check", className: "text-sf-green" },
  failed: { icon: "x", className: "text-sf-red" },
  running: { icon: "loading", className: "text-sf-blue" },
  pending: { icon: "pending", className: "text-sf-text-muted" },
};

function StatusIcon({ status }: { status: string }) {
  const s = status.toLowerCase().replace("passed_tier", "passed_tier");
  const cfg = STATUS_ICON[s] || STATUS_ICON.pending;
  const props = { size: 14 };
  if (cfg.icon === "check") return <CheckCircle {...props} className={cfg.className} />;
  if (cfg.icon === "x") return <XCircle {...props} className={cfg.className} />;
  if (cfg.icon === "loading") return <Loader {...props} className={`${cfg.className} animate-spin`} />;
  return <Circle {...props} className={cfg.className} />;
}

interface NodeEntry {
  node_id: string;
  status: string;
  tier_used: string;
  attempt_count: number;
  execution_time_ms: number;
  error_message: string | null;
  parsed_output: Record<string, unknown> | null;
  raw_output: string | null;
  validation_result?: {
    is_valid: boolean;
    errors: string[];
    raw_output: string;
    parsed_output: Record<string, unknown>;
    validation_time_ms: number;
  };
}

function getValidationErrors(node: NodeEntry): string[] {
  return node.validation_result?.errors ?? [];
}

interface Props {
  runId: string;
  onClose: () => void;
}

export function ExecutionDetailPanel({ runId, onClose }: Props) {
  const { data: run } = useExecution(runId);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => {
    if (run) {
      const entries = Object.values(run.node_results as unknown as Record<string, NodeEntry>);
      if (entries.length > 0 && !selectedNode) {
        setSelectedNode(entries[0].node_id);
      }
    }
  }, [run, selectedNode]);

  const nodeEntries: NodeEntry[] = run
    ? Array.isArray(run.node_results)
      ? run.node_results as unknown as NodeEntry[]
      : Object.values(run.node_results as Record<string, NodeEntry> || {})
    : [];

  const activeNode = nodeEntries.find((n) => n.node_id === selectedNode);
  const finalOutput = run?.final_output as Record<string, unknown> | null;

  function renderOutput(node: NodeEntry) {
    if (!node.parsed_output && !node.raw_output) {
      return <span className="text-sf-text-muted">No output yet</span>;
    }
    const data = node.parsed_output || (node.raw_output ? tryParseJSON(node.raw_output) : null);
    return <pre className="whitespace-pre-wrap text-xs leading-[1.7] text-sf-text">{JSON.stringify(data, null, 2)}</pre>;
  }

  if (!run) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.8)" }}>
        <div className="bg-sf-bg border border-sf-border-standard rounded-card w-full max-w-[1100px] max-h-[85vh] flex items-center justify-center">
          <span className="text-sf-text-muted font-mono text-sm">Loading execution details…</span>
        </div>
      </div>
    );
  }

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
            <span className="text-sm text-sf-text font-medium">{run.template_name}</span>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge status={run.status} />
            <button onClick={onClose} className="p-1 text-sf-text-muted hover:text-sf-text transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left — node list */}
          <div className="w-[220px] shrink-0 border-r border-sf-border overflow-y-auto p-4">
            <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
              Nodes ({nodeEntries.length})
            </div>
            <div className="space-y-1">
              {nodeEntries.map((node) => (
                <button
                  key={node.node_id}
                  onClick={() => setSelectedNode(node.node_id)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-btn text-left transition-colors ${
                    selectedNode === node.node_id
                      ? "bg-sf-surface border border-sf-border-standard"
                      : "hover:bg-[rgba(255,255,255,0.03)]"
                  }`}
                >
                  <StatusIcon status={node.status} />
                  <span className="font-mono text-xs text-sf-text truncate">{node.node_id}</span>
                  {selectedNode !== node.node_id && (
                    <ChevronRight size={12} className="shrink-0 text-sf-text-muted ml-auto" />
                  )}
                </button>
              ))}
            </div>

            {finalOutput && (
              <>
                <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3 mt-6">
                  Final Output
                </div>
                <button
                  onClick={() => setSelectedNode("__final__")}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-btn text-left transition-colors ${
                    selectedNode === "__final__"
                      ? "bg-sf-surface border border-sf-border-standard"
                      : "hover:bg-[rgba(255,255,255,0.03)]"
                  }`}
                >
                  <CheckCircle size={14} className="text-sf-green" />
                  <span className="font-mono text-xs text-sf-green">report</span>
                  <ChevronRight size={12} className="shrink-0 text-sf-text-muted ml-auto" />
                </button>
              </>
            )}
          </div>

          {/* Center — node details */}
          <div className="flex-1 overflow-y-auto p-4">
            {selectedNode === "__final__" ? (
              <div>
                <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
                  Final Output
                </div>
                <div className="bg-sf-surface border border-sf-border-standard rounded-btn p-4">
                  {finalOutput ? (
                    <pre className="whitespace-pre-wrap text-xs leading-[1.7] text-sf-text">{JSON.stringify(finalOutput, null, 2)}</pre>
                  ) : (
                    <span className="text-sf-text-muted">No final output</span>
                  )}
                </div>
              </div>
            ) : activeNode ? (
              <div>
                <div className="flex items-center gap-3 mb-4">
                  <span className="font-mono text-sm text-sf-text">{activeNode.node_id}</span>
                  <StatusIcon status={activeNode.status} />
                  <span className={`inline-flex px-2 py-[2px] rounded-pill text-[10px] font-mono uppercase ${
                    activeNode.tier_used === "FAST" ? "bg-sf-green/10 text-sf-green" :
                    activeNode.tier_used === "REPAIR" ? "bg-sf-amber/10 text-sf-amber" :
                    "bg-sf-purple/10 text-sf-purple"
                  }`}>
                    {activeNode.tier_used}
                  </span>
                  <span className="text-xs text-sf-text-muted font-mono">
                    {activeNode.execution_time_ms.toFixed(0)}ms · attempt {activeNode.attempt_count}
                  </span>
                </div>

                {getValidationErrors(activeNode).length > 0 && (
                  <div className="mb-4 p-3 bg-sf-red/10 border border-sf-red/30 rounded-btn">
                    <div className="font-mono text-xs text-sf-red mb-1">Validation Errors</div>
                    {getValidationErrors(activeNode).map((e, i) => (
                      <div key={i} className="text-xs text-sf-red/80 font-mono">• {e}</div>
                    ))}
                  </div>
                )}

                {activeNode.error_message && (
                  <div className="mb-4 p-3 bg-sf-red/10 border border-sf-red/30 rounded-btn">
                    <div className="font-mono text-xs text-sf-red mb-1">Error</div>
                    <div className="text-xs text-sf-red/80 font-mono">{activeNode.error_message}</div>
                  </div>
                )}

                <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-2">Parsed Output</div>
                <div className="bg-sf-surface border border-sf-border-standard rounded-btn p-4">
                  {renderOutput(activeNode)}
                </div>

                {activeNode.raw_output && !activeNode.parsed_output && (
                  <>
                    <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-2 mt-4">Raw Output</div>
                    <div className="bg-sf-surface border border-sf-border-standard rounded-btn p-4">
                      <pre className="whitespace-pre-wrap text-xs leading-[1.7] text-sf-text">{activeNode.raw_output}</pre>
                    </div>
                  </>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-sf-text-muted text-sm">
                Select a node to view its output
              </div>
            )}
          </div>

          {/* Right — summary */}
          <div className="w-[280px] shrink-0 bg-sf-bg-deep border-l border-sf-border flex flex-col">
            <div className="px-4 py-3 border-b border-sf-border">
              <span className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted">Run Summary</span>
            </div>
            <div className="p-4 space-y-3 overflow-y-auto">
              {[
                ["Run ID", run.id],
                ["Status", run.status],
                ["Started", formatDistanceToNow(new Date(run.started_at), { addSuffix: true })],
                ["Duration", run.total_execution_time_ms != null ? `${(run.total_execution_time_ms / 1000).toFixed(1)}s` : "—"],
                ["Nodes", `${nodeEntries.filter(n => n.status.toLowerCase().startsWith("passed")).length}/${nodeEntries.length} passed`],
              ].map(([key, value]) => (
                <div key={key} className="flex flex-col py-2 border-b border-sf-border text-sm">
                  <span className="text-xs text-sf-text-muted mb-0.5">{key}</span>
                  <span className="text-sf-text font-mono text-xs">{value}</span>
                </div>
              ))}

              {run.error_message && (
                <div className="p-3 bg-sf-red/10 border border-sf-red/30 rounded-btn">
                  <div className="font-mono text-xs text-sf-red mb-1">Error</div>
                  <div className="text-xs text-sf-text font-mono">{run.error_message}</div>
                </div>
              )}

              {run.input_data && Object.keys(run.input_data).length > 0 && (
                <>
                  <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mt-2 mb-1">Input Data</div>
                  <div className="bg-sf-surface border border-sf-border-standard rounded-btn p-3">
                    <pre className="whitespace-pre-wrap text-[11px] text-sf-text font-mono">{JSON.stringify(run.input_data, null, 2)}</pre>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
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

function tryParseJSON(str: string): Record<string, unknown> | string {
  try { return JSON.parse(str); }
  catch { return str; }
}
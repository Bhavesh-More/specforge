import { useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  useNodesState,
  useEdgesState,
  type Edge,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { X } from "lucide-react";
import type { CognitiveTemplate, NodeType } from "../types";

const NODE_TYPE_COLORS: Record<NodeType, string> = {
  standard: "#3b82f6",
  symbolic: "#f59e0b",
  adversarial: "#a855f7",
  lookahead: "#3ecf8e",
  parallel: "#6b7280",
};

interface Props {
  template: CognitiveTemplate;
  onClose: () => void;
  onRun?: (templateId: string, inputData: Record<string, unknown>) => void;
  isRunning?: boolean;
}

export function TemplateDetailModal({ template, onClose, onRun, isRunning }: Props) {
  const [showInput, setShowInput] = useState(false);
  const [inputValue, setInputValue] = useState("");

  function handleRunClick() {
    if (showInput) {
      onRun?.(template.template_id, {
        description: inputValue,
        raw_input: inputValue,
        input: inputValue,
      });
      setShowInput(false);
      setInputValue("");
    } else {
      setShowInput(true);
    }
  }

  function handleCancelRun() {
    setShowInput(false);
    setInputValue("");
  }

  const initialNodes = useMemo(() => {
    return (template.nodes || []).map((node, i) => ({
      id: node.node_id,
      position: { x: 250, y: i * 130 },
      data: { label: node.node_id, nodeType: node.node_type, description: node.description },
      style: {
        background: "#171717",
        border: `2px solid ${NODE_TYPE_COLORS[node.node_type]}66`,
        borderRadius: "6px",
        padding: "12px 14px",
        width: 180,
      },
    }));
  }, [template.nodes]);

  const initialEdges = useMemo(() => {
    const edges: Edge[] = [];
    template.nodes.forEach((node) => {
      node.depends_on.forEach((dep) => {
        edges.push({
          id: `${dep}-${node.node_id}`,
          source: dep,
          target: node.node_id,
          style: { stroke: "#363636", strokeWidth: 1.5 },
          animated: false,
          markerEnd: { type: MarkerType.ArrowClosed, color: "#363636" },
        });
      });
    });
    return edges;
  }, [template.nodes]);

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  const nodeTypes = useMemo(
    () => ({
      custom: ({ data }: { data: { label: string; nodeType: NodeType; description: string } }) => {
        const color = NODE_TYPE_COLORS[data.nodeType];
        return (
          <div className="relative" style={{ width: 180 }}>
            {/* Left accent bar */}
            <div
              className="absolute left-0 top-0 bottom-0 w-1 rounded-l"
              style={{ background: color }}
            />
            <div className="pl-3 pr-2 py-2">
              <div className="font-mono text-[11px] text-sf-text">{data.label}</div>
              <div
                className="font-mono text-[10px] uppercase mt-1"
                style={{ color }}
              >
                {data.nodeType}
              </div>
              <div className="text-[11px] text-sf-text-muted mt-1 truncate">
                {data.description}
              </div>
            </div>
          </div>
        );
      },
    }),
    []
  );

  const executionWaves = useMemo(() => {
    const waves: string[][] = [];
    const remaining = new Set(template.nodes.map((n) => n.node_id));
    const assigned = new Set<string>();

    while (remaining.size > 0) {
      const wave = template.nodes
        .filter((n) => !assigned.has(n.node_id))
        .filter((n) => n.depends_on.every((d) => assigned.has(d)))
        .map((n) => n.node_id);
      if (!wave.length) break;
      waves.push(wave);
      wave.forEach((id) => assigned.add(id));
      wave.forEach((id) => remaining.delete(id));
    }
    return waves;
  }, [template.nodes]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.8)" }}
    >
      {/* Inner panel */}
      <div className="bg-sf-bg border border-sf-border-standard rounded-card w-full max-w-[960px] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-5 border-b border-sf-border">
          <div>
            <h2 className="text-lg text-sf-text">{template.name}</h2>
            <p className="text-sm text-sf-text-muted mt-1">{template.description}</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="inline-flex px-2 py-[2px] rounded-pill text-xs text-sf-text-muted bg-sf-surface border border-sf-border-standard">
              v{template.version}
            </span>
            <button
              onClick={onClose}
              className="p-1 text-sf-text-muted hover:text-sf-text transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left panel */}
          <div className="w-[280px] shrink-0 border-r border-sf-border overflow-y-auto p-4">
            <div className="mb-6">
              <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
                Metadata
              </div>
              {[
                ["Template ID", template.template_id.slice(0, 8) + "…"],
                ["Author", template.author],
                ["Version", template.version],
                ["Schema", template.schema_version],
                ["Created", new Date(template.created_at).toLocaleDateString()],
                ["Tags", template.tags.join(", ")],
              ].map(([key, value]) => (
                <div
                  key={key}
                  className="flex justify-between py-2 border-b border-sf-border text-sm"
                >
                  <span className="text-sf-text-muted">{key}</span>
                  <span className="text-sf-text font-mono text-xs">{value}</span>
                </div>
              ))}
            </div>

            <div>
              <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
                Execution Plan
              </div>
              {executionWaves.map((wave, i) => (
                <div key={i} className="mb-2">
                  <div className="text-xs text-sf-text-muted mb-1">Wave {i}</div>
                  <div className="flex flex-wrap gap-1">
                    {wave.map((nodeId) => (
                      <span
                        key={nodeId}
                        className="inline-flex px-2 py-[2px] rounded-pill text-xs text-sf-text bg-sf-surface border border-sf-border-standard"
                      >
                        {nodeId}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right panel — DAG */}
          <div className="flex-1 bg-sf-surface overflow-hidden relative">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              nodeTypes={nodeTypes}
              fitView
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#242424" gap={20} />
            </ReactFlow>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-sf-border">
          {showInput ? (
            <>
              <textarea
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="Paste raw incident log/input here..."
                className="flex-1 min-h-[88px] max-h-[180px] bg-sf-surface border border-sf-border-standard rounded-btn px-3 py-[6px] text-sm text-sf-text placeholder:text-sf-text-muted font-mono resize-y"
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleRunClick();
                  if (e.key === "Escape") handleCancelRun();
                }}
                autoFocus
              />
              <button
                onClick={handleCancelRun}
                className="px-4 py-[6px] rounded-btn text-sm text-sf-text-muted hover:text-sf-text transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleRunClick}
                disabled={isRunning || !inputValue.trim()}
                className="flex items-center gap-2 px-5 py-[6px] rounded-pill text-sm font-medium text-sf-green bg-transparent border border-[rgba(62,207,142,0.3)] hover:bg-[rgba(62,207,142,0.1)] transition-colors disabled:opacity-50"
              >
                {isRunning ? "Starting…" : "Run →"}
              </button>
            </>
          ) : (
            <>
              <button onClick={onClose} className="px-4 py-[6px] rounded-btn text-sm text-sf-text-muted hover:text-sf-text transition-colors">
                Cancel
              </button>
              <button
                onClick={handleRunClick}
                disabled={isRunning}
                className="flex items-center gap-2 px-5 py-[6px] rounded-pill text-sm font-medium text-sf-green bg-transparent border border-[rgba(62,207,142,0.3)] hover:bg-[rgba(62,207,142,0.1)] transition-colors disabled:opacity-50"
              >
                {isRunning ? "Starting…" : "Run Template →"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

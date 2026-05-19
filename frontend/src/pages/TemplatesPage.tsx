import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useTemplates, useMutations } from "../hooks/useSpecForgeAPI";
import { TemplateDetailModal } from "../components/TemplateDetailModal";
import type { CognitiveTemplate } from "../types";
import * as api from "../api/index";

export function TemplatesPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading, error } = useTemplates();
  const { startExecution, uploadTemplate } = useMutations();
  const templates = Array.isArray(data) ? data : [];
  const [selected, setSelected] = useState<CognitiveTemplate | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [runningTemplateId, setRunningTemplateId] = useState<string | null>(null);

  async function openTemplate(tpl: CognitiveTemplate) {
    const tplRec = tpl as unknown as Record<string, unknown>;
    const id = (tplRec.templateId as string) || (tplRec.template_id as string);
    if (!id) {
      console.error("openTemplate: no template id found");
      return;
    }
    try {
      const res = await api.getTemplate(id);
      const d = res as Record<string, unknown>;
      const full: CognitiveTemplate = {
        template_id: (d.templateId as string) || (d.template_id as string) || id,
        name: (d.name as string) || "Unknown",
        description: (d.description as string) || "",
        version: (d.version as string) || "1.0.0",
        schema_version: (d.schemaVersion as string) || (d.schema_version as string) || "1.0.0",
        nodes: (d.nodes || []) as CognitiveTemplate["nodes"],
        created_at: (d.createdAt as string) || (d.created_at as string) || new Date().toISOString(),
        updated_at: (d.updatedAt as string) || (d.updated_at as string) || new Date().toISOString(),
        tags: (d.tags || []) as string[],
        author: (d.author as string) || "anonymous",
      };
      setSelected(full);
      setDetailOpen(true);
    } catch (e) {
      console.error(`Failed to load template detail for ${id}:`, e);
      alert(`Failed to open template: ${(e as Error).message || "Unknown error"}`);
    }
  }

  function closeDetail() {
    setDetailOpen(false);
    setSelected(null);
  }

  function handleRun(templateId: string, inputData: Record<string, unknown> = {}) {
    if (!templateId) {
      alert("Template ID not available. Please reopen the detail.");
      return;
    }
    setRunningTemplateId(templateId);
    setDetailOpen(false);
    startExecution.mutate(
      { templateId, inputData },
      {
        onSuccess: (data) => {
          console.log("Execution started:", data);
          setRunningTemplateId(null);
          qc.invalidateQueries({ queryKey: ["executions"] });
          navigate("/executions");
        },
        onError: (err) => {
          console.error("Execution error:", err);
          setRunningTemplateId(null);
          alert("Run failed: " + (err as Error).message);
        },
      }
    );
  }

  function handleUploadClick() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,.ct.json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const json = JSON.parse(text);
        uploadTemplate.mutate(json, {
          onSuccess: () => qc.invalidateQueries({ queryKey: ["templates"] }),
          onError: (err) => alert("Upload failed: " + (err as Error).message),
        });
      } catch (err) {
        alert("Invalid JSON: " + (err as Error).message);
      }
    };
    input.click();
  }

  if (isLoading) {
    return <Skeleton />;
  }

  if (error || !templates.length) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <span className="text-5xl text-sf-border-standard">◆</span>
        <p className="text-base text-sf-text">No templates yet</p>
        <p className="text-sm text-sf-text-muted">
          Upload a .ct.json file to get started
        </p>
        <button
          onClick={handleUploadClick}
          className="mt-2 px-5 py-[6px] rounded-pill text-sm font-medium text-sf-text bg-sf-bg-deep border border-sf-text"
        >
          <Upload size={14} className="inline mr-2" />
          Upload Template
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-sf-border shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-lg text-sf-text">Templates</h2>
          <span className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted">
            {templates.length} templates
          </span>
        </div>
        <button
          onClick={handleUploadClick}
          className="flex items-center gap-2 px-5 py-[6px] rounded-pill text-sm font-medium text-sf-text bg-sf-bg-deep border border-sf-text"
        >
          <Upload size={14} />
          Upload Template
        </button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-sf-border">
              <th className="text-left font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-[10px]">
                Name
              </th>
              <th className="text-left font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-[10px]">
                Version
              </th>
              <th className="text-left font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-[10px]">
                Tags
              </th>
              <th className="text-left font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-[10px]">
                Last Run
              </th>
              <th className="w-24" />
            </tr>
          </thead>
          <tbody>
            {templates.map((tpl, idx) => (
              <tr
                key={((tpl as unknown as Record<string, unknown>).templateId as string) || ((tpl as unknown as Record<string, unknown>).template_id as string) || `tpl-${idx}`}
                onClick={() => openTemplate(tpl)}
                className="border-b border-sf-border cursor-pointer transition-colors duration-100 hover:bg-[rgba(255,255,255,0.03)]"
              >
                <td className="px-4 py-3">
                  <span className="text-sm font-medium text-sf-text">{tpl.name}</span>
                  <span className="block text-xs text-sf-text-muted mt-0.5">{tpl.description}</span>
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex px-2 py-[2px] rounded-pill text-xs text-sf-text-muted bg-sf-surface border border-sf-border-standard">
                    v{tpl.version}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {(tpl.tags || []).map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex px-2 py-[2px] rounded-pill text-xs text-sf-text-muted border border-sf-border-standard"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-sf-text-muted">—</td>
                <td className="px-4 py-3">
                  <span className="text-sm text-sf-text-muted opacity-0 group-hover:opacity-100 transition-opacity">
                    View →
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detailOpen && selected && (
        <TemplateDetailModal
          template={selected}
          onClose={closeDetail}
          onRun={handleRun}
          isRunning={runningTemplateId === selected.template_id}
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
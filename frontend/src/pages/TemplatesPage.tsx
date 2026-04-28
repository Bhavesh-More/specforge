import { useState } from "react";
import { Upload } from "lucide-react";
import { useTemplates, useMutations } from "../hooks/useSpecForgeAPI";
import { TemplateDetailModal } from "../components/TemplateDetailModal";
import type { CognitiveTemplate } from "../types";
import { useQueryClient } from "@tanstack/react-query";
import axios from "axios";

export function TemplatesPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useTemplates();
  const { startExecution, uploadTemplate } = useMutations();
  const templates = Array.isArray(data) ? data : [];
  const [selected, setSelected] = useState<CognitiveTemplate | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  async function openTemplate(tpl: CognitiveTemplate) {
    try {
      const res = await axios.get(`/api/v1/templates/${tpl.template_id}`);
      const data = res.data as Record<string, unknown>;
      const full: CognitiveTemplate = {
        template_id: data.templateId as string,
        name: data.name as string,
        description: data.description as string,
        version: data.version as string,
        schema_version: data.schemaVersion as string,
        nodes: (data.nodes || []) as CognitiveTemplate["nodes"],
        created_at: data.createdAt as string,
        updated_at: data.updatedAt as string,
        tags: (data.tags || []) as string[],
        author: (data.author || "anonymous") as string,
      };
      setSelected(full);
      setDetailOpen(true);
    } catch {
      // fallback: open with summary data if detail fetch fails
      setSelected(tpl);
      setDetailOpen(true);
    }
  }

  function closeDetail() {
    setDetailOpen(false);
    setSelected(null);
  }

  function handleRun(templateId: string, inputData: Record<string, unknown>) {
    startExecution.mutate(
      { templateId, inputData },
      {
        onSuccess: () => closeDetail(),
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
                Nodes
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
            {templates.map((tpl) => (
              <tr
                key={tpl.template_id}
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
                <td className="px-4 py-3 text-sm text-sf-text-muted">
                  {tpl.nodes.length} nodes
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {tpl.tags.map((tag) => (
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
          isRunning={startExecution.isPending}
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

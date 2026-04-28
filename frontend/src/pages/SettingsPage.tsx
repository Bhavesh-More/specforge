import { useState, useEffect } from "react";
import { CheckCircle } from "lucide-react";
import { useOllamaHealth, useOllamaModels, useOllamaConfig, useMutations } from "../hooks/useSpecForgeAPI";

export function SettingsPage() {
  const { data: health } = useOllamaHealth();
  const { data: models, isLoading: modelsLoading } = useOllamaModels();
  const { data: config } = useOllamaConfig();
  const { updateOllamaConfig } = useMutations();

  const [selectedMain, setSelectedMain] = useState(config?.mainModel ?? "");
  const [selectedTeacher, setSelectedTeacher] = useState(config?.teacherModel ?? "");
  const [showSaved, setShowSaved] = useState(false);

  useEffect(() => {
    if (config?.mainModel) setSelectedMain(config.mainModel);
    if (config?.teacherModel) setSelectedTeacher(config.teacherModel);
  }, [config]);

  const handleSave = () => {
    updateOllamaConfig.mutate({ mainModel: selectedMain, teacherModel: selectedTeacher });
  };

  useEffect(() => {
    if (updateOllamaConfig.isSuccess) {
      setShowSaved(true);
      const timer = setTimeout(() => setShowSaved(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [updateOllamaConfig.isSuccess]);

  return (
    <div className="h-full flex flex-col px-6 py-4">
      <div className="mb-6">
        <h2 className="text-lg text-sf-text mb-1">Settings</h2>
        <p className="text-sm text-sf-text-muted">Configure Ollama models for execution and healing.</p>
      </div>

      {/* Ollama Connection */}
      <div className="mb-8 p-4 bg-sf-surface border border-sf-border-standard rounded-card">
        <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
          Ollama Connection
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${
              health?.status === "healthy"
                ? "bg-sf-green"
                : health?.status === "unhealthy"
                  ? "bg-sf-red"
                  : "bg-sf-amber animate-pulse"
            }`}
          />
          <span className="text-sm text-sf-text font-mono">
            {health?.status === "healthy"
              ? `Connected — ${health.url}`
              : health?.status === "unhealthy"
                ? "Offline"
                : "Checking…"}
          </span>
        </div>
      </div>

      {/* Model Selection */}
      <div className="mb-8 p-4 bg-sf-surface border border-sf-border-standard rounded-card">
        <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-4">
          Model Selection
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-sf-text mb-2">
              Main Model <span className="text-sf-text-muted font-mono text-xs">(standard nodes)</span>
            </label>
            <select
              value={selectedMain}
              onChange={(e) => setSelectedMain(e.target.value)}
              className="w-full max-w-md bg-sf-bg border border-sf-border-standard rounded-btn px-3 py-2 text-sm text-sf-text focus:outline-none focus:border-sf-green"
            >
              <option value="">Select model…</option>
              {modelsLoading && <option disabled>Loading models…</option>}
              {models?.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm text-sf-text mb-2">
              Teacher Model <span className="text-sf-text-muted font-mono text-xs">(healing/repair nodes)</span>
            </label>
            <select
              value={selectedTeacher}
              onChange={(e) => setSelectedTeacher(e.target.value)}
              className="w-full max-w-md bg-sf-bg border border-sf-border-standard rounded-btn px-3 py-2 text-sm text-sf-text focus:outline-none focus:border-sf-green"
            >
              <option value="">Select model…</option>
              {modelsLoading && <option disabled>Loading models…</option>}
              {models?.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-4 relative">
          <button
            onClick={handleSave}
            disabled={updateOllamaConfig.isPending || !selectedMain || !selectedTeacher}
            className="px-4 py-2 bg-sf-green text-sf-bg text-sm font-medium rounded-btn hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {updateOllamaConfig.isPending ? "Saving…" : "Save Configuration"}
          </button>
          {showSaved && (
            <span className="absolute -top-8 left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-3 py-1 bg-sf-green text-sf-bg text-xs font-medium rounded-full shadow-lg whitespace-nowrap">
              <CheckCircle size={12} />
              Models saved
            </span>
          )}
        </div>
      </div>

      {/* Available Models */}
      <div className="p-4 bg-sf-surface border border-sf-border-standard rounded-card">
        <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-3">
          Available Models ({models?.length ?? 0})
        </div>
        <div className="space-y-2">
          {models?.map((m) => (
            <div
              key={m.name}
              className="flex items-center justify-between px-3 py-2 bg-sf-bg border border-sf-border rounded-btn"
            >
              <span className="text-sm text-sf-text font-mono">{m.name}</span>
              <span className="text-xs text-sf-text-muted font-mono">
                {m.size ? `${(m.size / 1e9).toFixed(1)} GB` : "—"}
              </span>
            </div>
          ))}
          {!modelsLoading && (!models || models.length === 0) && (
            <div className="text-sm text-sf-text-muted">No local models found.</div>
          )}
        </div>
      </div>
    </div>
  );
}
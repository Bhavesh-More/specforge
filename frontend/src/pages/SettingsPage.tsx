import { useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { useOllamaModels, useSelectedModels, useMutateSelectedModels, useOllamaHealth } from "../hooks/useSpecForgeAPI";
import { useAppStore } from "../stores/appStore";

export function SettingsPage() {
  const { setOllamaStatus } = useAppStore();

  const { data: modelsData, isLoading: modelsLoading } = useOllamaModels();
  const { data: selectedData, isLoading: selectedLoading } = useSelectedModels();
  const { data: healthData, refetch: refetchHealth } = useOllamaHealth();
  const { mutate: saveModels, isPending: saving } = useMutateSelectedModels();

  const availableModels = modelsData?.models ?? [];
  const selectedDefault = selectedData?.default_model ?? "llama3.2";
  const selectedTeacher = selectedData?.teacher_model ?? "llama3.1:8b";

  // Sync health status to store
  useEffect(() => {
    if (healthData) {
      setOllamaStatus(healthData.status as "healthy" | "unhealthy");
    }
  }, [healthData, setOllamaStatus]);

  function handleSave(defaultModel: string, teacherModel: string) {
    saveModels({ default_model: defaultModel, teacher_model: teacherModel });
  }

  if (modelsLoading || selectedLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-sf-text-muted font-mono text-sm">Loading settings…</span>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-sf-border shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-lg text-sf-text">Settings</h2>
          <span className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted">
            Ollama Configuration
          </span>
        </div>
        <button
          onClick={() => refetchHealth()}
          className="flex items-center gap-2 px-4 py-[6px] rounded-btn text-sm text-sf-text-muted hover:text-sf-text transition-colors"
        >
          <RefreshCw size={14} />
          Refresh Health
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-8">
        {/* Ollama Health */}
        <section>
          <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-4">
            Ollama Status
          </div>
          <div className="bg-sf-surface border border-sf-border-standard rounded-card p-5 flex items-center gap-4">
            <div
              className={`w-3 h-3 rounded-full ${
                healthData?.status === "healthy"
                  ? "bg-sf-green"
                  : healthData?.status === "unhealthy"
                    ? "bg-sf-red"
                    : "bg-sf-amber animate-pulse"
              }`}
            />
            <div>
              <div className="text-sm font-medium text-sf-text">
                {healthData?.status === "healthy"
                  ? "Ollama is running"
                  : healthData?.status === "unhealthy"
                    ? "Ollama is offline"
                    : "Checking Ollama status…"}
              </div>
              {healthData?.reason && (
                <div className="text-xs text-sf-text-muted mt-1">{healthData.reason}</div>
              )}
              {availableModels.length > 0 && (
                <div className="text-xs text-sf-text-muted mt-1">
                  {availableModels.length} model(s) available
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Default Model */}
        <section>
          <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-4">
            Default Model
          </div>
          <div className="bg-sf-surface border border-sf-border-standard rounded-card p-5">
            <p className="text-xs text-sf-text-muted mb-4">
              Used for standard node execution across all templates.
            </p>
            <div className="flex items-center gap-3">
              <select
                id="defaultModel"
                defaultValue={selectedDefault}
                className="flex-1 bg-sf-bg border border-sf-border-standard rounded-btn px-3 py-2 text-sm text-sf-text font-mono max-w-[320px]"
              >
                {availableModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>

        {/* Teacher Model */}
        <section>
          <div className="font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted mb-4">
            Teacher Model
          </div>
          <div className="bg-sf-surface border border-sf-border-standard rounded-card p-5">
            <p className="text-xs text-sf-text-muted mb-4">
              Used for self-healing and deep reasoning tasks.
            </p>
            <div className="flex items-center gap-3">
              <select
                id="teacherModel"
                defaultValue={selectedTeacher}
                className="flex-1 bg-sf-bg border border-sf-border-standard rounded-btn px-3 py-2 text-sm text-sf-text font-mono max-w-[320px]"
              >
                {availableModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>

        {/* Save Button */}
        <div className="flex justify-end">
          <button
            onClick={() => {
              const defaultEl = document.getElementById("defaultModel") as HTMLSelectElement;
              const teacherEl = document.getElementById("teacherModel") as HTMLSelectElement;
              handleSave(defaultEl.value, teacherEl.value);
            }}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-[6px] rounded-pill text-sm font-medium text-sf-green bg-transparent border border-[rgba(62,207,142,0.3)] hover:bg-[rgba(62,207,142,0.1)] transition-colors disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Model Selection"}
          </button>
        </div>
      </div>
    </div>
  );
}
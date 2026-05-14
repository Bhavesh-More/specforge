import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../api/index";
import type {
  CognitiveTemplate,
  KnowledgeFile,
  HealingEvent,
} from "../types";

// ─── Templates ───────────────────────────────────────────────────────────────

export function useTemplates() {
  return useQuery<CognitiveTemplate[]>({
    queryKey: ["templates"],
    queryFn: api.listTemplates,
    refetchInterval: false,
  });
}

export function useTemplate(id: string) {
  return useQuery<CognitiveTemplate>({
    queryKey: ["templates", id],
    queryFn: () => api.getTemplate(id).then((r) => r as unknown as CognitiveTemplate),
    enabled: !!id,
  });
}

// ─── Executions ───────────────────────────────────────────────────────────────

export function useExecutions() {
  return useQuery<Array<Record<string, unknown>>>({
    queryKey: ["executions"],
    queryFn: api.listExecutions,
    refetchInterval: 5000,
  });
}

export function useExecution(id: string | null) {
  return useQuery<Record<string, unknown>>({
    queryKey: ["executions", id],
    queryFn: () => api.getExecution(id!),
    enabled: !!id,
    refetchInterval: (q) =>
      q.state.data?.status === "RUNNING" ? 2000 : false,
  });
}

// ─── Knowledge ───────────────────────────────────────────────────────────────

export function useKnowledgeFiles() {
  return useQuery<KnowledgeFile[]>({
    queryKey: ["knowledge", "files"],
    queryFn: api.listKnowledgeFiles,
  });
}

export function useKnowledgeFile(name: string | null) {
  return useQuery<KnowledgeFile>({
    queryKey: ["knowledge", "files", name],
    queryFn: () => api.getKnowledgeFile(name!) as Promise<KnowledgeFile>,
    enabled: !!name,
  });
}

// ─── Healing ───────────────────────────────────────────────────────────────

export function useHealingEvents() {
  return useQuery<HealingEvent[]>({
    queryKey: ["healing", "events"],
    queryFn: api.listHealingEvents,
    refetchInterval: 10000,
  });
}

// ─── Mutations ───────────────────────────────────────────────────────────────

export function useMutations() {
  const qc = useQueryClient();

  const uploadTemplate = useMutation({
    mutationFn: (template: Record<string, unknown>) => api.uploadTemplate(template),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["templates"] }),
  });

  const createKnowledgeFile = useMutation({
    mutationFn: (file: { name: string; content: string }) =>
      api.createKnowledgeFile(file.name, file.content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }),
  });

  const updateKnowledgeFile = useMutation({
    mutationFn: (file: { name: string; content: string }) =>
      api.updateKnowledgeFile(file.name, file.content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }),
  });

  const approveHealingEvent = useMutation({
    mutationFn: (id: string) => api.approveHealingEvent(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["healing"] }),
  });

  const rejectHealingEvent = useMutation({
    mutationFn: (id: string) => api.rejectHealingEvent(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["healing"] }),
  });

  const startExecution = useMutation({
    mutationFn: (payload: { templateId: string; inputData?: Record<string, unknown> }) =>
      api.startExecution(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }),
  });

  const deleteExecution = useMutation({
    mutationFn: (id: string) => api.deleteExecution(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }),
  });

  return {
    uploadTemplate,
    createKnowledgeFile,
    updateKnowledgeFile,
    approveHealingEvent,
    rejectHealingEvent,
    startExecution,
    deleteExecution,
  };
}

// ─── Models ─────────────────────────────────────────────────────────────────

export function useOllamaModels() {
  return useQuery({
    queryKey: ["ollama", "models"],
    queryFn: api.listOllamaModels,
    refetchInterval: 30000,
  });
}

export function useSelectedModels() {
  return useQuery({
    queryKey: ["ollama", "selected"],
    queryFn: api.getSelectedModels,
  });
}

export function useMutateSelectedModels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { default_model?: string; teacher_model?: string }) =>
      api.updateSelectedModels(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ollama", "selected"] }),
  });
}

export function useOllamaHealth() {
  return useQuery({
    queryKey: ["ollama", "health"],
    queryFn: api.checkOllamaHealth,
    refetchInterval: 15000,
  });
}
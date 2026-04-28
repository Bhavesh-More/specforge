import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import type {
  CognitiveTemplate,
  ExecutionRun,
  KnowledgeFile,
  HealingEvent,
} from "../types";

const API = axios.create({ baseURL: "/api/v1" });

// ─── Ollama ───────────────────────────────────────────────────────────────────

export interface OllamaModel {
  name: string;
  size: number | null;
  modified_at: string | null;
}

export interface OllamaHealth {
  status: string;
  url: string;
  model: string | null;
}

export function useOllamaHealth() {
  return useQuery<OllamaHealth>({
    queryKey: ["ollama", "health"],
    queryFn: () => API.get("/ollama/health").then((r) => r.data),
    refetchInterval: 15000,
  });
}

export function useOllamaModels() {
  return useQuery<OllamaModel[]>({
    queryKey: ["ollama", "models"],
    queryFn: async () => {
      const res = await API.get("/ollama/models");
      const data = res.data as Record<string, unknown>;
      return ((data.models || []) as Record<string, unknown>[]).map((m) => ({
        name: m.name as string,
        size: m.size as number | null,
        modified_at: m.modified_at as string | null,
      }));
    },
  });
}

// ─── Templates ───────────────────────────────────────────────────────────────

export function useTemplates() {
  return useQuery<CognitiveTemplate[]>({
    queryKey: ["templates"],
    queryFn: async () => {
      const res = await API.get("/templates");
      const data = res.data;
      const rawItems = (data?.items || data?.templates || []) as Record<string, unknown>[];
      return rawItems.map((item) => {
        const camel = item as Record<string, unknown>;
        return {
          template_id: camel.templateId as string,
          name: camel.name as string,
          description: camel.description as string,
          version: camel.version as string,
          schema_version: camel.schemaVersion as string,
          nodes: (camel.nodes || []) as CognitiveTemplate["nodes"],
          created_at: camel.createdAt as string,
          updated_at: camel.updatedAt as string,
          tags: (camel.tags || []) as string[],
          author: (camel.author || "anonymous") as string,
        };
      }) as CognitiveTemplate[];
    },
    refetchInterval: false,
  });
}

export function useTemplate(id: string) {
  return useQuery<CognitiveTemplate>({
    queryKey: ["templates", id],
    queryFn: async () => {
      const res = await API.get(`/templates/${id}`);
      const data = res.data as Record<string, unknown>;
      return {
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
      } as CognitiveTemplate;
    },
    enabled: !!id,
  });
}

// ─── Executions ───────────────────────────────────────────────────────────────

export function useExecutions() {
  return useQuery<ExecutionRun[]>({
    queryKey: ["executions"],
    queryFn: async () => {
      const res = await API.get("/executions");
      const data = res.data;
      const rawItems = (data?.items || data?.executions || []) as Record<string, unknown>[];
      return rawItems.map((item) => normalizeExecution(item) as unknown as ExecutionRun);
    },
    refetchInterval: 5000,
  });
}

export function useExecution(id: string | null) {
  return useQuery<ExecutionRun>({
    queryKey: ["executions", id],
    queryFn: async () => {
      const res = await API.get(`/executions/${id}`);
      return normalizeExecution(res.data) as unknown as ExecutionRun;
    },
    enabled: !!id,
    refetchInterval: (q) =>
      (q.state.data as ExecutionRun | undefined)?.status === "RUNNING" ? 2000 : false,
  });
}

function normalizeExecution(data: unknown): Record<string, unknown> {
  const camel = data as Record<string, unknown>;
  return {
    id: camel.runId as string,
    run_id: camel.runId as string,
    template_id: camel.templateId as string,
    template_name: camel.templateName as string,
    status: camel.status as ExecutionRun["status"],
    input_data: (camel.inputData || {}) as Record<string, unknown>,
    final_output: camel.finalOutput as ExecutionRun["final_output"],
    error_message: camel.errorMessage as string | null,
    started_at: camel.startedAt as string,
    completed_at: camel.completedAt as string | null,
    total_execution_time_ms: camel.totalExecutionTimeMs as number | null,
    state_file_path: camel.stateFilePath as string | null,
    node_results: (camel.nodeResults || []) as ExecutionRun["node_results"],
  };
}

// ─── Knowledge ───────────────────────────────────────────────────────────────

export function useKnowledgeFiles() {
  return useQuery<KnowledgeFile[]>({
    queryKey: ["knowledge", "files"],
    queryFn: async () => {
      const res = await API.get("/knowledge/files");
      const data = res.data;
      const rawItems = (data?.items || data?.files || []) as Record<string, unknown>[];
      return rawItems.map((item) => ({
        name: item.name as string,
        content: item.content as string,
        linked_files: (item.linkedFiles || []) as string[],
      })) as KnowledgeFile[];
    },
  });
}

export function useKnowledgeFile(name: string | null) {
  return useQuery<KnowledgeFile>({
    queryKey: ["knowledge", "files", name],
    queryFn: async () => {
      const res = await API.get(`/knowledge/files/${name}`);
      const data = res.data as Record<string, unknown>;
      return {
        name: data.name as string,
        content: data.content as string,
        linked_files: (data.linkedFiles || []) as string[],
      } as KnowledgeFile;
    },
    enabled: !!name,
  });
}

export function useMutations() {
  const qc = useQueryClient();

  const createKnowledgeFile = useMutation({
    mutationFn: (file: { name: string; content: string }) =>
      API.post("/knowledge/files", file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }),
  });

  const updateKnowledgeFile = useMutation({
    mutationFn: (file: { name: string; content: string }) =>
      API.put(`/knowledge/files/${file.name}`, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }),
  });

  const approveHealingEvent = useMutation({
    mutationFn: (id: string) => API.post(`/healing/events/${id}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["healing"] }),
  });

  const rejectHealingEvent = useMutation({
    mutationFn: (id: string) => API.post(`/healing/events/${id}/reject`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["healing"] }),
  });

  const startExecution = useMutation({
    mutationFn: ({ templateId, inputData }: { templateId: string; inputData: Record<string, unknown> }) =>
      API.post(`/executions`, { templateId, inputData }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }),
  });

  const uploadTemplate = useMutation({
    mutationFn: (template: Record<string, unknown>) =>
      API.post("/templates", template),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["templates"] }),
  });

  const updateOllamaConfig = useMutation({
    mutationFn: (config: { mainModel: string; teacherModel: string }) =>
      API.put("/ollama/config", config),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ollama"] }),
  });

  return {
    createKnowledgeFile,
    updateKnowledgeFile,
    approveHealingEvent,
    rejectHealingEvent,
    startExecution,
    uploadTemplate,
    updateOllamaConfig,
  };
}

// ─── Ollama Config ─────────────────────────────────────────────────────────────

export function useOllamaConfig() {
  return useQuery<{ mainModel: string; teacherModel: string }>({
    queryKey: ["ollama", "config"],
    queryFn: () => API.get("/ollama/config").then((r) => r.data),
  });
}

// ─── Healing ───────────────────────────────────────────────────────────────

export function useHealingEvents() {
  return useQuery<HealingEvent[]>({
    queryKey: ["healing", "events"],
    queryFn: async () => {
      const res = await API.get("/healing/events");
      const data = res.data;
      const rawItems = (data?.items || data?.events || []) as Record<string, unknown>[];
      return rawItems.map((item) => ({
        id: item.eventId as string,
        triggered_at: item.triggeredAt as string,
        trigger_type: item.trigger as string,
        node_id: item.nodeId as string,
        template_id: item.templateId as string,
        failure_count: item.failureCount as number,
        failure_examples: (item.failureExamples || []) as string[],
        teacher_model: item.teacherModelUsed as string,
        patches: (item.patches || []) as string[],
        applied: item.applied as boolean,
        applied_at: item.appliedAt as string | null,
        approved_by: item.approvedBy as string | null,
      })) as HealingEvent[];
    },
    refetchInterval: 10000,
  });
}

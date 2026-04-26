import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import type {
  CognitiveTemplate,
  ExecutionRun,
  KnowledgeFile,
  HealingEvent,
} from "../types";

const API = axios.create({ baseURL: "/api/v1" });

// ─── Templates ───────────────────────────────────────────────────────────────

export function useTemplates() {
  return useQuery<CognitiveTemplate[]>({
    queryKey: ["templates"],
    queryFn: async () => {
      const res = await API.get("/templates");
      // API may return { templates: [...] } or direct array
      const data = res.data;
      if (Array.isArray(data)) return data;
      if (data?.templates && Array.isArray(data.templates)) return data.templates;
      return [];
    },
    refetchInterval: false,
  });
}

export function useTemplate(id: string) {
  return useQuery<CognitiveTemplate>({
    queryKey: ["templates", id],
    queryFn: () => API.get(`/templates/${id}`).then((r) => r.data),
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
      if (Array.isArray(data)) return data;
      if (data?.executions && Array.isArray(data.executions)) return data.executions;
      return [];
    },
    refetchInterval: 5000,
  });
}

export function useExecution(id: string | null) {
  return useQuery<ExecutionRun>({
    queryKey: ["executions", id],
    queryFn: () => API.get(`/executions/${id}`).then((r) => r.data),
    enabled: !!id,
    refetchInterval: (q) =>
      q.state.data?.status === "RUNNING" ? 2000 : false,
  });
}

// ─── Knowledge ───────────────────────────────────────────────────────────────

export function useKnowledgeFiles() {
  return useQuery<KnowledgeFile[]>({
    queryKey: ["knowledge", "files"],
    queryFn: async () => {
      const res = await API.get("/knowledge/files");
      const data = res.data;
      if (Array.isArray(data)) return data;
      if (data?.files && Array.isArray(data.files)) return data.files;
      return [];
    },
  });
}

export function useKnowledgeFile(name: string | null) {
  return useQuery<KnowledgeFile>({
    queryKey: ["knowledge", "files", name],
    queryFn: () => API.get(`/knowledge/files/${name}`).then((r) => r.data),
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
    mutationFn: (templateId: string) =>
      API.post(`/executions`, { template_id: templateId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }),
  });

  return {
    createKnowledgeFile,
    updateKnowledgeFile,
    approveHealingEvent,
    rejectHealingEvent,
    startExecution,
  };
}

// ─── Healing ───────────────────────────────────────────────────────────────

export function useHealingEvents() {
  return useQuery<HealingEvent[]>({
    queryKey: ["healing", "events"],
    queryFn: async () => {
      const res = await API.get("/healing/events");
      const data = res.data;
      if (Array.isArray(data)) return data;
      if (data?.events && Array.isArray(data.events)) return data.events;
      return [];
    },
    refetchInterval: 10000,
  });
}

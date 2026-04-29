import axios from "axios";
import type {
  CognitiveTemplate,
  ExecutionRun,
  KnowledgeFile,
  HealingEvent,
} from "../types";

const api = axios.create({ baseURL: "/api/v1" });

// ─── Models ──────────────────────────────────────────────────────────────────

export async function listOllamaModels() {
  const res = await api.get("/models");
  return res.data as { models: string[] };
}

export async function getSelectedModels() {
  const res = await api.get("/models/selected");
  return res.data as { default_model: string; teacher_model: string };
}

export async function updateSelectedModels(data: {
  default_model?: string;
  teacher_model?: string;
}) {
  const res = await api.put("/models/selected", data);
  return res.data as { default_model: string; teacher_model: string };
}

export async function checkOllamaHealth() {
  const res = await api.get("/ollama/health");
  return res.data as { status: string; models: string[]; reason?: string };
}

// ─── Templates ───────────────────────────────────────────────────────────────

export async function listTemplates() {
  const res = await api.get("/templates");
  const data = res.data;
  if (Array.isArray(data)) return data;
  if (data?.items && Array.isArray(data.items)) return data.items;
  return [];
}

export async function getTemplate(id: string) {
  const res = await api.get(`/templates/${id}`);
  return res.data as {
    templateId: string;
    name: string;
    description: string;
    version: string;
    schemaVersion: string;
    nodes: CognitiveTemplate["nodes"];
    createdAt: string;
    updatedAt: string;
    tags: string[];
    author: string;
  };
}

export async function uploadTemplate(template: Record<string, unknown>) {
  const res = await api.post("/templates", template);
  return res.data;
}

// ─── Executions ─────────────────────────────────────────────────────────────

export async function listExecutions() {
  const res = await api.get("/executions");
  const data = res.data;
  let items: unknown[] = [];
  if (Array.isArray(data)) items = data;
  else if (data?.executions && Array.isArray(data.executions)) items = data.executions;
  else if (data?.items && Array.isArray(data.items)) items = data.items;
  // Backend returns runId, templateId, etc. — normalize to ExecutionRun shape
  return items.map((r: Record<string, unknown>) => ({
    id: r.runId as string,
    template_id: r.templateId as string,
    template_name: r.templateName as string,
    status: r.status as string,
    input_data: (r.inputData || {}) as Record<string, unknown>,
    final_output: (r.finalOutput || null) as Record<string, unknown> | null,
    error_message: (r.errorMessage || null) as string | null,
    started_at: r.startedAt as string,
    completed_at: (r.completedAt || null) as string | null,
    total_execution_time_ms: (r.totalExecutionTimeMs ?? null) as number | null,
    state_file_path: (r.stateFilePath || null) as string | null,
    node_results: (r.nodeResults || []) as unknown[],
  }));
}

export async function getExecution(id: string): Promise<Record<string, unknown>> {
  const res = await api.get(`/executions/${id}`);
  const r = res.data as Record<string, unknown>;
  // Normalize camelCase fields to snake_case for frontend types
  const nodeResultsRaw = r.nodeResults as Record<string, unknown> | undefined;
  const nodeResultsArray = nodeResultsRaw
    ? Object.values(nodeResultsRaw)
    : [];
  return {
    id: r.runId as string,
    template_id: r.templateId as string,
    template_name: r.templateName as string,
    status: r.status as string,
    input_data: (r.inputData || {}) as Record<string, unknown>,
    final_output: (r.finalOutput || null) as Record<string, unknown> | null,
    error_message: (r.errorMessage || null) as string | null,
    started_at: r.startedAt as string,
    completed_at: (r.completedAt || null) as string | null,
    total_execution_time_ms: (r.totalExecutionTimeMs ?? null) as number | null,
    state_file_path: (r.stateFilePath || null) as string | null,
    node_results: nodeResultsArray,
  };
}

export async function startExecution(payload: { templateId: string; inputData?: Record<string, unknown> }) {
  const res = await api.post("/executions", { template_id: payload.templateId, input_data: payload.inputData || {} });
  return res.data;
}

export async function deleteExecution(id: string) {
  await api.delete(`/executions/${id}`);
}

// ─── Knowledge ───────────────────────────────────────────────────────────────

export async function listKnowledgeFiles() {
  const res = await api.get("/knowledge/files");
  const data = res.data;
  if (Array.isArray(data)) return data;
  if (data?.files && Array.isArray(data.files)) return data.files;
  return [];
}

export async function getKnowledgeFile(name: string) {
  const res = await api.get(`/knowledge/files/${name}`);
  return res.data;
}

export async function createKnowledgeFile(name: string, content: string) {
  const res = await api.post("/knowledge/files", { name, content });
  return res.data;
}

export async function updateKnowledgeFile(name: string, content: string) {
  const res = await api.put(`/knowledge/files/${name}`, { name, content });
  return res.data;
}

// ─── Healing ────────────────────────────────────────────────────────────────

export async function listHealingEvents() {
  const res = await api.get("/healing/events");
  const data = res.data;
  if (Array.isArray(data)) return data;
  if (data?.events && Array.isArray(data.events)) return data.events;
  return [];
}

export async function approveHealingEvent(id: string) {
  const res = await api.post(`/healing/events/${id}/approve`);
  return res.data;
}

export async function rejectHealingEvent(id: string) {
  const res = await api.post(`/healing/events/${id}/reject`);
  return res.data;
}
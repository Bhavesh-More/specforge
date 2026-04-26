// ─── Node Types ───────────────────────────────────────────────────────────────

export type NodeType = "standard" | "symbolic" | "adversarial" | "lookahead" | "parallel";
export type ExecutionTier = "FAST" | "REPAIR" | "DEEP";
export type ExecutionStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type NodeStatus = "PENDING" | "RUNNING" | "PASSED_TIER1" | "PASSED_TIER2" | "PASSED_TIER3" | "FAILED";
export type HealingStatus = "APPLIED" | "PENDING_APPROVAL" | "REJECTED";
export type OllamaStatus = "healthy" | "unhealthy" | "checking";

// ─── Focus Prompt ─────────────────────────────────────────────────────────────

export interface FocusPrompt {
  system_prompt: string;
  user_template: string;
  output_schema: Record<string, unknown>;
  required_variables: string[];
  max_tokens: number;
  temperature: number;
}

// ─── DAG Node ───────────────────────────────────────────────────────────────────

export interface DAGNode {
  node_id: string;
  name: string;
  description: string;
  node_type: NodeType;
  focus_prompt: FocusPrompt;
  depends_on: string[];
  can_run_parallel: boolean;
  max_retries: number;
  symbolic_tool: string | null;
  output_key: string;
}

// ─── Template ────────────────────────────────────────────────────────────────

export interface CognitiveTemplate {
  template_id: string;
  name: string;
  description: string;
  version: string;
  schema_version: string;
  nodes: DAGNode[];
  created_at: string;
  updated_at: string;
  tags: string[];
  author: string;
}

// ─── Execution ────────────────────────────────────────────────────────────────

export interface NodeResult {
  id: string;
  run_id: string;
  node_id: string;
  status: NodeStatus;
  tier_used: ExecutionTier;
  attempt_count: number;
  execution_time_ms: number;
  validation_errors: string[];
  error_message: string | null;
  created_at: string;
}

export interface ExecutionRun {
  id: string;
  template_id: string;
  template_name: string;
  status: ExecutionStatus;
  input_data: Record<string, unknown>;
  final_output: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  total_execution_time_ms: number | null;
  state_file_path: string | null;
  node_results: NodeResult[];
}

// ─── Knowledge ──────────────────────────────────────────────────────────────

export interface KnowledgeFile {
  name: string;
  content: string;
  linked_files: string[];
}

// ─── Healing ────────────────────────────────────────────────────────────────

export interface HealingEvent {
  id: string;
  triggered_at: string;
  trigger_type: string;
  node_id: string;
  template_id: string;
  failure_count: number;
  failure_examples: string[];
  teacher_model: string;
  patches: string[];
  applied: boolean;
  applied_at: string | null;
  approved_by: string | null;
}

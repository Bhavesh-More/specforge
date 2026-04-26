import { create } from "zustand";
import type { OllamaStatus } from "../types";

interface AppState {
  ollamaStatus: OllamaStatus;
  activeRuns: number;
  selectedTemplateId: string | null;
  selectedRunId: string | null;
  sidebarWidth: 220;
  setOllamaStatus: (status: OllamaStatus) => void;
  setActiveRuns: (count: number) => void;
  setSelectedTemplateId: (id: string | null) => void;
  setSelectedRunId: (id: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  ollamaStatus: "checking",
  activeRuns: 0,
  selectedTemplateId: null,
  selectedRunId: null,
  sidebarWidth: 220,
  setOllamaStatus: (status) => set({ ollamaStatus: status }),
  setActiveRuns: (count) => set({ activeRuns: count }),
  setSelectedTemplateId: (id) => set({ selectedTemplateId: id }),
  setSelectedRunId: (id) => set({ selectedRunId: id }),
}));

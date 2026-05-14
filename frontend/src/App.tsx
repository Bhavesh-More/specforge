import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/Layout";
import { TemplatesPage } from "./pages/TemplatesPage";
import { ExecutionsPage } from "./pages/ExecutionsPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { HealingPage } from "./pages/HealingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { DashboardPage } from "./pages/DashboardPage";
import "./index.css";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/templates" element={<TemplatesPage />} />
            <Route path="/executions" element={<ExecutionsPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/healing" element={<HealingPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/" element={<DashboardPage />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

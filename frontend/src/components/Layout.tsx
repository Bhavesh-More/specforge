import { Link, useLocation } from "react-router-dom";
import {
  LayoutTemplate,
  PlayCircle,
  BookOpen,
  HeartCrack,
  Settings,
} from "lucide-react";
import { useAppStore } from "../stores/appStore";

const NAV_ITEMS = [
  { to: "/templates", icon: LayoutTemplate, label: "Templates" },
  { to: "/executions", icon: PlayCircle, label: "Executions" },
  { to: "/knowledge", icon: BookOpen, label: "Knowledge" },
  { to: "/healing", icon: HeartCrack, label: "Healing" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { ollamaStatus, activeRuns } = useAppStore();

  const statusColor =
    ollamaStatus === "healthy"
      ? "bg-sf-green"
      : ollamaStatus === "unhealthy"
        ? "bg-sf-red"
        : "bg-sf-amber animate-pulse";

  return (
    <div className="flex h-screen overflow-hidden bg-sf-bg font-sans">
      {/* Sidebar */}
      <aside className="w-[220px] shrink-0 flex flex-col h-full bg-sf-bg-deep border-r border-sf-border">
        {/* Wordmark */}
        <div className="px-4 py-5">
          <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[1.2px] text-sf-text">
            <span className="text-sf-green">◆</span>
            <span>SPECFORGE</span>
          </div>
        </div>
        <div className="border-b border-sf-border" />

        {/* Nav */}
        <nav className="flex-1 pt-2">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => {
            const active = location.pathname.startsWith(to);
            return (
              <Link
                key={to}
                to={to}
                className={`
                  flex items-center gap-3 px-4 py-[10px] text-sm font-medium transition-colors duration-150
                  ${active
                    ? "text-sf-text border-l-2 border-sf-green bg-[rgba(62,207,142,0.05)]"
                    : "text-sf-text-muted hover:text-sf-text"
                  }
                `}
              >
                <Icon size={16} />
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Ollama status */}
        <div className="px-4 py-4 border-t border-sf-border flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${statusColor}`} />
          <span className="text-xs font-mono text-sf-text-muted">
            Ollama ·{" "}
            {ollamaStatus === "healthy"
              ? "Online"
              : ollamaStatus === "unhealthy"
                ? "Offline"
                : "Checking"}
          </span>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col h-full bg-sf-bg overflow-hidden">
        {/* Top bar */}
        <header className="h-[52px] shrink-0 flex items-center justify-between px-6 border-b border-sf-border">
          <h1 className="text-lg font-normal text-sf-text">
            {NAV_ITEMS.find((n) => location.pathname.startsWith(n.to))?.label ?? "SpecForge"}
          </h1>
          {activeRuns > 0 && (
            <span className="inline-flex items-center px-3 py-1 rounded-pill text-xs font-medium text-sf-green bg-[rgba(62,207,142,0.1)] border border-[rgba(62,207,142,0.3)]">
              {activeRuns} running
            </span>
          )}
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-y-auto">{children}</div>
      </main>
    </div>
  );
}

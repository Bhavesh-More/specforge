import { useQuery } from "@tanstack/react-query";
import { LayoutTemplate, Activity, Box } from "lucide-react";
import * as api from "../api";

export function DashboardPage() {
  const { data: stats } = useQuery({
    queryKey: ["stats"],
    queryFn: api.getStats,
  });
  const { data: recentExecutions } = useQuery({
    queryKey: ["executions", "recent"],
    queryFn: () => api.getRecentExecutions(5),
  });

  const statsData = (stats || {}) as Record<string, number>;

  return (
    <div className="h-full overflow-y-auto px-6 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-medium text-sf-text">Dashboard</h2>
        <span className="text-sm text-sf-text-muted">
          {new Date().toLocaleDateString()}
        </span>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          title="Templates"
          value={statsData.templates_count || 0}
          icon={LayoutTemplate}
          color="bg-sf-blue"
        />
        <StatCard
          title="Executions"
          value={statsData.executions_count || 0}
          icon={Activity}
          color="bg-sf-green"
        />
        <StatCard
          title="Healing Events"
          value={statsData.healing_events_count || 0}
          icon={Box}
          color="bg-sf-amber"
        />
        <StatCard
          title="Templates (Registry)"
          value={statsData.registry_templates || 0}
          icon={LayoutTemplate}
          color="bg-sf-purple"
        />
      </div>

      {/* Recent Executions */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium text-sf-text">Recent Executions</h3>
          <a href="/executions" className="text-sm text-sf-green hover:underline">
            View All
          </a>
        </div>
        <div className="bg-sf-bg-deep border border-sf-border rounded-lg overflow-hidden">
          {recentExecutions && (recentExecutions as Array<Record<string, unknown>>).length > 0 ? (
            <table className="w-full">
              <thead>
                <tr className="border-b border-sf-border bg-sf-bg">
                  <th className="text-left font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-3">
                    Template
                  </th>
                  <th className="text-left font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-3">
                    Status
                  </th>
                  <th className="text-left font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-3">
                    Started
                  </th>
                  <th className="text-right font-mono text-xs uppercase tracking-[1.2px] text-sf-text-muted px-4 py-3">
                    Duration
                  </th>
                </tr>
              </thead>
              <tbody>
                {(recentExecutions as Array<Record<string, unknown>>).map((exec) => (
                  <tr
                    key={exec.id as string}
                    className="border-b border-sf-border hover:bg-[rgba(255,255,255,0.03)] transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium text-sf-text">
                        {exec.template_name as string}
                      </div>
                      <div className="text-xs text-sf-text-muted">
                        {(exec.id as string).slice(0, 8)}…
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${
                          (exec.status as string) === "COMPLETED"
                            ? "bg-sf-green/10 text-sf-green border border-sf-green/20"
                            : (exec.status as string) === "FAILED"
                              ? "bg-sf-red/10 text-sf-red border border-sf-red/20"
                              : (exec.status as string) === "RUNNING"
                                ? "bg-sf-amber/10 text-sf-amber border border-sf-amber/20"
                                : "bg-sf-surface text-sf-text-muted border border-sf-border-standard"
                        }`}
                      >
                        {(exec.status as string) || "UNKNOWN"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-sf-text-muted">
                      {exec.started_at
                        ? new Date(exec.started_at as string).toLocaleString()
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm text-sf-text-muted text-right">
                      {(exec.total_execution_time_ms as number) != null
                        ? `${((exec.total_execution_time_ms as number) / 1000).toFixed(1)}s`
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-8 text-center text-sf-text-muted">
              No recent executions
            </div>
          )}
        </div>
      </div>

      {/* Quick Actions */}
      <div>
        <h3 className="text-lg font-medium text-sf-text mb-4">Quick Actions</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <QuickAction
            title="Upload Template"
            description="Import a .ct.json template file"
            icon={LayoutTemplate}
            href="/templates"
          />
          <QuickAction
            title="Create New Template"
            description="Design a new Cognitive Template"
            icon={LayoutTemplate}
            href="/templates/design"
          />
          <QuickAction
            title="View Knowledge"
            description="Browse and edit rule files"
            icon={Activity}
            href="/knowledge"
          />
        </div>
      </div>
    </div>
  );
}

function StatCard({
  title,
  value,
  icon: Icon,
  color,
}: {
  title: string;
  value: number;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <div className="bg-sf-bg-deep border border-sf-border rounded-lg p-4 flex items-center justify-between">
      <div>
        <p className="text-sm text-sf-text-muted mb-1">{title}</p>
        <p className="text-2xl font-medium text-sf-text">{value}</p>
      </div>
      <div className={`p-3 rounded-lg ${color} bg-opacity-10`}>
        <Icon className={`${color.replace("bg-", "text-")}`} size={24} />
      </div>
    </div>
  );
}

function QuickAction({
  title,
  description,
  icon: Icon,
  href,
}: {
  title: string;
  description: string;
  icon: React.ElementType;
  href: string;
}) {
  return (
    <a
      href={href}
      className="bg-sf-bg-deep border border-sf-border rounded-lg p-4 hover:border-sf-green transition-colors group"
    >
      <div className="flex items-start gap-3">
        <div className="p-2 rounded bg-sf-bg-deep border border-sf-border group-hover:border-sf-green/30 transition-colors">
          <Icon className="text-sf-text-muted" size={20} />
        </div>
        <div>
          <h4 className="text-sm font-medium text-sf-text mb-1 group-hover:text-sf-green transition-colors">
            {title}
          </h4>
          <p className="text-xs text-sf-text-muted">{description}</p>
        </div>
      </div>
    </a>
  );
}

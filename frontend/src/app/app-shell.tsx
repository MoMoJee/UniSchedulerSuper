import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  FileText,
  LayoutDashboard,
  ListTodo,
  Menu,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Group, Panel, Separator } from "react-resizable-panels";

import type { FrontendBootstrap } from "../bootstrap";
import { Button } from "../components/ui/button";
import { Tooltip } from "../components/ui/tooltip";
import { cn } from "../lib/cn";
import { useUiStore } from "../stores/ui-store";

const navigation = [
  { to: "/", label: "日程", icon: CalendarDays },
  { to: "/todos", label: "待办", icon: ListTodo },
  { to: "/search", label: "搜索", icon: Search },
  { to: "/files", label: "文件", icon: FileText },
  { to: "/settings", label: "设置", icon: Settings },
];

function Navigation({ compact = false }: { compact?: boolean }) {
  return (
    <nav
      aria-label="主导航"
      className={cn("flex flex-col gap-1 p-3", compact && "p-2")}
    >
      {navigation.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          className={({ isActive }) =>
            cn(
              "shell-nav-link",
              isActive && "shell-nav-link--active",
              compact && "justify-center px-2",
            )
          }
          to={to}
        >
          <Icon aria-hidden="true" size={18} />
          {compact ? (
            <span className="sr-only">{label}</span>
          ) : (
            <span>{label}</span>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

function AgentPlaceholder() {
  return (
    <aside
      aria-label="Agent 面板"
      className="h-full border-l border-[var(--border)] bg-[var(--surface)] p-4"
    >
      <div className="flex items-center gap-2">
        <Sparkles
          aria-hidden="true"
          className="text-[var(--accent)]"
          size={20}
        />
        <h2 className="font-semibold">智能助手</h2>
      </div>
      <p className="mt-3 text-sm leading-6 text-[var(--text-muted)]">
        Agent 会话、附件和回滚界面将在 FR-5 接入当前已验证的服务端协议。
      </p>
    </aside>
  );
}

export function AppShell({ bootstrap }: { bootstrap: FrontendBootstrap }) {
  const location = useLocation();
  const reduceMotion = useReducedMotion();
  const {
    panelLayout,
    setPanelLayout,
    leftPanelOpen,
    setLeftPanelOpen,
    agentPanelOpen,
    setAgentPanelOpen,
  } = useUiStore();
  const pageTitle =
    navigation.find((item) => item.to === location.pathname)?.label ?? "工作台";

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="flex items-center gap-2">
          <Tooltip content="打开导航">
            <Button
              aria-label="打开导航"
              className="lg:hidden"
              variant="ghost"
              onClick={() => setLeftPanelOpen(!leftPanelOpen)}
            >
              <Menu aria-hidden="true" size={20} />
            </Button>
          </Tooltip>
          <LayoutDashboard
            aria-hidden="true"
            className="text-[var(--accent)]"
            size={22}
          />
          <span className="font-semibold">UniSchedulerSuper</span>
          <span className="text-sm text-[var(--text-muted)]">
            / {pageTitle}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden text-sm text-[var(--text-muted)] sm:inline">
            {bootstrap.user.username}
          </span>
          <Tooltip content="打开 Agent 面板">
            <Button
              aria-label="打开 Agent 面板"
              className="lg:hidden"
              variant="ghost"
              onClick={() => setAgentPanelOpen(!agentPanelOpen)}
            >
              <Sparkles aria-hidden="true" size={20} />
            </Button>
          </Tooltip>
        </div>
      </header>

      <div className="app-shell__desktop">
        <Group
          defaultLayout={panelLayout}
          id="main-workspace"
          onLayoutChanged={(layout) => setPanelLayout(layout)}
          orientation="horizontal"
          resizeTargetMinimumSize={{ coarse: 32, fine: 16 }}
        >
          <Panel id="navigation" minSize="13rem">
            <aside
              aria-label="导航与筛选"
              className="h-full border-r border-[var(--border)] bg-[var(--surface)]"
            >
              <Navigation />
            </aside>
          </Panel>
          <Separator
            aria-label="调整导航宽度"
            className="panel-separator"
            id="navigation-workspace"
          />
          <Panel id="workspace" minSize="24rem">
            <motion.main
              animate={{ opacity: 1, y: 0 }}
              className="h-full overflow-auto bg-[var(--surface-canvas)] p-4 md:p-6"
              initial={reduceMotion ? false : { opacity: 0, y: 4 }}
              transition={{ duration: reduceMotion ? 0 : 0.16 }}
            >
              <Outlet />
            </motion.main>
          </Panel>
          <Separator
            aria-label="调整 Agent 面板宽度"
            className="panel-separator"
            id="workspace-agent"
          />
          <Panel id="agent" minSize="16rem">
            <AgentPlaceholder />
          </Panel>
        </Group>
      </div>

      <div className="app-shell__mobile">
        {leftPanelOpen ? (
          <aside className="mobile-panel">
            <Navigation />
            <Button onClick={() => setLeftPanelOpen(false)}>
              <ChevronLeft aria-hidden="true" />
              关闭导航
            </Button>
          </aside>
        ) : null}
        <main className="overflow-auto bg-[var(--surface-canvas)] p-4">
          <Outlet />
        </main>
        {agentPanelOpen ? (
          <div className="mobile-panel">
            <AgentPlaceholder />
            <Button onClick={() => setAgentPanelOpen(false)}>
              <ChevronRight aria-hidden="true" />
              关闭助手
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

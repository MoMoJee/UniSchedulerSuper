import {
  CalendarPlus,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Ellipsis,
  FileText,
  ListTodo,
  Menu,
  Search,
  Settings2,
  Share2,
  Sparkles,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { lazy, Suspense, useEffect, useState } from "react";
import {
  NavLink,
  Outlet,
  useLocation,
  useSearchParams,
} from "react-router-dom";
import { Group, Panel, Separator } from "react-resizable-panels";

import type { FrontendBootstrap } from "../bootstrap";
import { Button } from "../components/ui/button";
import { Tooltip } from "../components/ui/tooltip";
import { cn } from "../lib/cn";
import { useUiStore } from "../stores/ui-store";
import { AgentWorkspace } from "../features/agent/agent-workspace";
import { HomeSidebar } from "../features/planner/home-sidebar";
import { CenteredModal } from "../components/ui/centered-modal";
import { FullscreenSurface } from "../components/ui/fullscreen-surface";
import { ConfirmDialog } from "../components/ui/dialog";
import { DropdownMenu, DropdownMenuItem } from "../components/ui/overlays";
import {
  WORKBENCH_SURFACES,
  useWorkbenchSurfaceStore,
  type WorkbenchSurface,
} from "./workbench-surface-store";
import styles from "./app-shell.module.css";

const GlobalSearchWorkspace = lazy(async () => ({
  default: (await import("../features/search/search-workspace"))
    .SearchWorkspace,
}));
const SettingsWorkspace = lazy(async () => ({
  default: (await import("../features/settings/settings-workspace"))
    .SettingsWorkspace,
}));
const FilesWorkspace = lazy(async () => ({
  default: (await import("../features/files/files-workspace")).FilesWorkspace,
}));
const ShareGroupsWorkspace = lazy(async () => ({
  default: (await import("../features/planner/share-groups-workspace"))
    .ShareGroupsWorkspace,
}));

const navigation = [
  { to: "/", label: "日程", icon: CalendarDays },
  { to: "/todos", label: "待办", icon: ListTodo },
  { to: "/share", label: "分享组", icon: Share2 },
  { to: "/files", label: "文件", icon: FileText },
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

function useMobileLayout() {
  const query = "(max-width: 1023px)";
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && window.matchMedia?.(query).matches,
  );
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return undefined;
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return isMobile;
}

export function AppShell({ bootstrap }: { bootstrap: FrontendBootstrap }) {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const reduceMotion = useReducedMotion();
  const isMobile = useMobileLayout();
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
  const isHome = location.pathname === "/";
  const [logoutOpen, setLogoutOpen] = useState(false);
  const hydrateSurface = useWorkbenchSurfaceStore((state) => state.hydrate);
  const surfaceValue = params.get("surface");
  const surface = (
    surfaceValue && WORKBENCH_SURFACES.has(surfaceValue) ? surfaceValue : null
  ) as WorkbenchSurface;
  useEffect(() => {
    hydrateSurface(surface, params.get("dialog"), params.get("entity"));
  }, [hydrateSurface, params, surface]);
  const openSurface = (next: Exclude<WorkbenchSurface, null>) => {
    const copy = new URLSearchParams(params);
    copy.set("surface", next);
    setParams(copy);
  };
  const closeSurface = () => {
    const copy = new URLSearchParams(params);
    copy.delete("surface");
    copy.delete("dialog");
    copy.delete("entity");
    setParams(copy);
  };

  return (
    <div className={cn("app-shell", styles.boundary)}>
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
          <CalendarPlus
            aria-hidden="true"
            className="text-[var(--accent)]"
            size={22}
          />
          <span className="app-brand">UniSchedulerSuper</span>
          <span className="text-sm text-[var(--text-muted)]">
            / {pageTitle}
          </span>
        </div>
        <div className="top-island">
          <button
            aria-label="打开全局搜索"
            className="app-header__search"
            onClick={() => openSurface("search")}
            type="button"
          >
            <Search aria-hidden="true" size={17} />
            <span>搜索日程、待办、提醒…</span>
          </button>
          <button
            aria-label="打开设置"
            className="top-island__icon"
            onClick={() => openSurface("settings")}
            type="button"
          >
            <Settings2 aria-hidden="true" size={17} />
          </button>
          <DropdownMenu
            trigger={
              <button
                aria-label="打开功能菜单"
                className="top-island__icon"
                type="button"
              >
                <Ellipsis aria-hidden="true" size={18} />
              </button>
            }
          >
            <DropdownMenuItem
              className="menu-item"
              onSelect={() => openSurface("files")}
            >
              <FileText size={16} /> 文件管理
            </DropdownMenuItem>
            <DropdownMenuItem
              className="menu-item"
              onSelect={() => openSurface("settings")}
            >
              <Settings2 size={16} /> 设置
            </DropdownMenuItem>
            <DropdownMenuItem
              className="menu-item"
              onSelect={() => {
                window.location.assign("/help/");
              }}
            >
              <CircleHelp size={16} /> 帮助
            </DropdownMenuItem>
            <DropdownMenuItem
              className="menu-item menu-item--danger"
              onSelect={() => setLogoutOpen(true)}
            >
              退出登录
            </DropdownMenuItem>
          </DropdownMenu>
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
      <CenteredModal
        onOpenChange={(open) => !open && closeSurface()}
        open={surface === "search"}
        title="全局搜索"
        description="搜索日程、待办和提醒，并在当前工作台定位。"
        size="lg"
      >
        <Suspense
          fallback={
            <p className="text-sm text-[var(--text-muted)]">正在打开搜索…</p>
          }
        >
          <GlobalSearchWorkspace embedded onRequestClose={closeSurface} />
        </Suspense>
      </CenteredModal>
      <CenteredModal
        onOpenChange={(open) => !open && closeSurface()}
        open={surface === "settings"}
        title="设置"
        description="修改用户、显示、提醒与 Agent 偏好。"
        size="xl"
      >
        <Suspense fallback={<p>正在加载设置…</p>}>
          <SettingsWorkspace embedded onRequestClose={closeSurface} />
        </Suspense>
      </CenteredModal>
      <CenteredModal
        onOpenChange={(open) => !open && closeSurface()}
        open={surface === "share"}
        title="分享组管理"
        description="创建、加入或管理协作日程组。"
        size="lg"
      >
        <Suspense fallback={<p>正在加载分享组…</p>}>
          <ShareGroupsWorkspace embedded onRequestClose={closeSurface} />
        </Suspense>
      </CenteredModal>
      <FullscreenSurface
        onClose={closeSurface}
        open={surface === "files"}
        title="文件管理"
      >
        <Suspense fallback={<p>正在加载文件管理器…</p>}>
          <FilesWorkspace embedded />
        </Suspense>
      </FullscreenSurface>
      <ConfirmDialog
        open={logoutOpen}
        onOpenChange={setLogoutOpen}
        onConfirm={() => window.location.assign("/user_logout/")}
        title="确认退出登录？"
        description="当前未发送的 Agent 草稿不会保存。"
        confirmLabel="退出"
      />

      {!isMobile ? (
        <main aria-label="主工作区布局" className="app-shell__desktop">
          <Group
            defaultLayout={panelLayout}
            id="main-workspace"
            onLayoutChanged={(layout) => setPanelLayout(layout)}
            orientation="horizontal"
            resizeTargetMinimumSize={{ coarse: 32, fine: 16 }}
          >
            <Panel id="navigation" minSize="13rem">
              {isHome ? (
                <HomeSidebar username={bootstrap.user.username} />
              ) : (
                <aside
                  aria-label="导航与筛选"
                  className="h-full overflow-auto border-r border-[var(--border)] bg-[var(--surface)]"
                >
                  <Navigation />
                </aside>
              )}
            </Panel>
            <Separator
              aria-label="调整导航宽度"
              className="panel-separator"
              id="navigation-workspace"
            />
            <Panel id="workspace" minSize="24rem">
              <motion.div
                animate={{ opacity: 1, y: 0 }}
                aria-label="当前页面内容"
                className={
                  isHome
                    ? "h-full overflow-hidden bg-[var(--surface-canvas)] p-2"
                    : "h-full overflow-auto bg-[var(--surface-canvas)] p-4 md:p-6"
                }
                initial={reduceMotion ? false : { opacity: 0, y: 4 }}
                role="region"
                transition={{ duration: reduceMotion ? 0 : 0.16 }}
              >
                <Outlet />
              </motion.div>
            </Panel>
            <Separator
              aria-label="调整 Agent 面板宽度"
              className="panel-separator"
              id="workspace-agent"
            />
            <Panel id="agent" minSize="16rem">
              <AgentWorkspace
                username={bootstrap.user.username}
                webSocketPath={bootstrap.endpoints.agentWebSocketPath}
              />
            </Panel>
          </Group>
        </main>
      ) : (
        <div className="app-shell__mobile">
          {leftPanelOpen ? (
            <aside className="mobile-panel">
              {isHome ? (
                <HomeSidebar username={bootstrap.user.username} />
              ) : (
                <Navigation />
              )}
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
              <AgentWorkspace
                username={bootstrap.user.username}
                webSocketPath={bootstrap.endpoints.agentWebSocketPath}
              />
              <Button onClick={() => setAgentPanelOpen(false)}>
                <ChevronRight aria-hidden="true" />
                关闭助手
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

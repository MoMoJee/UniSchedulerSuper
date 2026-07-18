import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { plannerApi } from "../../api/planner";
import { apiClient } from "../../api/http";
import { Button } from "../../components/ui/button";
import styles from "./search-workspace.module.css";

const DAY = 86_400_000;
function range(days: number): { from: string; to: string } {
  const now = new Date();
  return {
    from: new Date(now.getTime() - 180 * DAY).toISOString(),
    to: new Date(now.getTime() + days * DAY).toISOString(),
  };
}

export function SearchWorkspace({
  embedded = false,
  onRequestClose,
}: {
  embedded?: boolean;
  onRequestClose?: () => void;
} = {}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [types, setTypes] = useState<Array<"event" | "todo" | "reminder">>([
    "event",
    "todo",
    "reminder",
  ]);
  const [results, setResults] = useState<Array<Record<string, unknown>>>([]);
  const [groups, setGroups] = useState<Array<{ id: string; name: string }>>([]);
  const [shareGroups, setShareGroups] = useState<
    Array<{ id: string; name: string }>
  >([]);
  const [groupId, setGroupId] = useState("");
  const [shareGroupId, setShareGroupId] = useState("");
  const [rangeDays, setRangeDays] = useState(365);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      plannerApi.listGroups(controller.signal),
      apiClient.request<{ groups?: Array<Record<string, unknown>> }>(
        "/api/share-groups/my-groups/",
        { signal: controller.signal },
      ),
    ])
      .then(([personal, shared]) => {
        setGroups(
          (personal.groups ?? []).flatMap((item) =>
            typeof item.group_id === "string" && typeof item.name === "string"
              ? [{ id: item.group_id, name: item.name }]
              : [],
          ),
        );
        setShareGroups(
          (shared.groups ?? []).flatMap((item) =>
            typeof item.share_group_id === "string" &&
            typeof item.share_group_name === "string"
              ? [{ id: item.share_group_id, name: item.share_group_name }]
              : [],
          ),
        );
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2 || !types.length) {
      return undefined;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setState("loading");
      const windowRange = range(rangeDays);
      void plannerApi
        .search(
          text,
          windowRange.from,
          windowRange.to,
          types,
          controller.signal,
        )
        .then((response) => {
          if (!controller.signal.aborted) {
            const values = (response.results ?? response.items ?? []) as Array<
              Record<string, unknown>
            >;
            setResults(
              values.filter(
                (item) =>
                  (!groupId || item.group_id === groupId) &&
                  (!shareGroupId || item.share_group_id === shareGroupId),
              ),
            );
            setActiveIndex(-1);
            setState("idle");
          }
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setState("error");
            setError(reason instanceof Error ? reason.message : "搜索失败。");
          }
        });
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [groupId, query, rangeDays, shareGroupId, types]);
  const toggle = (type: "event" | "todo" | "reminder") =>
    setTypes((values) =>
      values.includes(type)
        ? values.filter((value) => value !== type)
        : [...values, type],
    );
  const jump = (result: Record<string, unknown>) => {
    const kind = result.type;
    onRequestClose?.();
    if (kind === "todo")
      navigate(
        `/?dialog=todo&entity=${encodeURIComponent(String(result.entity_id ?? result.id ?? ""))}`,
      );
    else
      navigate(
        `/?selected=${encodeURIComponent(String(result.entity_id ?? result.id ?? ""))}${typeof result.start === "string" ? `&date=${encodeURIComponent(result.start.slice(0, 10))}` : ""}`,
      );
  };
  return (
    <section
      aria-label={embedded ? "全局搜索" : undefined}
      aria-labelledby={embedded ? undefined : "search-title"}
      className={`search-workspace ${styles.root}`}
      data-ui="search-workspace"
    >
      {!embedded ? (
        <>
          <h1 id="search-title">全局搜索</h1>
          <p className="text-[var(--text-muted)]">
            搜索当前与未来窗口内的日程、待办和提醒；输入至少两个字符。
          </p>
        </>
      ) : null}
      <label className="search-input">
        <Search aria-hidden="true" size={19} />
        <input
          autoFocus
          aria-label="搜索关键词"
          role="combobox"
          aria-activedescendant={
            activeIndex >= 0 ? `search-result-${activeIndex}` : undefined
          }
          aria-controls="search-results"
          aria-expanded={results.length > 0}
          onKeyDown={(event) => {
            if (!results.length) return;
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((value) =>
                Math.min(value + 1, results.length - 1),
              );
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((value) => Math.max(value - 1, 0));
            } else if (event.key === "Enter" && activeIndex >= 0) {
              event.preventDefault();
              jump(results[activeIndex]);
            } else if (event.key === "Escape") {
              setQuery("");
              setResults([]);
              setActiveIndex(-1);
            }
          }}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索日程、待办、提醒"
          value={query}
        />
        {query ? (
          <Button
            aria-label="清空搜索"
            variant="ghost"
            onClick={() => setQuery("")}
          >
            <X aria-hidden="true" size={16} />
          </Button>
        ) : null}
      </label>
      <fieldset className="search-types">
        <legend>搜索类型</legend>
        {(["event", "todo", "reminder"] as const).map((type) => (
          <label key={type}>
            <input
              checked={types.includes(type)}
              onChange={() => toggle(type)}
              type="checkbox"
            />
            {{ event: "日程", todo: "待办", reminder: "提醒" }[type]}
          </label>
        ))}
      </fieldset>
      <div className="search-advanced">
        <label>
          个人日程组
          <select
            value={groupId}
            onChange={(event) => setGroupId(event.target.value)}
          >
            <option value="">全部</option>
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          分享组
          <select
            value={shareGroupId}
            onChange={(event) => setShareGroupId(event.target.value)}
          >
            <option value="">全部</option>
            {shareGroups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          时间范围
          <select
            value={rangeDays}
            onChange={(event) => setRangeDays(Number(event.target.value))}
          >
            <option value={30}>未来 30 天</option>
            <option value={180}>未来半年</option>
            <option value={365}>未来一年</option>
            <option value={1095}>未来三年</option>
          </select>
        </label>
      </div>
      {state === "loading" ? <p>正在搜索…</p> : null}
      {state === "error" ? <p className="agent-error">{error}</p> : null}
      {query.trim().length >= 2 && state === "idle" && !results.length ? (
        <p className="empty-state">没有匹配结果。</p>
      ) : null}
      <div
        aria-label="搜索结果"
        className="search-results"
        id="search-results"
        role="listbox"
      >
        {query.trim().length >= 2
          ? results.map((result, index) => (
              <button
                aria-selected={activeIndex === index}
                id={`search-result-${index}`}
                key={`${String(result.id ?? result.entity_id ?? "result")}-${index}`}
                onMouseEnter={() => setActiveIndex(index)}
                role="option"
                onClick={() => jump(result)}
                type="button"
              >
                <strong>
                  {String(result.title ?? result.name ?? "未命名项目")}
                </strong>
                <span>
                  {String(result.type ?? "项目")} ·{" "}
                  {String(
                    result.start ??
                      result.due ??
                      result.trigger ??
                      result.description ??
                      "",
                  )}
                </span>
              </button>
            ))
          : null}
      </div>
    </section>
  );
}

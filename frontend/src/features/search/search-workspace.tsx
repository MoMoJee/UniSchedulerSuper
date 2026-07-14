import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { plannerApi } from "../../api/planner";
import { Button } from "../../components/ui/button";

const DAY = 86_400_000;
function range(): { from: string; to: string } {
  const now = new Date();
  return {
    from: new Date(now.getTime() - 180 * DAY).toISOString(),
    to: new Date(now.getTime() + 365 * DAY).toISOString(),
  };
}

export function SearchWorkspace() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [types, setTypes] = useState<Array<"event" | "todo" | "reminder">>([
    "event",
    "todo",
    "reminder",
  ]);
  const [results, setResults] = useState<Array<Record<string, unknown>>>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2 || !types.length) {
      return undefined;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setState("loading");
      const windowRange = range();
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
            setResults(
              (response.results ?? response.items ?? []) as Array<
                Record<string, unknown>
              >,
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
  }, [query, types]);
  const toggle = (type: "event" | "todo" | "reminder") =>
    setTypes((values) =>
      values.includes(type)
        ? values.filter((value) => value !== type)
        : [...values, type],
    );
  const jump = (result: Record<string, unknown>) => {
    const kind = result.type;
    if (kind === "todo") navigate("/todos");
    else
      navigate(
        `/?selected=${encodeURIComponent(String(result.entity_id ?? result.id ?? ""))}`,
      );
  };
  return (
    <section aria-labelledby="search-title" className="search-workspace">
      <h1 id="search-title">全局搜索</h1>
      <p className="text-[var(--text-muted)]">
        搜索当前与未来窗口内的日程、待办和提醒；输入至少两个字符。
      </p>
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

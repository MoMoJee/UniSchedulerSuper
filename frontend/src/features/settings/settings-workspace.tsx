import { useEffect, useRef, useState } from "react";
import { useUiStore, type ThemePreference } from "../../stores/ui-store";

import { settingsApi, type UserPreferences } from "../../api/settings";
import { Button } from "../../components/ui/button";
import { CourseImporter } from "./course-importer";

function object(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function AgentOptimization({
  value,
  onSave,
}: {
  value: Record<string, unknown>;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}) {
  const config = object(value.config);
  return (
    <form
      className="settings-section"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const number = (name: string, fallback: number) => {
          const value = Number(data.get(name));
          return Number.isFinite(value) ? value : fallback;
        };
        void onSave({
          enable_context_optimization: data.get("enabled") === "on",
          optimization_config: {
            target_usage_ratio: number("target", 60) / 100,
            token_calculation_method: data.get("method"),
            enable_summarization: data.get("summarize") === "on",
            summary_trigger_ratio: number("trigger", 50) / 100,
            min_messages_before_summary: number("minimum", 20),
            compress_tool_output: data.get("compress") === "on",
            tool_output_max_tokens: number("toolTokens", 200),
            tool_compress_preserve_recent_messages: number("preserve", 5),
            recursion_limit: number("recursion", 25),
          },
        });
      }}
    >
      <h2>Agent 上下文优化</h2>
      <label className="settings-check">
        <input
          defaultChecked={value.enable_context_optimization !== false}
          name="enabled"
          type="checkbox"
        />
        启用上下文优化
      </label>
      <div className="settings-grid">
        <label>
          上下文使用率（%）
          <input
            defaultValue={Number(config.target_usage_ratio ?? 0.6) * 100}
            max="90"
            min="30"
            name="target"
            step="5"
            type="number"
          />
        </label>
        <label>
          Token 计算方式
          <select
            defaultValue={String(config.token_calculation_method ?? "actual")}
            name="method"
          >
            <option value="actual">实际值</option>
            <option value="tiktoken">精确计算</option>
            <option value="estimate">估算</option>
          </select>
        </label>
        <label>
          摘要触发阈值（%）
          <input
            defaultValue={Number(config.summary_trigger_ratio ?? 0.5) * 100}
            max="80"
            min="30"
            name="trigger"
            step="5"
            type="number"
          />
        </label>
        <label>
          最少消息数
          <input
            defaultValue={Number(config.min_messages_before_summary ?? 20)}
            max="50"
            min="5"
            name="minimum"
            type="number"
          />
        </label>
        <label>
          工具输出最大 Token
          <input
            defaultValue={Number(config.tool_output_max_tokens ?? 200)}
            max="1000"
            min="50"
            name="toolTokens"
            step="50"
            type="number"
          />
        </label>
        <label>
          保留最近工具消息
          <input
            defaultValue={Number(
              config.tool_compress_preserve_recent_messages ?? 5,
            )}
            max="20"
            min="1"
            name="preserve"
            type="number"
          />
        </label>
        <label>
          最大执行步数
          <input
            defaultValue={Number(config.recursion_limit ?? 25)}
            max="100"
            min="10"
            name="recursion"
            step="5"
            type="number"
          />
        </label>
      </div>
      <label className="settings-check">
        <input
          defaultChecked={config.enable_summarization !== false}
          name="summarize"
          type="checkbox"
        />{" "}
        启用智能摘要
      </label>
      <label className="settings-check">
        <input
          defaultChecked={config.compress_tool_output !== false}
          name="compress"
          type="checkbox"
        />{" "}
        压缩过长工具输出
      </label>
      <Button type="submit" variant="primary">
        保存优化配置
      </Button>
    </form>
  );
}

export function SettingsWorkspace({
  embedded = false,
  onRequestClose,
}: { embedded?: boolean; onRequestClose?: () => void } = {}) {
  const setUiTheme = useUiStore((state) => state.setTheme);
  const [activeTab, setActiveTab] = useState<
    "basic" | "calendar" | "display" | "reminders" | "ai" | "mine"
  >("basic");
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [agent, setAgent] = useState<Record<string, unknown> | null>(null);
  const [skills, setSkills] = useState<Array<Record<string, unknown>>>([]);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const openingTheme = useRef(useUiStore.getState().theme);
  useEffect(() => {
    void Promise.all([
      settingsApi.getPreferences(),
      settingsApi.getAgentConfig(),
      settingsApi.getSkills(),
    ])
      .then(([prefs, config, loadedSkills]) => {
        setPreferences(prefs);
        setAgent(object(config));
        setSkills(loadedSkills.items.map(object));
      })
      .catch((error: unknown) =>
        setMessage(error instanceof Error ? error.message : "无法加载设置。"),
      );
  }, []);
  const save = async () => {
    if (!preferences) return;
    setSaving(true);
    try {
      await settingsApi.savePreferences(preferences);
      setUiTheme(
        (typeof preferences.theme === "string"
          ? preferences.theme
          : "light") as ThemePreference,
      );
      setMessage("设置已保存。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败。");
    } finally {
      setSaving(false);
    }
  };
  const model = object(agent?.model);
  const allModels = object(model.all_models);
  const currentModel =
    typeof model.current_model_id === "string" ? model.current_model_id : "";
  const optimization = object(agent?.optimization);
  const tokenUsage = object(agent?.token_usage);
  return (
    <section
      aria-labelledby="settings-title"
      className={`settings-workspace${embedded ? " settings-workspace--embedded" : ""}`}
      data-active-tab={activeTab}
    >
      <header className="settings-workspace__header">
        <div>
          <span className="workspace-eyebrow">用户设置</span>
          <h1 id="settings-title">设置中心</h1>
          <p>
            显示、日程偏好、提醒与 Agent
            配置集中在同一处；保存按钮只提交相应配置。
          </p>
        </div>
        <nav aria-label="设置分类" className="settings-tabs">
          {(
            [
              ["basic", "基本设置"],
              ["calendar", "日程偏好"],
              ["display", "显示偏好"],
              ["reminders", "提醒设置"],
              ["ai", "AI 设置"],
              ["mine", "我的"],
            ] as const
          ).map(([id, label]) => (
            <button
              aria-current={activeTab === id ? "page" : undefined}
              key={id}
              onClick={() => setActiveTab(id)}
              type="button"
            >
              {label}
            </button>
          ))}
        </nav>
      </header>
      {!preferences ? (
        <p>正在加载设置…</p>
      ) : (
        <section
          className="settings-section settings-panel settings-panel--preferences"
          id="settings-display"
        >
          <h2>
            {
              (
                {
                  basic: "基本设置",
                  calendar: "日程偏好",
                  display: "显示偏好",
                  reminders: "提醒设置",
                } as Record<string, string>
              )[activeTab]
            }
          </h2>
          <div className="settings-grid">
            {activeTab === "basic" ? (
              <>
                <label>
                  语言
                  <select aria-label="语言" defaultValue="zh-CN">
                    <option value="zh-CN">简体中文</option>
                  </select>
                </label>
                <label>
                  时区
                  <select aria-label="时区" defaultValue="Asia/Shanghai">
                    <option value="Asia/Shanghai">
                      Asia/Shanghai（UTC+8）
                    </option>
                  </select>
                </label>
                <label className="settings-check">
                  <input disabled type="checkbox" /> 云端多设备同步（即将推出）
                </label>
              </>
            ) : null}
            {activeTab === "display" ? (
              <>
                <label>
                  主题
                  <select
                    aria-label="主题"
                    onChange={(event) => {
                      const theme = event.target.value as ThemePreference;
                      setPreferences({ ...preferences, theme });
                      // 旧版主题选择是即时可见的；保存仅负责持久化到服务器。
                      setUiTheme(theme);
                    }}
                    value={
                      typeof preferences.theme === "string"
                        ? preferences.theme
                        : "light"
                    }
                  >
                    <option value="light">浅色</option>
                    <option value="dark">深色</option>
                    <option value="china-red">中国红</option>
                    <option value="warm-pastel">暖调粉彩</option>
                    <option value="cool-pastel">冷调粉彩</option>
                    <option value="macaron">马卡龙</option>
                    <option value="dopamine">多巴胺</option>
                    <option value="forest">森林</option>
                    <option value="sunset">落日</option>
                    <option value="ocean">海洋</option>
                    <option value="sakura">樱花</option>
                    <option value="cyberpunk">赛博朋克</option>
                    <option value="system">跟随系统</option>
                  </select>
                </label>
                <label className="settings-check">
                  <input
                    checked={preferences.use_gold_theme === true}
                    onChange={(event) =>
                      setPreferences({
                        ...preferences,
                        use_gold_theme: event.target.checked,
                      })
                    }
                    type="checkbox"
                  />{" "}
                  启用金色主题装饰
                </label>
              </>
            ) : null}
            {activeTab === "calendar" ? (
              <>
                <label>
                  默认日历视图
                  <select
                    aria-label="默认日历视图"
                    onChange={(event) =>
                      setPreferences({
                        ...preferences,
                        calendar_view_default: event.target.value,
                      })
                    }
                    value={
                      typeof preferences.calendar_view_default === "string"
                        ? preferences.calendar_view_default
                        : "dayGridMonth"
                    }
                  >
                    <option value="dayGridMonth">月视图</option>
                    <option value="timeGridWeek">周视图</option>
                    <option value="timeGridTwoDay">2 日视图</option>
                  </select>
                </label>
                <label>
                  默认日程时长（分钟）
                  <input
                    aria-label="默认日程时长"
                    min="5"
                    onChange={(event) =>
                      setPreferences({
                        ...preferences,
                        default_event_duration: Number(event.target.value),
                      })
                    }
                    type="number"
                    value={
                      typeof preferences.default_event_duration === "number"
                        ? preferences.default_event_duration
                        : 60
                    }
                  />
                </label>
                <label className="settings-check">
                  <input
                    checked={preferences.show_week_number === true}
                    onChange={(event) =>
                      setPreferences({
                        ...preferences,
                        show_week_number: event.target.checked,
                      })
                    }
                    type="checkbox"
                  />
                  显示周数
                </label>
              </>
            ) : null}
            {activeTab === "reminders" ? (
              <>
                <label className="settings-check">
                  <input
                    checked={preferences.reminder_enabled === true}
                    onChange={(event) =>
                      setPreferences({
                        ...preferences,
                        reminder_enabled: event.target.checked,
                      })
                    }
                    type="checkbox"
                  />{" "}
                  启用提醒
                </label>
                <label className="settings-check">
                  <input
                    checked={preferences.reminder_sound === true}
                    onChange={(event) =>
                      setPreferences({
                        ...preferences,
                        reminder_sound: event.target.checked,
                      })
                    }
                    type="checkbox"
                  />{" "}
                  提醒声音
                </label>
                <label className="settings-check">
                  <input disabled type="checkbox" />{" "}
                  系统通知高级规则（即将推出）
                </label>
              </>
            ) : null}
          </div>
          <Button
            disabled={saving}
            variant="primary"
            onClick={() => void save()}
          >
            保存设置
          </Button>
        </section>
      )}
      <section
        className="settings-section settings-panel settings-panel--ai"
        id="settings-agent"
      >
        <h2>Agent 配置</h2>
        {agent ? (
          <>
            <label>
              当前模型
              <select
                aria-label="当前模型"
                onChange={(event) =>
                  void settingsApi
                    .updateModel({ current_model_id: event.target.value })
                    .then(() => settingsApi.getAgentConfig())
                    .then((value) => {
                      setAgent(object(value));
                      setMessage("模型已切换；仅影响新请求。");
                    })
                    .catch((error: unknown) =>
                      setMessage(
                        error instanceof Error
                          ? error.message
                          : "模型切换失败。",
                      ),
                    )
                }
                value={currentModel}
              >
                {Object.entries(allModels).map(([id, info]) => (
                  <option key={id} value={id}>
                    {String(object(info).name ?? id)}
                  </option>
                ))}
              </select>
            </label>
            <label className="settings-check">
              <input
                checked={model.thinking_enabled === true}
                disabled={
                  object(allModels[currentModel]).thinking_mode ===
                    "unsupported" ||
                  object(allModels[currentModel]).thinking_mode === "forced"
                }
                onChange={(event) =>
                  void settingsApi
                    .updateModel({ thinking_enabled: event.target.checked })
                    .then(() => setMessage("思考模式已保存。"))
                    .catch((error: unknown) =>
                      setMessage(
                        error instanceof Error ? error.message : "保存失败。",
                      ),
                    )
                }
                type="checkbox"
              />
              启用思考模式
            </label>
          </>
        ) : (
          <p>正在加载 Agent 配置…</p>
        )}
      </section>
      {agent ? (
        <div
          className="settings-panel settings-panel--ai"
          id="settings-context"
        >
          <AgentOptimization
            onSave={async (body) => {
              try {
                await settingsApi.updateOptimization(body);
                setAgent(object(await settingsApi.getAgentConfig()));
                setMessage("上下文优化配置已保存；仅影响之后的 Agent 请求。");
              } catch (error) {
                setMessage(
                  error instanceof Error ? error.message : "保存优化配置失败。",
                );
              }
            }}
            value={optimization}
          />
        </div>
      ) : null}
      {agent ? (
        <section
          className="settings-section settings-panel settings-panel--ai"
          id="settings-usage"
        >
          <h2>本月 Token 用量</h2>
          <p>
            {String(tokenUsage.current_month ?? "当前月份")}：已使用{" "}
            {String(tokenUsage.monthly_used ?? 0)} /{" "}
            {String(tokenUsage.monthly_credit ?? "-")}；剩余{" "}
            {String(tokenUsage.remaining ?? "-")}。
          </p>
          <ul className="settings-token-list">
            {Object.entries(object(tokenUsage.models)).map(
              ([id, modelValue]) => {
                const item = object(modelValue);
                return (
                  <li key={id}>
                    {String(item.name ?? id)}：输入{" "}
                    {String(item.input_tokens ?? 0)}，输出{" "}
                    {String(item.output_tokens ?? 0)}，费用{" "}
                    {String(item.cost ?? 0)}
                  </li>
                );
              },
            )}
          </ul>
        </section>
      ) : null}
      <section
        className="settings-section settings-panel settings-panel--mine"
        id="settings-skills"
      >
        <h2>Skills</h2>
        {skills.map((skill) => (
          <label className="settings-check" key={String(skill.id)}>
            <input
              checked={skill.is_active === true}
              onChange={() => {
                const id = Number(skill.id);
                void settingsApi
                  .toggleSkill(id)
                  .then((result) =>
                    setSkills((values) =>
                      values.map((item) =>
                        Number(item.id) === id
                          ? { ...item, is_active: result.is_active }
                          : item,
                      ),
                    ),
                  )
                  .catch((error: unknown) =>
                    setMessage(
                      error instanceof Error
                        ? error.message
                        : "切换 Skill 失败。",
                    ),
                  );
              }}
              type="checkbox"
            />
            {String(skill.name)}
            <small>{String(skill.description ?? "")}</small>
          </label>
        ))}
      </section>
      <div className="settings-panel settings-panel--mine" id="settings-course">
        <CourseImporter />
      </div>
      {message ? (
        <p aria-live="polite" className="agent-status">
          {message}
        </p>
      ) : null}
      {embedded ? (
        <footer className="settings-workspace__footer">
          <Button
            onClick={() => {
              setUiTheme(openingTheme.current);
              onRequestClose?.();
            }}
          >
            取消
          </Button>
          <Button
            disabled={saving || !preferences}
            onClick={() => void save()}
            variant="primary"
          >
            {saving ? "保存中…" : "保存设置"}
          </Button>
        </footer>
      ) : null}
    </section>
  );
}

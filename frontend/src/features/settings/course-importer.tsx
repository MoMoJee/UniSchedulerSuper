import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { settingsApi } from "../../api/settings";
import { plannerKeys } from "../../api/queryKeys";
import { Button } from "../../components/ui/button";

type Course = Record<string, unknown>;
export function CourseImporter() {
  const client = useQueryClient();
  const [semesters, setSemesters] = useState<
    Array<{ code: string; name: string }>
  >([]);
  const [semester, setSemester] = useState("");
  const [cookie, setCookie] = useState("");
  const [courses, setCourses] = useState<Course[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void settingsApi
      .semesters()
      .then((value) => {
        setSemesters(value.semesters);
        setSemester(value.current_semester);
      })
      .catch((error: unknown) =>
        setMessage(error instanceof Error ? error.message : "无法加载学期。"),
      );
  }, []);
  const fetchCourses = async () => {
    if (!cookie.trim()) {
      setMessage("请输入仅用于本次请求的教务系统 Cookie。");
      return;
    }
    setBusy(true);
    try {
      const value = await settingsApi.fetchCourses(cookie.trim(), semester);
      setCourses(value.courses.map((item) => item as Course));
      setSelected(
        new Set(
          value.courses.map((item) => String((item as Course).course_id)),
        ),
      );
      setMessage(`已解析 ${value.courses.length} 个课程时段，请确认后导入。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "课表解析失败。");
    } finally {
      setBusy(false);
    }
  };
  const confirm = async () => {
    const picked = courses.filter((course) =>
      selected.has(String(course.course_id)),
    );
    if (!picked.length) {
      setMessage("请至少选择一项课程。 ");
      return;
    }
    setBusy(true);
    try {
      const value = await settingsApi.confirmCourses(picked);
      setMessage(value.message);
      await client.invalidateQueries({ queryKey: plannerKeys.all });
      setCookie("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "课程导入失败。");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-labelledby="course-import-title" className="course-import">
      <h2 id="course-import-title">导入课表</h2>
      <p>Cookie 仅在当前内存请求中使用，不会写入 URL、localStorage 或日志。</p>
      <label>
        学期
        <select
          aria-label="导入学期"
          onChange={(event) => setSemester(event.target.value)}
          value={semester}
        >
          {semesters.map((item) => (
            <option key={item.code} value={item.code}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        教务系统 Cookie
        <textarea
          aria-label="教务系统 Cookie"
          onChange={(event) => setCookie(event.target.value)}
          placeholder="JSESSIONID=…"
          value={cookie}
        />
      </label>
      <Button
        disabled={busy}
        onClick={() => void fetchCourses()}
        variant="secondary"
      >
        解析课表
      </Button>
      {courses.length ? (
        <>
          <div className="course-list">
            {courses.map((course) => {
              const id = String(course.course_id);
              return (
                <label key={id}>
                  <input
                    checked={selected.has(id)}
                    onChange={() =>
                      setSelected((values) => {
                        const next = new Set(values);
                        if (next.has(id)) next.delete(id);
                        else next.add(id);
                        return next;
                      })
                    }
                    type="checkbox"
                  />
                  <span>
                    <strong>{String(course.name ?? "未命名课程")}</strong>
                    <small>
                      {String(course.time_slot ?? "")} ·{" "}
                      {String(course.rrule_text ?? "单次")}
                    </small>
                  </span>
                </label>
              );
            })}
          </div>
          <Button
            disabled={busy}
            onClick={() => void confirm()}
            variant="primary"
          >
            导入选中课程
          </Button>
        </>
      ) : null}
      {message ? (
        <p aria-live="polite" className="agent-status">
          {message}
        </p>
      ) : null}
    </section>
  );
}

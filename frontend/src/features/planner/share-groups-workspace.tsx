import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  Crown,
  LogOut,
  Plus,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiClient } from "../../api/http";
import { Button } from "../../components/ui/button";
import { ConfirmDialog, TextInputDialog } from "../../components/ui/dialog";
import styles from "./share-groups-workspace.module.css";

type ShareGroup = {
  share_group_id: string;
  share_group_name: string;
  share_group_description?: string;
  share_group_color?: string;
  role: "owner" | "member";
  member_count?: number;
  owner_name?: string;
  my_member_color?: string;
};

export function ShareGroupsWorkspace({
  embedded = false,
  onRequestClose,
}: { embedded?: boolean; onRequestClose?: () => void } = {}) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [joinOpen, setJoinOpen] = useState(false);
  const [pendingLeave, setPendingLeave] = useState<ShareGroup | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ShareGroup | null>(null);
  const [message, setMessage] = useState("");
  const groups = useQuery({
    queryKey: ["share-groups"],
    queryFn: async () => {
      const value = await apiClient.request<{ groups?: ShareGroup[] }>(
        "/api/share-groups/my-groups/",
      );
      return value.groups ?? [];
    },
  });
  const refresh = () =>
    client.invalidateQueries({ queryKey: ["share-groups"] });
  const runAction = async (
    request: () => Promise<unknown>,
    success: string,
  ) => {
    try {
      await request();
      await refresh();
      setMessage(success);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "操作失败，请稍后重试。",
      );
    }
  };
  return (
    <section
      className={styles.workspace}
      aria-labelledby="share-groups-title"
      data-ui="share-groups-workspace"
    >
      {!embedded ? (
        <header className={styles.pageHeader}>
          <div>
            <span className="workspace-eyebrow">协作日程</span>
            <h1 id="share-groups-title">分享组</h1>
            <p>与成员共享可见日程；只读权限会在日历中明确标识。</p>
          </div>
          <div className={styles.toolbar}>
            <Button onClick={() => setJoinOpen(true)}>
              <UserPlus size={16} /> 加入分享组
            </Button>
            <Button onClick={() => setCreateOpen(true)} variant="primary">
              <Plus size={16} /> 创建分享组
            </Button>
          </div>
        </header>
      ) : (
        <div aria-label="分享组操作" className={styles.toolbar}>
          <Button onClick={() => setJoinOpen(true)}>
            <UserPlus size={16} /> 加入分享组
          </Button>
          <Button onClick={() => setCreateOpen(true)} variant="primary">
            <Plus size={16} /> 创建分享组
          </Button>
        </div>
      )}
      {groups.isLoading ? (
        <p className={styles.state}>正在加载分享组…</p>
      ) : null}
      {groups.isError ? (
        <p className="agent-error">无法加载分享组，请稍后重试。</p>
      ) : null}
      <div className={styles.grid}>
        {groups.data?.map((group) => (
          <article
            className={styles.card}
            data-ui="share-group-card"
            key={group.share_group_id}
          >
            <span
              className={`${styles.dot} group-color-dot`}
              style={{
                background:
                  group.share_group_color ??
                  group.my_member_color ??
                  "var(--accent)",
              }}
            />
            <div className={styles.content} data-ui="share-group-content">
              <strong>{group.share_group_name}</strong>
              <p>{group.share_group_description || "没有描述"}</p>
              <small>
                {group.role === "owner" ? (
                  <>
                    <Crown aria-hidden="true" size={13} /> 群主
                  </>
                ) : (
                  `成员 · 群主 ${group.owner_name ?? "-"}`
                )}
                {group.member_count ? ` · ${group.member_count} 位成员` : ""}
              </small>
              <code>{group.share_group_id}</code>
            </div>
            <div className={styles.actions} data-ui="share-group-actions">
              <Button
                onClick={() => {
                  onRequestClose?.();
                  navigate(
                    `/?share=${encodeURIComponent(group.share_group_id)}`,
                  );
                }}
                variant="secondary"
              >
                <CalendarDays size={16} /> 查看日程
              </Button>
              <Button
                onClick={() =>
                  void navigator.clipboard?.writeText(group.share_group_id)
                }
                variant="ghost"
              >
                复制 ID
              </Button>
              {group.role === "owner" ? (
                <Button
                  onClick={() => setPendingDelete(group)}
                  variant="danger"
                >
                  <Trash2 size={16} /> 删除群组
                </Button>
              ) : (
                <Button
                  onClick={() => setPendingLeave(group)}
                  variant="secondary"
                >
                  <LogOut size={16} /> 退出群组
                </Button>
              )}
            </div>
          </article>
        ))}
      </div>
      {!groups.isLoading && !groups.data?.length ? (
        <div className="empty-state">
          <Users size={26} /> 尚未加入分享组。创建或加入后，会在这里集中管理。
        </div>
      ) : null}
      {message ? (
        <p aria-live="polite" className="agent-status">
          {message}
        </p>
      ) : null}
      <TextInputDialog
        title="创建分享组"
        description="输入名称后创建；创建成功后可将下方显示的组标识发送给成员。"
        label="分享组名称"
        initialValue=""
        confirmLabel="创建"
        open={createOpen}
        onOpenChange={setCreateOpen}
        onConfirm={(share_group_name) =>
          void runAction(
            () =>
              apiClient.request("/api/share-groups/create/", {
                method: "POST",
                body: { share_group_name },
              }),
            "分享组已创建。",
          )
        }
      />
      <TextInputDialog
        title="加入分享组"
        description="输入拥有者提供的分享组标识。"
        label="分享组标识"
        initialValue=""
        confirmLabel="加入"
        open={joinOpen}
        onOpenChange={setJoinOpen}
        onConfirm={(share_group_id) =>
          void runAction(
            () =>
              apiClient.request("/api/share-groups/join/", {
                method: "POST",
                body: { share_group_id },
              }),
            "已加入分享组。",
          )
        }
      />
      <ConfirmDialog
        confirmLabel="退出群组"
        description={`退出后将不再看到「${pendingLeave?.share_group_name ?? ""}」的共享日程。`}
        onConfirm={() =>
          pendingLeave &&
          void runAction(
            () =>
              apiClient.request(
                `/api/share-groups/${encodeURIComponent(pendingLeave.share_group_id)}/leave/`,
                { method: "POST" },
              ),
            "已退出分享组。",
          ).finally(() => setPendingLeave(null))
        }
        onOpenChange={(open) => !open && setPendingLeave(null)}
        open={pendingLeave !== null}
        title="确认退出分享组？"
      />
      <ConfirmDialog
        confirmLabel="删除群组"
        description={`删除「${pendingDelete?.share_group_name ?? ""}」会移除所有成员关系和共享日程投影，不能撤销。`}
        onConfirm={() =>
          pendingDelete &&
          void runAction(
            () =>
              apiClient.request(
                `/api/share-groups/${encodeURIComponent(pendingDelete.share_group_id)}/delete/`,
                { method: "DELETE" },
              ),
            "分享组已删除。",
          ).finally(() => setPendingDelete(null))
        }
        onOpenChange={(open) => !open && setPendingDelete(null)}
        open={pendingDelete !== null}
        title="确认删除分享组？"
      />
    </section>
  );
}

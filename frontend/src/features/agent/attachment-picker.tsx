import { Link2, Paperclip, Search, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  agentApi,
  type AgentAttachment,
  type AttachableItemWire,
} from "../../api/agent";
import { Button } from "../../components/ui/button";
import { CenteredModal } from "../../components/ui/centered-modal";
import { FilePicker } from "../files/file-picker";

interface AttachmentPickerProps {
  sessionId: string;
  selected: AgentAttachment[];
  disabled?: boolean;
  onSelect: (attachments: AgentAttachment[]) => void;
  onError: (message: string) => void;
}

function attachmentIcon(kind: AgentAttachment["kind"]): string {
  const labels: Record<AgentAttachment["kind"], string> = {
    event: "日程",
    todo: "待办",
    reminder: "提醒",
    image: "图片",
    file: "文件",
    workflow: "规则",
    "text-reference": "引用",
    unknown: "附件",
  };
  return labels[kind];
}

export function AttachmentChips({
  attachments,
  onRemove,
  removable = true,
}: {
  attachments: AgentAttachment[];
  onRemove?: (id: string) => void;
  /** Historical attachments are informative only and must not look removable. */
  removable?: boolean;
}) {
  if (!attachments.length) return null;
  return (
    <div className="agent-attachment-chips" aria-label="待发送附件">
      {attachments.map((attachment) => (
        <span className="agent-attachment-chip" key={attachment.id}>
          <span>
            {attachmentIcon(attachment.kind)} · {attachment.label}
          </span>
          {removable && onRemove ? (
            <button
              aria-label={`移除附件 ${attachment.label}`}
              onClick={() => onRemove(attachment.id)}
              type="button"
            >
              <X aria-hidden="true" size={14} />
            </button>
          ) : null}
        </span>
      ))}
    </div>
  );
}

export function AttachmentPicker({
  sessionId,
  selected,
  disabled = false,
  onSelect,
  onError,
}: AttachmentPickerProps) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"internal" | "cloud" | "upload">("internal");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<AttachableItemWire[]>([]);
  const [loading, setLoading] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open || tab !== "internal") return;
    const controller = new AbortController();
    const request = agentApi
      .listAttachable(undefined, query, controller.signal)
      .then((result) => setItems(result.items));
    void request
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          onError(error instanceof Error ? error.message : "加载附件失败。");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [onError, open, query, tab]);

  const addInternal = async (item: AttachableItemWire) => {
    setLoading(true);
    try {
      const response = await agentApi.attachInternal(sessionId, item);
      onSelect([
        ...selected,
        {
          id: String(response.attachment.id),
          kind: item.type,
          label: response.attachment.filename ?? item.title,
          resourceId: item.id,
          occurrenceRef: item.occurrence_ref ?? null,
          previewUrl: null,
          preview: response.attachment.preview ?? null,
          parseStatus: response.attachment.parse_status ?? null,
          isAvailable: true,
        },
      ]);
      setOpen(false);
    } catch (error) {
      onError(error instanceof Error ? error.message : "添加内部附件失败。");
    } finally {
      setLoading(false);
    }
  };
  const addCloud = async (
    files: Array<{
      id: number;
      filename: string;
      category: string;
      parseStatus: string;
    }>,
  ) => {
    setLoading(true);
    try {
      const response = await agentApi.attachCloudFiles(
        sessionId,
        files.map((file) => file.id),
      );
      if (response.attachments.length !== files.length)
        throw new Error("部分云盘文件已删除或无权限，请重新选择。");
      onSelect([
        ...selected,
        ...response.attachments.map((created, index) => ({
          id: String(created.id),
          kind:
            files[index].category === "image"
              ? ("image" as const)
              : ("file" as const),
          label: created.filename ?? files[index].filename,
          resourceId: String(files[index].id),
          occurrenceRef: null,
          previewUrl: null,
          preview: null,
          parseStatus: created.parse_status ?? files[index].parseStatus,
          isAvailable: true,
        })),
      ]);
      setOpen(false);
    } catch (error) {
      onError(error instanceof Error ? error.message : "从云盘添加附件失败。");
    } finally {
      setLoading(false);
    }
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setLoading(true);
    try {
      const uploaded: AgentAttachment[] = [];
      for (const file of Array.from(files)) {
        const response = await agentApi.uploadAttachment(sessionId, file);
        uploaded.push({
          id: String(response.attachment.id),
          kind: response.attachment.type === "image" ? "image" : "file",
          label: response.attachment.filename ?? file.name,
          resourceId: null,
          occurrenceRef: null,
          previewUrl: null,
          preview: null,
          parseStatus: response.attachment.parse_status ?? "pending",
          isAvailable: true,
        });
      }
      onSelect([...selected, ...uploaded]);
      setOpen(false);
      if (input.current) input.current.value = "";
    } catch (error) {
      onError(error instanceof Error ? error.message : "上传附件失败。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Button
        aria-label="添加附件"
        disabled={disabled}
        variant="ghost"
        onClick={() => {
          setLoading(true);
          setOpen(true);
        }}
      >
        <Paperclip aria-hidden="true" size={18} />
      </Button>
      <CenteredModal
        open={open}
        onOpenChange={(value) => {
          if (value) setLoading(true);
          setOpen(value);
        }}
        title="添加 Agent 附件"
        description="关联系统中的内容，或上传一份新文件。"
        size="lg"
      >
        <div className="agent-picker-tabs" role="tablist">
          <Button
            aria-selected={tab === "internal"}
            onClick={() => {
              setLoading(true);
              setTab("internal");
            }}
          >
            系统内容
          </Button>
          <Button
            aria-selected={tab === "cloud"}
            onClick={() => {
              setLoading(true);
              setTab("cloud");
            }}
          >
            我的文件
          </Button>
          <Button
            aria-selected={tab === "upload"}
            onClick={() => {
              setLoading(false);
              setTab("upload");
            }}
          >
            从设备上传
          </Button>
        </div>
        {tab === "internal" ? (
          <label className="agent-picker-search">
            <Search aria-hidden="true" size={16} />
            <input
              autoFocus
              value={query}
              onChange={(event) => {
                setLoading(true);
                setQuery(event.target.value);
              }}
              placeholder="搜索可附加内容"
            />
          </label>
        ) : null}
        {loading ? (
          <p className="text-sm text-[var(--text-muted)]">正在加载…</p>
        ) : null}
        {tab === "internal" ? (
          <div className="agent-picker-results">
            {items.map((item) => (
              <button
                disabled={disabled}
                key={`${item.type}-${item.id}`}
                onClick={() => void addInternal(item)}
                type="button"
              >
                <Link2 aria-hidden="true" size={16} />
                <span>
                  <strong>{item.title}</strong>
                  <small>
                    {item.type} {item.subtitle ? `· ${item.subtitle}` : ""}
                  </small>
                </span>
              </button>
            ))}
          </div>
        ) : null}
        {tab === "cloud" ? (
          <div className="mt-4">
            <FilePicker
              disabled={disabled}
              onConfirm={addCloud}
              trigger={<Button>打开云盘文件选择器</Button>}
            />
          </div>
        ) : null}
        {tab === "upload" ? (
          <div
            className="agent-upload-zone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              void upload(event.dataTransfer.files);
            }}
          >
            <Upload aria-hidden="true" size={28} />
            <strong>拖入文件到这里</strong>
            <p>支持文档、图片和常见文本格式</p>
            <input
              hidden
              ref={input}
              aria-label="上传本地附件"
              multiple
              onChange={(event) => void upload(event.target.files)}
              type="file"
            />
            <Button onClick={() => input.current?.click()} variant="primary">
              选择文件
            </Button>
          </div>
        ) : null}
      </CenteredModal>
    </>
  );
}

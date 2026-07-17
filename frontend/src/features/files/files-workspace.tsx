import {
  Download,
  FilePenLine,
  FilePlus2,
  FolderOpen,
  FolderPlus,
  Image,
  LayoutGrid,
  List,
  Link,
  MoreHorizontal,
  Move,
  Pencil,
  Trash2,
  Upload,
  Search,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { filesApi, mapFileRecord, type FileRecord } from "../../api/files";
import { fileKeys } from "../../api/queryKeys";
import { Button } from "../../components/ui/button";
import { CenteredModal } from "../../components/ui/centered-modal";
import { ConfirmDialog, TextInputDialog } from "../../components/ui/dialog";
import { DropdownMenu, DropdownMenuItem } from "../../components/ui/overlays";
import { Sheet } from "../../components/ui/sheet";

function formatSize(value: number): string {
  return value < 1024
    ? `${value} B`
    : value < 1_048_576
      ? `${(value / 1024).toFixed(1)} KB`
      : `${(value / 1_048_576).toFixed(1)} MB`;
}

function isPreviewable(file: FileRecord): boolean {
  return (
    file.category === "image" ||
    file.category === "text" ||
    file.category === "document"
  );
}

function FileMoveSheet({
  file,
  onClose,
  onConfirm,
}: {
  file: FileRecord | null;
  onClose: () => void;
  onConfirm: (folderId: number | null) => void | Promise<void>;
}) {
  const [folderId, setFolderId] = useState<number | null>(
    file?.folderId ?? null,
  );
  const listing = useQuery({
    enabled: file !== null,
    queryKey: ["files", "move-target", folderId],
    queryFn: ({ signal }) => filesApi.list(folderId, signal),
  });
  return (
    <CenteredModal
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      open={file !== null}
      title={`移动 ${file?.filename ?? "文件"}`}
      size="md"
    >
      <p className="text-sm text-[var(--text-muted)]">
        选择目标目录后确认；不会复制文件。
      </p>
      <nav aria-label="移动目标路径" className="file-breadcrumb">
        {listing.data?.breadcrumb.map((item) => (
          <Button
            key={String(item.id)}
            onClick={() => setFolderId(item.id)}
            variant="ghost"
          >
            {item.name}
          </Button>
        ))}
      </nav>
      <div className="file-picker-results">
        {listing.data?.folders.map((folder) => (
          <Button
            key={folder.id}
            onClick={() => setFolderId(folder.id)}
            variant="secondary"
          >
            <FolderOpen aria-hidden="true" size={16} /> {folder.name}
          </Button>
        ))}
      </div>
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>取消</Button>
        <Button onClick={() => void onConfirm(folderId)} variant="primary">
          移动到此处
        </Button>
      </div>
    </CenteredModal>
  );
}

function MarkdownPreview({
  file,
  onSaved,
  onError,
}: {
  file: FileRecord;
  onSaved: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const markdown = useQuery({
    queryKey: ["files", "markdown", file.id],
    queryFn: () => filesApi.getMarkdown(file.id),
  });
  if (markdown.isLoading) return <p>正在加载 Markdown…</p>;
  if (markdown.isError || !markdown.data)
    return (
      <p className="agent-error">
        此文件尚无可编辑的 Markdown 内容；可下载原文件查看。
      </p>
    );
  return (
    <MarkdownEditor
      key={`${file.id}-${markdown.data.markdown_edited}`}
      file={file}
      initialValue={markdown.data.parsed_markdown ?? ""}
      onError={onError}
      onSaved={onSaved}
    />
  );
}

function MarkdownEditor({
  file,
  initialValue,
  onSaved,
  onError,
}: {
  file: FileRecord;
  initialValue: string;
  onSaved: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [content, setContent] = useState(initialValue);
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await filesApi.saveMarkdown(file.id, content);
      await onSaved();
    } catch (error) {
      onError(error);
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <label className="file-markdown-editor">
        Markdown 内容
        <textarea
          aria-label="Markdown 内容"
          onChange={(event) => setContent(event.target.value)}
          value={content}
        />
      </label>
      <div className="flex justify-end gap-2">
        <Button
          onClick={() =>
            window.open(
              filesApi.downloadUrl(file.id, true),
              "_blank",
              "noopener",
            )
          }
        >
          下载 Markdown
        </Button>
        <Button disabled={saving} onClick={() => void save()} variant="primary">
          保存 Markdown
        </Button>
      </div>
    </>
  );
}

export function FilesWorkspace({
  embedded = false,
}: { embedded?: boolean } = {}) {
  const client = useQueryClient();
  const [folderId, setFolderId] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<FileRecord | null>(null);
  const [pendingFolderDelete, setPendingFolderDelete] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [renameFile, setRenameFile] = useState<FileRecord | null>(null);
  const [renameFolder, setRenameFolder] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [moveFile, setMoveFile] = useState<FileRecord | null>(null);
  const [previewFile, setPreviewFile] = useState<FileRecord | null>(null);
  const [urlDialog, setUrlDialog] = useState(false);
  const [message, setMessage] = useState("");
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"grid" | "list">(() =>
    window.localStorage.getItem("unischedulersuper-files-view") === "list"
      ? "list"
      : "grid",
  );
  const input = useRef<HTMLInputElement>(null);
  const listing = useQuery({
    queryKey: fileKeys.list(folderId),
    queryFn: ({ signal }) => filesApi.list(folderId, signal),
  });
  const rootListing = useQuery({
    enabled: folderId !== null,
    queryKey: fileKeys.list(null),
    queryFn: ({ signal }) => filesApi.list(null, signal),
  });
  const refresh = () => client.invalidateQueries({ queryKey: fileKeys.all });
  const showError = (error: unknown, fallback: string) =>
    setMessage(error instanceof Error ? error.message : fallback);
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    try {
      await filesApi.upload(Array.from(files), folderId);
      await refresh();
      setMessage("文件已上传。 ");
      if (input.current) input.current.value = "";
    } catch (error) {
      showError(error, "上传失败。 ");
    }
  };
  const createFolder = async () => {
    const value = name.trim();
    if (!value) return;
    try {
      await filesApi.createFolder(value, folderId);
      setName("");
      await refresh();
      setMessage("文件夹已创建。 ");
    } catch (error) {
      showError(error, "创建文件夹失败。 ");
    }
  };
  const files = (listing.data?.files ?? []).map(mapFileRecord);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleFolders = (listing.data?.folders ?? []).filter(
    (folder) =>
      !normalizedQuery ||
      folder.name.toLocaleLowerCase().includes(normalizedQuery),
  );
  const visibleFiles = files.filter(
    (file) =>
      !normalizedQuery ||
      file.filename.toLocaleLowerCase().includes(normalizedQuery),
  );
  const rootFolders =
    folderId === null
      ? (listing.data?.folders ?? [])
      : (rootListing.data?.folders ?? []);
  return (
    <section
      aria-labelledby="files-title"
      className={`files-workspace${embedded ? " files-workspace--embedded" : ""}`}
    >
      <header>
        <div>
          <h1 id="files-title">文件管理</h1>
          <nav aria-label="文件路径" className="file-breadcrumb">
            {listing.data?.breadcrumb.map((item) => (
              <Button
                key={String(item.id)}
                onClick={() => setFolderId(item.id)}
                variant="ghost"
              >
                {item.name}
              </Button>
            ))}
          </nav>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setUrlDialog(true)} variant="secondary">
            <Link aria-hidden="true" size={16} /> URL 上传
          </Button>
          <Button onClick={() => input.current?.click()} variant="primary">
            <Upload aria-hidden="true" size={16} /> 上传
          </Button>
          <input
            hidden
            multiple
            onChange={(event) => void upload(event.target.files)}
            ref={input}
            type="file"
          />
        </div>
      </header>
      <div className="files-layout">
        <aside aria-label="文件夹树" className="files-tree">
          <strong>文件夹</strong>
          <Button
            aria-current={folderId === null ? "page" : undefined}
            onClick={() => setFolderId(null)}
            variant="ghost"
          >
            <FolderOpen size={16} /> 根目录
          </Button>
          {rootFolders.map((folder) => (
            <Button
              aria-current={folderId === folder.id ? "page" : undefined}
              key={folder.id}
              onClick={() => setFolderId(folder.id)}
              variant="ghost"
            >
              <FolderOpen size={16} /> {folder.name}
              <small>{folder.file_count}</small>
            </Button>
          ))}
          <p>
            存储空间
            <br />
            <strong>
              {formatSize(
                listing.data?.quota.used_bytes ??
                  rootListing.data?.quota.used_bytes ??
                  0,
              )}
            </strong>{" "}
            /{" "}
            {formatSize(
              listing.data?.quota.max_storage_bytes ??
                rootListing.data?.quota.max_storage_bytes ??
                0,
            )}
          </p>
        </aside>
        <div className="files-content">
          <div className="files-toolbar">
            <label className="files-search">
              <Search aria-hidden="true" size={16} />
              <input
                aria-label="搜索当前文件夹"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索当前文件夹"
                value={query}
              />
            </label>
            <input
              aria-label="新文件夹名称"
              onChange={(event) => setName(event.target.value)}
              placeholder="新文件夹名称"
              value={name}
            />
            <Button disabled={!name.trim()} onClick={() => void createFolder()}>
              <FolderPlus aria-hidden="true" size={16} /> 创建文件夹
            </Button>
            <span>
              已用 {formatSize(listing.data?.quota.used_bytes ?? 0)} /{" "}
              {formatSize(listing.data?.quota.max_storage_bytes ?? 0)}
            </span>
            <div className="files-view-toggle" aria-label="文件视图">
              <Button
                aria-pressed={view === "grid"}
                onClick={() => {
                  setView("grid");
                  window.localStorage.setItem(
                    "unischedulersuper-files-view",
                    "grid",
                  );
                }}
                variant="ghost"
              >
                <LayoutGrid size={16} /> 网格
              </Button>
              <Button
                aria-pressed={view === "list"}
                onClick={() => {
                  setView("list");
                  window.localStorage.setItem(
                    "unischedulersuper-files-view",
                    "list",
                  );
                }}
                variant="ghost"
              >
                <List size={16} /> 列表
              </Button>
            </div>
          </div>
          <div
            className={`files-grid files-grid--${view}`}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              void upload(event.dataTransfer.files);
            }}
          >
            {visibleFolders.map((folder) => (
              <article className="file-card file-card--folder" key={folder.id}>
                <button
                  aria-label={`打开文件夹 ${folder.name}`}
                  className="file-card__open"
                  onClick={() => setFolderId(folder.id)}
                  type="button"
                >
                  <FilePlus2 aria-hidden="true" size={22} />
                  <strong>{folder.name}</strong>
                  <small>{folder.file_count} 个文件</small>
                </button>
                <DropdownMenu
                  trigger={
                    <Button
                      aria-label={`文件夹操作 ${folder.name}`}
                      variant="ghost"
                    >
                      <MoreHorizontal aria-hidden="true" size={16} />
                    </Button>
                  }
                >
                  <DropdownMenuItem
                    className="menu-item"
                    onSelect={() => setRenameFolder(folder)}
                  >
                    <Pencil size={15} /> 重命名
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="menu-item"
                    onSelect={() => setPendingFolderDelete(folder)}
                  >
                    <Trash2 size={15} /> 删除
                  </DropdownMenuItem>
                </DropdownMenu>
              </article>
            ))}
            {visibleFiles.map((file) => (
              <article className="file-card" key={file.id}>
                <button
                  aria-label={`预览文件 ${file.filename}`}
                  className="file-card__open"
                  disabled={!isPreviewable(file)}
                  onClick={() => setPreviewFile(file)}
                  type="button"
                >
                  {file.category === "image" ? (
                    <Image aria-hidden="true" size={22} />
                  ) : (
                    <FilePenLine aria-hidden="true" size={22} />
                  )}
                  <strong>{file.filename}</strong>
                  <small>
                    {file.category} · {formatSize(file.fileSize)} ·{" "}
                    {file.parseStatus}
                  </small>
                </button>
                <DropdownMenu
                  trigger={
                    <Button
                      aria-label={`文件操作 ${file.filename}`}
                      variant="ghost"
                    >
                      <MoreHorizontal aria-hidden="true" size={16} />
                    </Button>
                  }
                >
                  {isPreviewable(file) ? (
                    <DropdownMenuItem
                      className="menu-item"
                      onSelect={() => setPreviewFile(file)}
                    >
                      <FilePenLine size={15} /> 预览 / 编辑
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuItem
                    className="menu-item"
                    onSelect={() =>
                      window.open(
                        filesApi.downloadUrl(file.id),
                        "_blank",
                        "noopener",
                      )
                    }
                  >
                    <Download size={15} /> 下载
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="menu-item"
                    onSelect={() => setRenameFile(file)}
                  >
                    <Pencil size={15} /> 重命名
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="menu-item"
                    onSelect={() => setMoveFile(file)}
                  >
                    <Move size={15} /> 移动
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="menu-item"
                    onSelect={() => setPendingDelete(file)}
                  >
                    <Trash2 size={15} /> 删除
                  </DropdownMenuItem>
                </DropdownMenu>
              </article>
            ))}
          </div>
          {listing.isLoading ? <p>正在加载文件…</p> : null}
          {!listing.isLoading &&
          !visibleFolders.length &&
          !visibleFiles.length ? (
            <p className="empty-state">
              {normalizedQuery
                ? "没有匹配的文件或文件夹。"
                : "当前文件夹为空。可拖入文件或创建文件夹。"}
            </p>
          ) : null}
          {message ? (
            <p aria-live="polite" className="agent-status">
              {message}
            </p>
          ) : null}
        </div>
      </div>
      <ConfirmDialog
        confirmLabel="删除"
        description={`删除 ${pendingDelete?.filename ?? "文件"} 后，不能再作为附件发送。`}
        onConfirm={() =>
          void (async () => {
            if (!pendingDelete) return;
            try {
              await filesApi.remove(pendingDelete.id);
              await refresh();
              setPendingDelete(null);
            } catch (error) {
              showError(error, "删除失败。 ");
            }
          })()
        }
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        open={pendingDelete !== null}
        title="删除文件？"
      />
      <ConfirmDialog
        confirmLabel="删除文件夹"
        description={`仅可删除空文件夹：${pendingFolderDelete?.name ?? ""}。`}
        onConfirm={() =>
          void (async () => {
            if (!pendingFolderDelete) return;
            try {
              await filesApi.removeFolder(pendingFolderDelete.id);
              await refresh();
              setPendingFolderDelete(null);
            } catch (error) {
              showError(error, "删除文件夹失败。 ");
            }
          })()
        }
        onOpenChange={(open) => {
          if (!open) setPendingFolderDelete(null);
        }}
        open={pendingFolderDelete !== null}
        title="删除文件夹？"
      />
      <TextInputDialog
        confirmLabel="保存"
        description="只修改名称，不改变文件内容或路径。"
        initialValue={renameFile?.filename ?? ""}
        label="文件名"
        onConfirm={(value) =>
          void (async () => {
            if (!renameFile) return;
            try {
              await filesApi.rename(renameFile.id, value);
              await refresh();
              setRenameFile(null);
            } catch (error) {
              showError(error, "重命名失败。 ");
            }
          })()
        }
        onOpenChange={(open) => {
          if (!open) setRenameFile(null);
        }}
        open={renameFile !== null}
        title="重命名文件"
      />
      <TextInputDialog
        confirmLabel="保存"
        description="只修改目录名称，不移动其中的文件。"
        initialValue={renameFolder?.name ?? ""}
        label="文件夹名称"
        onConfirm={(value) =>
          void (async () => {
            if (!renameFolder) return;
            try {
              await filesApi.renameFolder(renameFolder.id, value);
              await refresh();
              setRenameFolder(null);
            } catch (error) {
              showError(error, "重命名文件夹失败。 ");
            }
          })()
        }
        onOpenChange={(open) => {
          if (!open) setRenameFolder(null);
        }}
        open={renameFolder !== null}
        title="重命名文件夹"
      />
      <TextInputDialog
        confirmLabel="上传"
        description="仅允许后端白名单支持的公开文件 URL；内网与危险重定向会由服务端拒绝。"
        initialValue=""
        label="文件 URL"
        onConfirm={(url) =>
          void (async () => {
            try {
              await filesApi.uploadUrl(url, folderId);
              await refresh();
              setUrlDialog(false);
              setMessage("URL 文件已上传。 ");
            } catch (error) {
              showError(error, "URL 上传失败。 ");
            }
          })()
        }
        onOpenChange={setUrlDialog}
        open={urlDialog}
        title="从 URL 上传文件"
      />
      <FileMoveSheet
        key={moveFile?.id ?? "no-file"}
        file={moveFile}
        onClose={() => setMoveFile(null)}
        onConfirm={(target) =>
          void (async () => {
            if (!moveFile) return;
            try {
              await filesApi.move(moveFile.id, target);
              await refresh();
              setMoveFile(null);
              setMessage("文件已移动。 ");
            } catch (error) {
              showError(error, "移动失败。 ");
            }
          })()
        }
      />
      <Sheet
        onOpenChange={(open) => {
          if (!open) setPreviewFile(null);
        }}
        open={previewFile !== null}
        title={`预览 ${previewFile?.filename ?? "文件"}`}
      >
        {previewFile?.category === "image" && previewFile.fileUrl ? (
          <img
            alt={previewFile.filename}
            className="file-preview-image"
            src={previewFile.fileUrl}
          />
        ) : null}
        {previewFile && previewFile.category !== "image" ? (
          <MarkdownPreview
            file={previewFile}
            onError={(error) => showError(error, "保存 Markdown 失败。 ")}
            onSaved={async () => {
              setMessage("Markdown 已保存。 ");
              await refresh();
            }}
          />
        ) : null}
      </Sheet>
    </section>
  );
}

import { FileText, FolderOpen, Search } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { filesApi, mapFileRecord, type FileRecord } from "../../api/files";
import { Button } from "../../components/ui/button";
import { Sheet } from "../../components/ui/sheet";

export function FilePicker({
  trigger,
  multiple = true,
  disabled = false,
  onConfirm,
}: {
  trigger: ReactNode;
  multiple?: boolean;
  disabled?: boolean;
  onConfirm: (files: FileRecord[]) => void | Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [folderId, setFolderId] = useState<number | null>(null);
  const [folders, setFolders] = useState<Array<{ id: number; name: string }>>(
    [],
  );
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void filesApi
        .pick({ query, folderId }, controller.signal)
        .then((response) => {
          if (!controller.signal.aborted) {
            setFiles(response.files.map(mapFileRecord));
            setFolders(response.folders);
            setMessage("");
          }
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted)
            setMessage(
              error instanceof Error ? error.message : "无法加载文件。 ",
            );
        });
    }, 180);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [folderId, open, query]);
  const confirm = async () => {
    const picked = files.filter((file) => selected.has(file.id));
    if (!picked.length) {
      setMessage("请选择至少一个文件。 ");
      return;
    }
    await onConfirm(picked);
    setOpen(false);
    setSelected(new Set());
  };
  const openPicker = () => {
    if (disabled) return;
    setQuery("");
    setFolderId(null);
    setSelected(new Set());
    setOpen(true);
  };
  return (
    <>
      <span onClick={openPicker}>{trigger}</span>
      <Sheet open={open} onOpenChange={setOpen} title="选择云盘文件">
        <label className="agent-picker-search">
          <Search aria-hidden="true" size={16} />
          <input
            aria-label="搜索云盘文件"
            autoFocus
            onChange={(event) => setQuery(event.target.value)}
            placeholder="按文件名搜索"
            value={query}
          />
        </label>
        <div aria-label="云盘文件夹" className="file-picker-folders">
          {folderId !== null ? (
            <Button onClick={() => setFolderId(null)} variant="ghost">
              返回根目录
            </Button>
          ) : null}
          {folders.map((folder) => (
            <Button
              key={folder.id}
              onClick={() => setFolderId(folder.id)}
              variant="secondary"
            >
              <FolderOpen aria-hidden="true" size={16} /> {folder.name}
            </Button>
          ))}
        </div>
        <div className="file-picker-results">
          {files.map((file) => (
            <label key={file.id}>
              <input
                checked={selected.has(file.id)}
                onChange={() =>
                  setSelected((values) => {
                    const next = multiple ? new Set(values) : new Set<number>();
                    if (next.has(file.id)) next.delete(file.id);
                    else next.add(file.id);
                    return next;
                  })
                }
                type={multiple ? "checkbox" : "radio"}
              />
              <FileText aria-hidden="true" size={16} />
              <span>
                <strong>{file.filename}</strong>
                <small>
                  {file.category} · {file.parseStatus}
                </small>
              </span>
            </label>
          ))}
        </div>
        {message ? <p className="agent-error">{message}</p> : null}
        <Button onClick={() => void confirm()} variant="primary">
          选择文件
        </Button>
      </Sheet>
    </>
  );
}

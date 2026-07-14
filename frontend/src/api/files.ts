import { apiClient, type JsonObject } from "./http";

export interface FileListWire {
  current_folder: { id: number | null; name: string; path: string };
  breadcrumb: Array<{ id: number | null; name: string; path: string }>;
  folders: Array<{
    id: number;
    name: string;
    path: string;
    file_count: number;
  }>;
  files: JsonObject[];
  quota: {
    used_bytes: number;
    max_storage_bytes: number;
    usage_percent: number;
    file_count: number;
  };
}

export interface FileRecord {
  id: number;
  filename: string;
  fileSize: number;
  mimeType: string;
  category: string;
  folderId: number | null;
  parseStatus: string;
  fileUrl: string | null;
}

export function mapFileRecord(value: unknown): FileRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new Error("文件响应必须是对象。");
  const wire = value as JsonObject;
  if (!Number.isInteger(wire.id) || typeof wire.filename !== "string")
    throw new Error("文件响应缺少 id 或 filename。");
  return {
    id: wire.id as number,
    filename: wire.filename,
    fileSize: typeof wire.file_size === "number" ? wire.file_size : 0,
    mimeType:
      typeof wire.mime_type === "string"
        ? wire.mime_type
        : "application/octet-stream",
    category: typeof wire.category === "string" ? wire.category : "unknown",
    folderId: Number.isInteger(wire.folder_id)
      ? (wire.folder_id as number)
      : null,
    parseStatus:
      typeof wire.parse_status === "string" ? wire.parse_status : "unknown",
    fileUrl: typeof wire.file_url === "string" ? wire.file_url : null,
  };
}

export const filesApi = {
  list: (folderId?: number, signal?: AbortSignal) => {
    const query = folderId
      ? `?${new URLSearchParams({ folder_id: String(folderId) })}`
      : "";
    return apiClient.request<FileListWire>(`/api/files/${query}`, { signal });
  },
  get: (fileId: number, signal?: AbortSignal) =>
    apiClient.request<JsonObject>(`/api/files/${fileId}/`, { signal }),
  upload: (files: File[], folderId?: number) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    if (folderId) form.append("folder_id", String(folderId));
    return apiClient.request<JsonObject>("/api/files/upload/", {
      method: "POST",
      body: form,
    });
  },
};

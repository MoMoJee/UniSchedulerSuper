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
  textPreview: string | null;
}

export interface FileFolder {
  id: number;
  name: string;
  path: string;
  parentId?: number | null;
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
    textPreview:
      typeof wire.text_preview === "string" ? wire.text_preview : null,
  };
}

export const filesApi = {
  list: (folderId?: number | null, signal?: AbortSignal) => {
    const query = folderId
      ? `?${new URLSearchParams({ folder_id: String(folderId) })}`
      : "";
    return apiClient.request<FileListWire>(`/api/files/${query}`, { signal });
  },
  get: (fileId: number, signal?: AbortSignal) =>
    apiClient.request<JsonObject>(`/api/files/${fileId}/`, { signal }),
  upload: (files: File[], folderId?: number | null) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    if (folderId) body.append("folder_id", String(folderId));
    return apiClient.request<JsonObject>("/api/files/upload/", {
      method: "POST",
      body,
    });
  },
  uploadUrl: (url: string, folderId?: number | null) =>
    apiClient.request<JsonObject>("/api/files/upload-url/", {
      method: "POST",
      body: { url, ...(folderId ? { folder_id: folderId } : {}) },
    }),
  remove: (fileId: number) =>
    apiClient.request<JsonObject>(`/api/files/${fileId}/`, {
      method: "DELETE",
    }),
  rename: (fileId: number, filename: string) =>
    apiClient.request<JsonObject>(`/api/files/${fileId}/rename/`, {
      method: "PUT",
      body: { filename },
    }),
  move: (fileId: number, folderId: number | null) =>
    apiClient.request<JsonObject>(`/api/files/${fileId}/move/`, {
      method: "PUT",
      body: { folder_id: folderId },
    }),
  createFolder: (name: string, parentId: number | null) =>
    apiClient.request<JsonObject>("/api/files/folders/", {
      method: "POST",
      body: { name, parent_id: parentId },
    }),
  renameFolder: (folderId: number, name: string) =>
    apiClient.request<JsonObject>(`/api/files/folders/${folderId}/rename/`, {
      method: "PUT",
      body: { name },
    }),
  removeFolder: (folderId: number) =>
    apiClient.request<JsonObject>(`/api/files/folders/${folderId}/`, {
      method: "DELETE",
    }),
  search: (query: string, signal?: AbortSignal) =>
    apiClient.request<{ results: JsonObject[] }>(
      `/api/files/search/?${new URLSearchParams({ q: query })}`,
      { signal },
    ),
  pick: (
    params: {
      query?: string;
      category?: string;
      folderId?: number | null;
    } = {},
    signal?: AbortSignal,
  ) =>
    apiClient.request<{ folders: FileFolder[]; files: JsonObject[] }>(
      `/api/files/pick/?${new URLSearchParams({ ...(params.query ? { q: params.query } : {}), ...(params.category ? { category: params.category } : {}), ...(params.folderId ? { folder_id: String(params.folderId) } : {}) })}`,
      { signal },
    ),
  getMarkdown: (fileId: number) =>
    apiClient.request<{
      id: number;
      filename: string;
      parsed_markdown: string;
      markdown_edited: boolean;
      parse_status: string;
    }>(`/api/files/${fileId}/markdown/`),
  saveMarkdown: (fileId: number, content: string) =>
    apiClient.request<JsonObject>(`/api/files/${fileId}/markdown/`, {
      method: "PUT",
      body: { content },
    }),
  downloadUrl: (fileId: number, markdown = false) =>
    `/api/files/${fileId}/${markdown ? "download-md" : "download"}/`,
};

import { readFrontendBootstrap } from "../bootstrap";
import { ApiError } from "./errors";

export type JsonObject = Record<string, unknown>;

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: JsonObject | FormData;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `frontend-${Date.now()}`;
}

function getCsrfToken(): string {
  return readFrontendBootstrap().csrfToken;
}

async function readResponseBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null;
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json() as Promise<unknown>;
  }
  return response.text();
}

function errorParts(body: unknown): {
  message: string;
  code: string | null;
  details: JsonObject | null;
} {
  if (typeof body === "object" && body !== null && !Array.isArray(body)) {
    const record = body as JsonObject;
    return {
      message:
        typeof record.error === "string"
          ? record.error
          : typeof record.message === "string"
            ? record.message
            : "请求失败。",
      code: typeof record.code === "string" ? record.code : null,
      details: record,
    };
  }
  return {
    message: typeof body === "string" && body ? body : "请求失败。",
    code: null,
    details: null,
  };
}

export class ApiClient {
  async request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    if (!path.startsWith("/")) {
      throw new Error(`API path 必须是同源绝对路径：${path}`);
    }
    const method = options.method ?? "GET";
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    headers.set("X-Request-ID", requestId());

    let body: BodyInit | undefined;
    if (options.body instanceof FormData) {
      body = options.body;
    } else if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.body);
    }
    if (method !== "GET") {
      headers.set("X-CSRFToken", getCsrfToken());
    }

    let response: Response;
    try {
      response = await fetch(path, {
        method,
        headers,
        body,
        signal: options.signal,
        credentials: "same-origin",
      });
    } catch (cause) {
      // Browsers and test transports do not all expose AbortError as the same
      // DOMException subclass. The caller-owned signal is the authoritative
      // cancellation source, so never convert its cancellation into a toast.
      if (
        options.signal?.aborted ||
        (cause instanceof DOMException && cause.name === "AbortError")
      ) {
        throw cause;
      }
      throw new ApiError({
        message: "网络连接失败，请检查网络后重试。",
        status: 0,
        code: "network_error",
        details: null,
        method,
        url: path,
      });
    }

    const payload = await readResponseBody(response);
    if (!response.ok) {
      const { message, code, details } = errorParts(payload);
      throw new ApiError({
        message,
        status: response.status,
        code,
        details,
        method,
        url: path,
      });
    }
    return payload as T;
  }
}

export const apiClient = new ApiClient();

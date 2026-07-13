export interface FrontendBootstrap {
  mode: "react";
  user: {
    username: string;
  };
  csrfToken: string;
  endpoints: {
    home: string;
    agentWebSocketPath: string;
  };
}

function isFrontendBootstrap(value: unknown): value is FrontendBootstrap {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<FrontendBootstrap>;
  return (
    candidate.mode === "react" &&
    typeof candidate.csrfToken === "string" &&
    typeof candidate.user?.username === "string" &&
    typeof candidate.endpoints?.home === "string" &&
    typeof candidate.endpoints?.agentWebSocketPath === "string"
  );
}

export function readFrontendBootstrap(
  documentRef: Document = document,
): FrontendBootstrap {
  const element = documentRef.getElementById("frontend-bootstrap");
  if (!element?.textContent) {
    throw new Error("缺少前端启动配置，无法安全初始化新版界面。");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(element.textContent);
  } catch {
    throw new Error("前端启动配置不是有效 JSON。");
  }
  if (!isFrontendBootstrap(parsed)) {
    throw new Error("前端启动配置不完整或版本不兼容。");
  }
  return parsed;
}

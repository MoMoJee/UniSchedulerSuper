export type ApiErrorDetails = Record<string, unknown> | null;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: ApiErrorDetails;
  readonly method: string;
  readonly url: string;

  constructor({
    message,
    status,
    code,
    details,
    method,
    url,
  }: {
    message: string;
    status: number;
    code: string | null;
    details: ApiErrorDetails;
    method: string;
    url: string;
  }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.method = method;
    this.url = url;
  }
}

export class PlannerClientValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlannerClientValidationError";
  }
}

export function toUserFacingApiMessage(error: ApiError): string {
  switch (error.status) {
    case 401:
      return "登录已失效，请重新登录后重试。";
    case 403:
      return "你没有执行此操作的权限。";
    case 404:
      return "目标资源已不存在或无法访问。";
    case 409:
      return "数据已被其他操作更新，请刷新后确认再提交。";
    case 410:
      return "该接口或历史记录已封存，不能回退到旧接口。";
    case 422:
      return "输入内容不符合当前规则，请检查标记的字段。";
    case 423:
      return "当前资源已被隔离或锁定，无法修改。";
    default:
      return error.message || "请求失败，请稍后重试。";
  }
}

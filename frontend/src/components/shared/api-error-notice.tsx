import { CircleAlert } from "lucide-react";

import { ApiError, toUserFacingApiMessage } from "../../api/errors";
import { Button } from "../ui/button";

export function ApiErrorNotice({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const message =
    error instanceof ApiError
      ? toUserFacingApiMessage(error)
      : "出现未知错误，请稍后重试。";
  return (
    <section aria-live="polite" className="error-notice">
      <CircleAlert aria-hidden="true" size={20} />
      <p>{message}</p>
      {onRetry ? <Button onClick={onRetry}>重试</Button> : null}
    </section>
  );
}

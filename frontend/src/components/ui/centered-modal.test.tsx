import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { CenteredModal } from "./centered-modal";

describe("CenteredModal", () => {
  it("has dialog semantics and closes with Escape", async () => {
    const onOpenChange = vi.fn();
    render(
      <CenteredModal open onOpenChange={onOpenChange} title="编辑日程">
        <button>保存</button>
      </CenteredModal>,
    );
    expect(
      screen.getByRole("dialog", { name: "编辑日程" }),
    ).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("restores focus after a controlled close", () => {
    const trigger = createRef<HTMLButtonElement>();
    const { rerender } = render(
      <>
        <button ref={trigger}>打开</button>
        <CenteredModal
          open
          onOpenChange={() => undefined}
          restoreFocusRef={trigger}
          title="提醒"
        >
          <span>内容</span>
        </CenteredModal>
      </>,
    );
    rerender(
      <>
        <button ref={trigger}>打开</button>
        <CenteredModal
          open={false}
          onOpenChange={() => undefined}
          restoreFocusRef={trigger}
          title="提醒"
        >
          <span>内容</span>
        </CenteredModal>
      </>,
    );
    expect(trigger.current).toHaveFocus();
  });
});

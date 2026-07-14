import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";

import { Button } from "./button";
import { ConfirmDialog } from "./dialog";

function DialogHarness() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <Button onClick={() => setOpen(true)} ref={triggerRef}>
        删除项目
      </Button>
      <ConfirmDialog
        description="此操作不可撤销。"
        onConfirm={() => setOpen(false)}
        onOpenChange={setOpen}
        open={open}
        restoreFocusRef={triggerRef}
        title="确认删除"
      />
    </>
  );
}

describe("ConfirmDialog", () => {
  it("moves focus into the dialog and restores it after Escape", () => {
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "删除项目" });
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});

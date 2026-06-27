import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RollbackDialog from "./RollbackDialog";

describe("RollbackDialog", () => {
  it("requires a reason before confirming rollback", async () => {
    const onConfirm = vi.fn();
    const onReasonChange = vi.fn();
    render(
      <RollbackDialog
        reason=""
        canRollback
        isPending={false}
        onReasonChange={onReasonChange}
        onConfirm={onConfirm}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Roll back" }));

    expect(screen.getByRole("button", { name: "Confirm rollback" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason"), "Bad verifier output");
    expect(onReasonChange).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

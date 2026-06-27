import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ParameterPanel, RunModeTabs } from "./RunConsole";
import type { ObjectiveParameters } from "../types";

function params(): ObjectiveParameters {
  return {
    target: "ZN2+",
    ph: 5,
    functions: ["bind", "polymerize"],
    length: 60,
    seed_count: 5,
    seed_sources: ["ccdc_csd", "de_novo"],
    target_score: 0.8,
    loop_count: 2
  };
}

describe("ParameterPanel", () => {
  it("renders editable objective parameters and loop count constraints", () => {
    render(<ParameterPanel parameters={params()} onChange={vi.fn()} />);

    expect(screen.getByLabelText("Target")).toHaveValue("ZN2+");
    expect(screen.getByLabelText("pH")).toHaveValue(5);
    expect(screen.getByLabelText("Length")).toHaveValue(60);
    expect(screen.getByLabelText("Loops")).toHaveAttribute("min", "0");
  });

  it("allows choosing de novo only", async () => {
    const onChange = vi.fn();
    render(<ParameterPanel parameters={params()} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "De novo" }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ seed_sources: ["de_novo"] }));
  });

  it("switches run mode tabs", async () => {
    const onChange = vi.fn();
    render(<RunModeTabs value="seed_and_loop" onChange={onChange} />);

    await userEvent.click(screen.getByRole("tab", { name: "Seed only" }));

    expect(onChange).toHaveBeenCalledWith("seed_only");
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LoopGraph from "./LoopGraph";
import type { MemorySnapshot } from "../types";

function snapshot(): MemorySnapshot {
  return {
    run_id: "run_1",
    root_loop_id: "loop_0",
    active_loop_id: "loop_1",
    objective: { description: "test", goals: [], max_loops: 2, custom: {} },
    conditions: { parameters: {}, schema_version: "conditions.v0" },
    edges: [{ parent_loop_id: "loop_0", child_loop_id: "loop_1" }],
    seed_selection_decision: null,
    created_at: "2026-06-27T12:00:00Z",
    nodes: [
      {
        loop_id: "loop_0",
        parent_loop_id: null,
        index: 0,
        status: "available",
        is_active: false,
        can_branch_from: true,
        branch_label: null,
        sequence_length: 20,
        sequence_preview: "ACDE",
        change_summary: null,
        change_rationale: null,
        change_diffs: [],
        latest_metrics: {},
        evaluation_kinds: ["boltz", "screening", "verifier"],
        human_input_count: 0,
        human_inputs: [],
        reflection: { went_well: [], went_wrong: [], next_actions: [], notes: null },
        completeness: null,
        created_at: "2026-06-27T12:00:00Z"
      },
      {
        loop_id: "loop_1",
        parent_loop_id: "loop_0",
        index: 1,
        status: "active",
        is_active: true,
        can_branch_from: true,
        branch_label: null,
        sequence_length: 20,
        sequence_preview: "ACDF",
        change_summary: "Apply F4Y",
        change_rationale: "Improve binding.",
        change_diffs: ["F4Y"],
        latest_metrics: { verifier_score: 0.8 },
        evaluation_kinds: ["verifier"],
        human_input_count: 1,
        human_inputs: [{ author: "human", note: "Rollback selected this loop", requested_changes: [], created_at: "2026-06-27T12:02:00Z", metadata: { action: "rollback", actor: "human" } }],
        reflection: { went_well: [], went_wrong: [], next_actions: [], notes: null },
        completeness: null,
        created_at: "2026-06-27T12:01:00Z"
      }
    ]
  };
}

describe("LoopGraph", () => {
  it("renders active and rollback loop badges", () => {
    render(<div style={{ width: 900, height: 500 }}><LoopGraph snapshot={snapshot()} selectedLoopId="loop_1" onSelectLoop={vi.fn()} /></div>);

    expect(screen.getAllByText("loop_1").length).toBeGreaterThan(0);
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Human rollback")).toBeInTheDocument();
  });
});

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Beaker, Loader2, Play, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { createRun, createRunEventSource, decodeEvent, parseObjective } from "../api";
import type { CreateRunPayload, GoalComparator, ObjectiveParameters, OptimizationTarget, RunMode, SeedSource, WorkbenchEvent } from "../types";
import EventFeed from "./EventFeed";

const DEFAULT_OBJECTIVE = "design a protein that binds Zn2+ at pH 5 and can polymerize";

export default function RunConsole() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [parameters, setParameters] = useState<ObjectiveParameters | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [events, setEvents] = useState<WorkbenchEvent[]>([]);
  const [runMode, setRunMode] = useState<RunMode>("seed_and_loop");

  const parseMutation = useMutation({
    mutationFn: parseObjective,
    onSuccess: setParameters
  });

  const runMutation = useMutation({
    mutationFn: createRun,
    onSuccess: (response) => {
      setRunId(response.run_id);
      setJobId(response.job_id);
      setEvents([]);
    }
  });

  useEffect(() => {
    if (!runId) return;
    const eventSource = createRunEventSource(runId);
    const append = (message: MessageEvent<string>) => {
      const event = decodeEvent(message);
      setEvents((current) => [...current, event]);
      if (event.event_type === "loop_finalized" || event.event_type === "rollback_recorded" || event.event_type === "evaluation_attached") {
        void queryClient.invalidateQueries({ queryKey: ["memory", runId] });
      }
    };
    for (const eventName of [
      "run_started",
      "loop_appended",
      "evaluation_attached",
      "reflection_written",
      "loop_finalized",
      "rollback_recorded",
      "run_finished",
      "run_failed",
      "human_input_recorded"
    ]) {
      eventSource.addEventListener(eventName, append as EventListener);
    }
    return () => eventSource.close();
  }, [queryClient, runId]);

  const canRun = parameters && objective.trim() && !runMutation.isPending;
  const latestStatus = useMemo(() => {
    const latest = events.at(-1);
    if (runMutation.isPending) return "starting";
    if (!latest) return jobId ? "queued" : "idle";
    if (latest.event_type === "run_finished") return "finished";
    if (latest.event_type === "run_failed") return "failed";
    return "running";
  }, [events, jobId, runMutation.isPending]);

  function submitRun(event: FormEvent) {
    event.preventDefault();
    if (!parameters) return;
    const optimizationTargets = parameters.optimization_targets.filter((target) => target.name.trim());
    const payload: CreateRunPayload = {
      objective,
      ...parameters,
      functions: parameters.functions.filter(Boolean),
      loop_count: runMode === "seed_only" ? 0 : parameters.loop_count,
      target_score: optimizationTargets.find((target) => target.name === "trs_total")?.target ?? parameters.target_score,
      optimization_targets: optimizationTargets,
      run_mode: runMode
    };
    runMutation.mutate(payload);
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <form onSubmit={submitRun} className="grid gap-4">
        <section className="rounded-lg border border-zinc-800 bg-zinc-900/70">
          <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <Beaker className="h-4 w-4 text-emerald-300" />
              <h1 className="text-sm font-semibold text-zinc-100">Novacore console</h1>
            </div>
            <StatusPill status={latestStatus} />
          </div>
          <div className="grid gap-4 p-4">
            <label className="grid gap-2">
              <span className="text-xs font-medium uppercase tracking-[0.12em] text-zinc-500">Objective</span>
              <textarea
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                className="min-h-28 resize-y rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-3 text-sm leading-6 text-zinc-100 outline-none transition focus:border-emerald-400"
              />
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => parseMutation.mutate(objective)}
                disabled={parseMutation.isPending || !objective.trim()}
                className="inline-flex h-9 items-center gap-2 rounded-lg bg-zinc-100 px-3 text-sm font-medium text-zinc-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {parseMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <SlidersHorizontal className="h-4 w-4" />}
                Extract parameters
              </button>
              <button
                type="submit"
                disabled={!canRun}
                className="inline-flex h-9 items-center gap-2 rounded-lg bg-emerald-400 px-3 text-sm font-medium text-zinc-950 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {runMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Start run
              </button>
              {runId ? (
                <button
                  type="button"
                  onClick={() => navigate(`/memory/${runId}`)}
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-700 px-3 text-sm font-medium text-zinc-100 transition hover:bg-zinc-800"
                >
                  Open memory
                  <ArrowRight className="h-4 w-4" />
                </button>
              ) : null}
            </div>
            {parseMutation.error || runMutation.error ? (
              <div role="alert" className="rounded-lg border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">
                {(parseMutation.error ?? runMutation.error)?.message}
              </div>
            ) : null}
          </div>
        </section>

        {parameters ? (
          <>
            <ParameterPanel parameters={parameters} onChange={setParameters} />
            <OptimizationTargetsPanel parameters={parameters} onChange={setParameters} />
            <RunModeTabs value={runMode} onChange={setRunMode} />
          </>
        ) : (
          <EmptyParameters />
        )}
      </form>

      <aside className="grid content-start gap-4">
        {runId ? (
          <section className="rounded-lg border border-zinc-800 bg-zinc-900/70 p-4">
            <div className="text-xs uppercase tracking-[0.12em] text-zinc-500">Active run</div>
            <div className="mt-2 break-all font-mono text-sm text-zinc-100">{runId}</div>
            <div className="mt-2 break-all font-mono text-xs text-zinc-500">{jobId}</div>
            <Link className="mt-4 inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-700 px-3 text-sm text-zinc-100 hover:bg-zinc-800" to={`/memory/${runId}`}>
              Memory page
              <ArrowRight className="h-4 w-4" />
            </Link>
          </section>
        ) : null}
        <EventFeed events={events} compact />
      </aside>
    </div>
  );
}

export function RunModeTabs({ value, onChange }: { value: RunMode; onChange: (value: RunMode) => void }) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/70">
      <div className="border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-100">Run mode</h2>
      </div>
      <Tabs.Root value={value} onValueChange={(next) => onChange(next as RunMode)} className="p-4">
        <Tabs.List className="grid max-w-md grid-cols-2 rounded-lg border border-zinc-700 bg-zinc-950 p-1">
          <Tabs.Trigger value="seed_and_loop" className="h-8 rounded-md px-2 text-xs font-medium text-zinc-400 transition data-[state=active]:bg-emerald-400 data-[state=active]:text-zinc-950">
            Novacore e2e
          </Tabs.Trigger>
          <Tabs.Trigger value="seed_only" className="h-8 rounded-md px-2 text-xs font-medium text-zinc-400 transition data-[state=active]:bg-emerald-400 data-[state=active]:text-zinc-950">
            Seed only
          </Tabs.Trigger>
        </Tabs.List>
      </Tabs.Root>
    </section>
  );
}

export function ParameterPanel({
  parameters,
  onChange
}: {
  parameters: ObjectiveParameters;
  onChange: (parameters: ObjectiveParameters) => void;
}) {
  function patch(update: Partial<ObjectiveParameters>) {
    onChange({ ...parameters, ...update });
  }
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/70">
      <div className="border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-100">Parameters</h2>
      </div>
      <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-4">
        <Field label="Target">
          <input value={parameters.target} onChange={(event) => patch({ target: event.target.value })} className="field-input" />
        </Field>
        <Field label="pH">
          <input type="number" step="0.1" value={parameters.ph} onChange={(event) => patch({ ph: Number(event.target.value) })} className="field-input" />
        </Field>
        <Field label="Length">
          <input type="number" min={1} value={parameters.length} onChange={(event) => patch({ length: Number(event.target.value) })} className="field-input" />
        </Field>
        <Field label="Functions">
          <input value={parameters.functions.join(", ")} onChange={(event) => patch({ functions: event.target.value.split(",").map((item) => item.trim()) })} className="field-input" />
        </Field>
        <Field label="Seed count">
          <input type="number" min={1} value={parameters.seed_count} onChange={(event) => patch({ seed_count: Number(event.target.value) })} className="field-input" />
        </Field>
        <Field label="Loops">
          <input type="number" min={0} value={parameters.loop_count} onChange={(event) => patch({ loop_count: Number(event.target.value) })} className="field-input" />
        </Field>
        <div className="grid gap-2">
          <span className="text-xs font-medium text-zinc-500">Seed source</span>
          <div className="grid grid-cols-3 rounded-lg border border-zinc-700 bg-zinc-950 p-1">
            <SeedButton sources={parameters.seed_sources} value="ccdc_csd" label="CCDC" onChange={(seed_sources) => patch({ seed_sources })} />
            <SeedButton sources={parameters.seed_sources} value="de_novo" label="De novo" onChange={(seed_sources) => patch({ seed_sources })} />
            <button
              type="button"
              onClick={() => patch({ seed_sources: ["ccdc_csd", "de_novo"] })}
              className={seedButtonClass(parameters.seed_sources.length === 2)}
            >
              Both
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

export function OptimizationTargetsPanel({
  parameters,
  onChange
}: {
  parameters: ObjectiveParameters;
  onChange: (parameters: ObjectiveParameters) => void;
}) {
  function patchTarget(index: number, update: Partial<OptimizationTarget>) {
    const next = parameters.optimization_targets.map((target, targetIndex) =>
      targetIndex === index ? { ...target, ...update } : target
    );
    onChange({ ...parameters, optimization_targets: next });
  }

  function addTarget() {
    onChange({
      ...parameters,
      optimization_targets: [
        ...parameters.optimization_targets,
        { name: "verifier_score", target: 0.8, comparator: "gte", weight: 1, description: "Future verifier MCP score." }
      ]
    });
  }

  function removeTarget(index: number) {
    onChange({
      ...parameters,
      optimization_targets: parameters.optimization_targets.filter((_, targetIndex) => targetIndex !== index)
    });
  }

  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/70">
      <div className="flex items-center justify-between gap-3 border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-100">Optimization targets</h2>
        <button type="button" onClick={addTarget} className="inline-flex h-8 items-center gap-2 rounded-lg border border-zinc-700 px-2.5 text-xs text-zinc-100 hover:bg-zinc-800">
          <Plus className="h-3.5 w-3.5" />
          Add target
        </button>
      </div>
      <div className="grid gap-2 p-4">
        {parameters.optimization_targets.length ? (
          parameters.optimization_targets.map((target, index) => (
            <div key={`${target.name}-${index}`} className="grid gap-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3 lg:grid-cols-[minmax(0,1.4fr)_120px_120px_100px_auto]">
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-zinc-500">Metric</span>
                <input value={target.name} onChange={(event) => patchTarget(index, { name: event.target.value })} className="field-input" />
              </label>
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-zinc-500">Comparator</span>
                <select value={target.comparator} onChange={(event) => patchTarget(index, { comparator: event.target.value as GoalComparator })} className="field-input">
                  <option value="gte">At least</option>
                  <option value="lte">At most</option>
                  <option value="eq">Equals</option>
                </select>
              </label>
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-zinc-500">Target</span>
                <input type="number" step="0.01" value={target.target} onChange={(event) => patchTarget(index, { target: Number(event.target.value) })} className="field-input" />
              </label>
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-zinc-500">Weight</span>
                <input type="number" min={0} step="0.1" value={target.weight} onChange={(event) => patchTarget(index, { weight: Number(event.target.value) })} className="field-input" />
              </label>
              <button type="button" onClick={() => removeTarget(index)} className="mt-5 inline-flex h-9 items-center justify-center rounded-lg border border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100" aria-label={`Remove ${target.name}`}>
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-zinc-800 p-4 text-sm text-zinc-500">
            Add at least one metric target before running Novacore.
          </div>
        )}
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-2">
      <span className="text-xs font-medium text-zinc-500">{label}</span>
      {children}
    </label>
  );
}

function SeedButton({
  sources,
  value,
  label,
  onChange
}: {
  sources: SeedSource[];
  value: SeedSource;
  label: string;
  onChange: (sources: SeedSource[]) => void;
}) {
  const active = sources.length === 1 && sources[0] === value;
  return (
    <button type="button" onClick={() => onChange([value])} className={seedButtonClass(active)}>
      {label}
    </button>
  );
}

function seedButtonClass(active: boolean) {
  return [
    "h-8 rounded-md px-2 text-xs font-medium transition",
    active ? "bg-emerald-400 text-zinc-950" : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
  ].join(" ");
}

function EmptyParameters() {
  return (
    <section className="rounded-lg border border-dashed border-zinc-800 bg-zinc-900/40 p-8 text-center text-sm text-zinc-500">
      Extract parameters to edit target, conditions, seed source, and loop count.
    </section>
  );
}

function StatusPill({ status }: { status: string }) {
  const active = status === "running" || status === "starting" || status === "queued";
  return (
    <span className={`rounded-full border px-2.5 py-1 text-xs ${active ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-zinc-700 bg-zinc-950 text-zinc-400"}`}>
      {status}
    </span>
  );
}

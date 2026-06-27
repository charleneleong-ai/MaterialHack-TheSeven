import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { createRunEventSource, decodeEvent, getLoopDetail, getMemory, rollbackLoop, runLoops } from "../api";
import type { LoopDetail, MemorySnapshot, WorkbenchEvent } from "../types";
import EventFeed from "./EventFeed";
import EvaluationInspector from "./EvaluationInspector";
import LoopGraph from "./LoopGraph";
import RollbackDialog from "./RollbackDialog";

export default function MemoryPage() {
  const { runId } = useParams<{ runId: string }>();
  const queryClient = useQueryClient();
  const [selectedLoopId, setSelectedLoopId] = useState<string | null>(null);
  const [events, setEvents] = useState<WorkbenchEvent[]>([]);

  const memoryQuery = useQuery({
    queryKey: ["memory", runId],
    queryFn: () => getMemory(runId!),
    enabled: Boolean(runId),
    refetchInterval: 2500
  });

  useEffect(() => {
    if (!runId) return;
    const eventSource = createRunEventSource(runId);
    const append = (message: MessageEvent<string>) => {
      const event = decodeEvent(message);
      setEvents((current) => [...current, event]);
      void queryClient.invalidateQueries({ queryKey: ["memory", runId] });
      if (event.loop_id) {
        void queryClient.invalidateQueries({ queryKey: ["loop", runId, event.loop_id] });
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

  useEffect(() => {
    if (!selectedLoopId && memoryQuery.data?.active_loop_id) {
      setSelectedLoopId(memoryQuery.data.active_loop_id);
    }
  }, [memoryQuery.data, selectedLoopId]);

  if (!runId) {
    return <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-6 text-sm text-zinc-400">No run selected.</div>;
  }

  return (
    <div className="grid min-h-[calc(100dvh-96px)] gap-4 xl:grid-cols-[minmax(0,1fr)_460px]">
      <section className="grid min-h-[680px] overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/70">
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <Link to="/" className="mb-2 inline-flex items-center gap-2 text-xs text-zinc-500 hover:text-zinc-200">
              <ArrowLeft className="h-3.5 w-3.5" />
              Run console
            </Link>
            <h1 className="text-sm font-semibold text-zinc-100">Memory graph</h1>
            <div className="mt-1 break-all font-mono text-xs text-zinc-500">{runId}</div>
          </div>
          {memoryQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin text-zinc-500" /> : null}
        </div>
        {memoryQuery.isLoading ? (
          <div className="grid place-items-center text-sm text-zinc-500">Loading memory.</div>
        ) : memoryQuery.error ? (
          <div className="grid place-items-center p-8 text-sm text-rose-200">{memoryQuery.error.message}</div>
        ) : memoryQuery.data ? (
          <LoopGraph snapshot={memoryQuery.data} selectedLoopId={selectedLoopId} onSelectLoop={setSelectedLoopId} />
        ) : null}
      </section>

      <aside className="grid content-start gap-4">
        <LoopInspector runId={runId} snapshot={memoryQuery.data} selectedLoopId={selectedLoopId} onSelectLoop={setSelectedLoopId} />
        <EventFeed events={events} compact />
      </aside>
    </div>
  );
}

function LoopInspector({
  runId,
  snapshot,
  selectedLoopId,
  onSelectLoop
}: {
  runId: string;
  snapshot?: MemorySnapshot;
  selectedLoopId: string | null;
  onSelectLoop: (loopId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [branchCount, setBranchCount] = useState(1);
  const [rollbackReason, setRollbackReason] = useState("");

  const detailQuery = useQuery({
    queryKey: ["loop", runId, selectedLoopId],
    queryFn: () => getLoopDetail(runId, selectedLoopId!),
    enabled: Boolean(selectedLoopId)
  });

  const branchMutation = useMutation({
    mutationFn: () => runLoops(runId, branchCount, selectedLoopId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory", runId] });
    }
  });

  const rollbackMutation = useMutation({
    mutationFn: () => rollbackLoop(runId, selectedLoopId!, rollbackReason),
    onSuccess: () => {
      setRollbackReason("");
      void queryClient.invalidateQueries({ queryKey: ["memory", runId] });
      if (selectedLoopId) void queryClient.invalidateQueries({ queryKey: ["loop", runId, selectedLoopId] });
    }
  });

  const selectedSummary = useMemo(
    () => snapshot?.nodes.find((node) => node.loop_id === selectedLoopId),
    [selectedLoopId, snapshot]
  );

  if (!selectedLoopId) {
    return <section className="rounded-lg border border-zinc-800 bg-zinc-900/70 p-6 text-sm text-zinc-500">Select a loop.</section>;
  }

  if (detailQuery.isLoading) {
    return <section className="rounded-lg border border-zinc-800 bg-zinc-900/70 p-6 text-sm text-zinc-500">Loading loop.</section>;
  }

  if (detailQuery.error) {
    return <section className="rounded-lg border border-zinc-800 bg-zinc-900/70 p-6 text-sm text-rose-200">{detailQuery.error.message}</section>;
  }

  const detail = detailQuery.data;
  if (!detail) return null;

  const canRollback = selectedSummary?.can_branch_from && selectedSummary.status !== "pending";
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/70">
      <div className="border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">Loop inspector</h2>
            <div className="mt-1 break-all font-mono text-xs text-zinc-500">{selectedLoopId}</div>
          </div>
          <span className="rounded-full border border-zinc-700 px-2 py-1 text-xs text-zinc-300">{selectedSummary?.status ?? detail.loop.status}</span>
        </div>
      </div>
      <div className="grid gap-4 p-4">
        <MetricStrip detail={detail} />
        <div className="grid gap-2">
          <div className="text-xs font-medium text-zinc-500">Sequence</div>
          <div className="break-all rounded-lg border border-zinc-800 bg-zinc-950 p-3 font-mono text-xs leading-5 text-zinc-300">
            {detail.loop.candidate.sequence}
          </div>
        </div>
        <AgentPlanPanel detail={detail} />
        <CandidateArtifactsPanel detail={detail} />
        <EvaluationInspector detail={detail} />
        <HumanInputPanel inputs={detail.loop.human_inputs} />
        <div className="grid gap-3 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
          <div className="text-xs font-medium text-zinc-500">Actions</div>
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <input
              type="number"
              min={0}
              value={branchCount}
              onChange={(event) => setBranchCount(Number(event.target.value))}
              className="field-input"
              aria-label="Loop count"
            />
            <button
              type="button"
              onClick={() => branchMutation.mutate()}
              disabled={branchMutation.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-emerald-400 px-3 text-sm font-medium text-zinc-950 disabled:opacity-50"
            >
              {branchMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Run loops
            </button>
          </div>
          <RollbackDialog
            reason={rollbackReason}
            canRollback={Boolean(canRollback)}
            isPending={rollbackMutation.isPending}
            onReasonChange={setRollbackReason}
            onConfirm={() => rollbackMutation.mutate()}
          />
        </div>
        <div className="grid gap-2">
          <div className="text-xs font-medium text-zinc-500">Lineage</div>
          <div className="flex flex-wrap gap-2">
            {detail.lineage_loop_ids.map((loopId) => (
              <button key={loopId} type="button" onClick={() => onSelectLoop(loopId)} className="rounded-lg border border-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300 hover:bg-zinc-800">
                {loopId}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function AgentPlanPanel({ detail }: { detail: LoopDetail }) {
  const changeSet = detail.loop.change_set;
  if (!changeSet) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm text-zinc-500">
        Loop 0 seed selected by Novacore pre-loop ranking.
      </div>
    );
  }

  return (
    <div className="grid gap-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-zinc-500">Agent plan</div>
        <span className="rounded-md border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200">
          {changeSet.author}
        </span>
      </div>
      <div className="text-sm font-medium text-zinc-100">{changeSet.summary}</div>
      <p className="text-sm leading-5 text-zinc-400">{changeSet.why}</p>
      <div className="flex flex-wrap gap-2">
        {changeSet.changes.map((change) => (
          <span key={String(change.machine_diff)} className="rounded-md border border-zinc-700 px-2 py-1 font-mono text-xs text-zinc-300">
            {String(change.machine_diff)}
          </span>
        ))}
      </div>
    </div>
  );
}

function CandidateArtifactsPanel({ detail }: { detail: LoopDetail }) {
  const artifacts = [...detail.loop.candidate.structure_artifacts, ...detail.loop.candidate.boltz_artifacts];
  if (!artifacts.length) return null;

  return (
    <div className="grid gap-2">
      <div className="text-xs font-medium text-zinc-500">Candidate artifacts</div>
      <div className="grid gap-1 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
        {artifacts.map((artifact) => (
          <div key={`${artifact.kind}-${artifact.uri}`} className="grid gap-1 text-xs">
            <div className="text-zinc-300">{artifact.kind}</div>
            <div className="break-all font-mono text-zinc-500">{artifact.uri}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HumanInputPanel({ inputs }: { inputs: LoopDetail["loop"]["human_inputs"] }) {
  return (
    <div className="grid gap-2">
      <div className="text-xs font-medium text-zinc-500">Human and agent notes</div>
      {inputs.length ? (
        <div className="grid gap-2">
          {inputs.map((input) => {
            const action = typeof input.metadata.action === "string" ? input.metadata.action : "note";
            const actor = typeof input.metadata.actor === "string" ? input.metadata.actor : input.author;
            const previousActive = typeof input.metadata.previous_active_loop_id === "string" ? input.metadata.previous_active_loop_id : null;
            return (
              <article key={`${input.created_at}-${input.note}`} className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-300">
                    {action === "rollback" ? `Rollback: ${actor}` : actor}
                  </span>
                  <time className="shrink-0 text-[11px] text-zinc-500">{formatDate(input.created_at)}</time>
                </div>
                <p className="mt-2 text-sm leading-5 text-zinc-300">{input.note}</p>
                {previousActive ? (
                  <div className="mt-2 break-all font-mono text-[11px] text-zinc-500">
                    Previous active: {previousActive}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm text-zinc-500">No notes recorded.</div>
      )}
    </div>
  );
}

function MetricStrip({ detail }: { detail: LoopDetail }) {
  const latestMetrics = detail.loop.evaluations.at(-1)?.metrics.reduce<Record<string, number>>((acc, metric) => {
    acc[metric.name] = metric.value;
    return acc;
  }, {}) ?? {};
  const metrics = Object.entries(latestMetrics).slice(0, 4);
  return (
    <div className="grid grid-cols-2 gap-2">
      {metrics.length === 0 ? (
        <div className="col-span-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm text-zinc-500">No metrics recorded.</div>
      ) : (
        metrics.map(([name, value]) => (
          <div key={name} className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
            <div className="text-[11px] uppercase tracking-[0.12em] text-zinc-500">{name}</div>
            <div className="mt-1 font-mono text-lg text-zinc-100">{Number(value).toFixed(3)}</div>
          </div>
        ))
      )}
    </div>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

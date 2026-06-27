from __future__ import annotations

import asyncio
import json
import queue
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from materialhack_memory import MetricGoal, to_jsonable

from materialhack_agent.workbench_service import WorkbenchService


class ParseObjectiveRequest(BaseModel):
    objective: str = Field(min_length=1)


class OptimizationTargetPayload(BaseModel):
    name: str = Field(min_length=1)
    target: float
    comparator: Literal["gte", "lte", "eq"] = "gte"
    weight: float = 1.0
    unit: str | None = None
    description: str | None = None

    def to_metric_goal(self) -> MetricGoal:
        return MetricGoal(
            name=self.name,
            target=self.target,
            comparator=self.comparator,
            weight=self.weight,
            unit=self.unit,
            description=self.description,
        )


class ParseObjectiveResponse(BaseModel):
    target: str
    ph: float
    functions: list[str]
    length: int
    seed_count: int
    seed_sources: list[str]
    target_score: float
    loop_count: int
    optimization_targets: list[OptimizationTargetPayload]


class CreateRunRequest(BaseModel):
    objective: str = Field(min_length=1)
    target: str = Field(min_length=1)
    ph: float = 7.0
    functions: list[str] = Field(default_factory=lambda: ["bind"])
    length: int = Field(default=60, ge=1)
    seed_count: int = Field(default=5, ge=1)
    seed_sources: list[Literal["ccdc_csd", "de_novo"]] = Field(default_factory=lambda: ["ccdc_csd", "de_novo"])
    target_score: float = Field(default=0.8, ge=0.0, le=1.0)
    loop_count: int = Field(default=2, ge=0)
    optimization_targets: list[OptimizationTargetPayload] = Field(default_factory=list)
    run_mode: Literal["seed_and_loop", "seed_only"] = "seed_and_loop"
    rng_seed: int = 7


class CreateRunResponse(BaseModel):
    run_id: str
    job_id: str
    status: str


class RunLoopsRequest(BaseModel):
    loop_count: int = Field(default=1, ge=0)
    start_loop_id: str | None = None


class RunLoopsResponse(BaseModel):
    run_id: str
    job_id: str
    status: str


class RollbackRequest(BaseModel):
    loop_id: str
    actor: str = "human"
    reason: str = Field(min_length=1)


service = WorkbenchService()
app = FastAPI(title="Novacore API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/objectives/parse", response_model=ParseObjectiveResponse)
def parse_objective_endpoint(request: ParseObjectiveRequest) -> ParseObjectiveResponse:
    parameters = service.parse_objective_parameters(request.objective)
    return ParseObjectiveResponse(
        target=parameters.target,
        ph=parameters.ph,
        functions=list(parameters.functions),
        length=parameters.length,
        seed_count=parameters.seed_count,
        seed_sources=list(parameters.seed_sources),
        target_score=parameters.target_score,
        loop_count=parameters.loop_count,
        optimization_targets=[OptimizationTargetPayload(**to_jsonable(target)) for target in parameters.optimization_targets],
    )


@app.post("/api/runs", response_model=CreateRunResponse)
def create_run_endpoint(request: CreateRunRequest) -> CreateRunResponse:
    try:
        payload = request.model_dump(exclude={"optimization_targets"})
        run_id, job_id = service.create_run(
            **payload,
            optimization_targets=tuple(target.to_metric_goal() for target in request.optimization_targets),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CreateRunResponse(run_id=run_id, job_id=job_id, status=service.get_job(job_id).status.value)


@app.post("/api/runs/{run_id}/loops", response_model=RunLoopsResponse)
def run_loops_endpoint(run_id: str, request: RunLoopsRequest) -> RunLoopsResponse:
    try:
        job_id = service.run_loops(
            run_id=run_id,
            loop_count=request.loop_count,
            start_loop_id=request.start_loop_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RunLoopsResponse(run_id=run_id, job_id=job_id, status=service.get_job(job_id).status.value)


@app.post("/api/runs/{run_id}/rollback")
def rollback_endpoint(run_id: str, request: RollbackRequest):
    try:
        loop = service.rollback(
            run_id=run_id,
            loop_id=request.loop_id,
            actor=request.actor,
            reason=request.reason,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_jsonable(loop)


@app.get("/api/runs/{run_id}/memory")
def memory_endpoint(run_id: str):
    try:
        return service.memory.get_run_visualization(run_id).to_frontend_payload()
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/loops/{loop_id}")
def loop_detail_endpoint(run_id: str, loop_id: str):
    try:
        loop = service.memory.get_loop(run_id=run_id, loop_id=loop_id)
        lineage = service.memory.get_lineage(run_id=run_id, loop_id=loop_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "loop": to_jsonable(loop),
        "lineage_loop_ids": [item.loop_id for item in lineage],
    }


@app.get("/api/jobs/{job_id}")
def job_endpoint(job_id: str):
    try:
        return service.get_job(job_id).to_payload()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=job_id) from exc


@app.get("/api/runs/{run_id}/events")
async def events_endpoint(run_id: str):
    async def stream():
        subscriber = service.event_hub.subscribe(run_id)
        try:
            for event in service.event_hub.events_for_run(run_id):
                yield _format_sse(event.event_type, event.to_payload())
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 15)
                    yield _format_sse(event.event_type, event.to_payload())
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            service.event_hub.unsubscribe(run_id, subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream")


def _format_sse(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def run() -> None:
    import uvicorn

    uvicorn.run("materialhack_agent.workbench_api:app", host="127.0.0.1", port=8000, reload=False)

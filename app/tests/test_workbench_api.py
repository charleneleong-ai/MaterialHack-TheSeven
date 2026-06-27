from __future__ import annotations

import time

from fastapi.testclient import TestClient

import materialhack_agent.workbench_api as api_module
from materialhack_agent.workbench_service import JobState, WorkbenchService


def _client() -> TestClient:
    api_module.service = WorkbenchService()
    return TestClient(api_module.app)


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 5
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {JobState.SUCCEEDED.value, JobState.FAILED.value}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {job_id}")


def test_parse_objective_returns_editable_defaults():
    client = _client()

    response = client.post(
        "/api/objectives/parse",
        json={"objective": "design a 72 residue protein that binds Zn2+ at pH 5 and can polymerize"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"] == "ZN2+"
    assert payload["ph"] == 5.0
    assert payload["length"] == 72
    assert payload["seed_sources"] == ["ccdc_csd", "de_novo"]
    assert [target["name"] for target in payload["optimization_targets"]] == ["trs_total", "plddt"]


def test_create_run_builds_seed_and_requested_loops():
    client = _client()

    response = client.post(
        "/api/runs",
        json={
            "objective": "design a protein that binds Zn2+ at pH 5",
            "target": "ZN2+",
            "ph": 5.0,
            "functions": ["bind"],
            "length": 60,
            "seed_count": 4,
            "seed_sources": ["ccdc_csd"],
            "target_score": 0.95,
            "loop_count": 2,
            "optimization_targets": [
                {"name": "trs_total", "target": 0.75, "comparator": "gte", "weight": 1.0},
                {"name": "plddt", "target": 0.7, "comparator": "gte", "weight": 0.5},
            ],
        },
    )
    response.raise_for_status()
    payload = response.json()
    job = _wait_for_job(client, payload["job_id"])

    assert job["status"] == "succeeded"
    memory = client.get(f"/api/runs/{payload['run_id']}/memory").json()
    assert len(memory["nodes"]) == 3
    assert [node["index"] for node in memory["nodes"]] == [0, 1, 2]
    assert any("verifier" in node["evaluation_kinds"] for node in memory["nodes"])
    assert [goal["name"] for goal in memory["objective"]["goals"]] == ["trs_total", "plddt"]
    loop_0 = client.get(f"/api/runs/{payload['run_id']}/loops/{memory['root_loop_id']}").json()
    artifact_uris = [
        artifact["uri"]
        for artifact in loop_0["loop"]["candidate"]["structure_artifacts"]
    ]
    assert any(uri.startswith("zip://ligands_10000.zip!/ligands_10000/Zn/") for uri in artifact_uris)


def test_seed_only_run_mode_stops_after_loop_zero():
    client = _client()

    response = client.post(
        "/api/runs",
        json={
            "objective": "design a protein that binds Zn2+ at pH 5",
            "target": "ZN2+",
            "ph": 5.0,
            "functions": ["bind"],
            "length": 60,
            "seed_count": 4,
            "seed_sources": ["ccdc_csd", "de_novo"],
            "target_score": 0.95,
            "loop_count": 2,
            "run_mode": "seed_only",
        },
    )
    response.raise_for_status()
    payload = response.json()
    job = _wait_for_job(client, payload["job_id"])

    assert job["status"] == "succeeded"
    assert job["result"]["loops_completed"] == 0
    memory = client.get(f"/api/runs/{payload['run_id']}/memory").json()
    assert len(memory["nodes"]) == 1
    assert memory["nodes"][0]["index"] == 0


def test_event_log_replays_as_sse_payloads():
    client = _client()
    run = client.post(
        "/api/runs",
        json={
            "objective": "design a protein that binds Zn2+ at pH 5",
            "target": "ZN2+",
            "ph": 5.0,
            "functions": ["bind"],
            "length": 60,
            "seed_count": 2,
            "seed_sources": ["ccdc_csd", "de_novo"],
            "target_score": 0.95,
            "loop_count": 1,
        },
    ).json()
    _wait_for_job(client, run["job_id"])

    sse_payloads = [
        api_module._format_sse(event.event_type, event.to_payload())
        for event in api_module.service.event_hub.events_for_run(run["run_id"])
    ]

    assert any(payload.startswith("event: evaluation_attached") for payload in sse_payloads)
    assert any('"evaluation_kind": "screening"' in payload for payload in sse_payloads)
    assert any('"evaluation_kind": "verifier"' in payload for payload in sse_payloads)
    assert any('"evaluator_name": "trs"' in payload for payload in sse_payloads)


def test_rollback_marks_descendants_abandoned_and_emits_event():
    client = _client()
    run = client.post(
        "/api/runs",
        json={
            "objective": "design a protein that binds Zn2+ at pH 5",
            "target": "ZN2+",
            "ph": 5.0,
            "functions": ["bind"],
            "length": 60,
            "seed_count": 2,
            "seed_sources": ["ccdc_csd", "de_novo"],
            "target_score": 0.95,
            "loop_count": 2,
        },
    ).json()
    _wait_for_job(client, run["job_id"])
    memory = client.get(f"/api/runs/{run['run_id']}/memory").json()
    loop_1 = memory["nodes"][1]["loop_id"]
    loop_2 = memory["nodes"][2]["loop_id"]

    rollback = client.post(
        f"/api/runs/{run['run_id']}/rollback",
        json={"loop_id": loop_1, "actor": "human", "reason": "Loop 2 reduced useful verifier confidence."},
    )
    rollback.raise_for_status()

    updated = client.get(f"/api/runs/{run['run_id']}/memory").json()
    nodes = {node["loop_id"]: node for node in updated["nodes"]}
    assert nodes[loop_1]["status"] == "active"
    assert nodes[loop_2]["status"] == "abandoned"
    assert nodes[loop_1]["human_inputs"][-1]["metadata"]["action"] == "rollback"

    event_types = [
        event.event_type
        for event in api_module.service.event_hub.events_for_run(run["run_id"])
    ]
    assert "rollback_recorded" in event_types


def test_continue_from_earlier_loop_creates_branch():
    client = _client()
    run = client.post(
        "/api/runs",
        json={
            "objective": "design a protein that binds Zn2+ at pH 5",
            "target": "ZN2+",
            "ph": 5.0,
            "functions": ["bind"],
            "length": 60,
            "seed_count": 2,
            "seed_sources": ["ccdc_csd", "de_novo"],
            "target_score": 0.95,
            "loop_count": 2,
        },
    ).json()
    _wait_for_job(client, run["job_id"])
    memory = client.get(f"/api/runs/{run['run_id']}/memory").json()
    loop_1 = memory["nodes"][1]["loop_id"]
    old_active = memory["active_loop_id"]

    branch = client.post(
        f"/api/runs/{run['run_id']}/loops",
        json={"loop_count": 1, "start_loop_id": loop_1},
    ).json()
    _wait_for_job(client, branch["job_id"])

    updated = client.get(f"/api/runs/{run['run_id']}/memory").json()
    nodes = {node["loop_id"]: node for node in updated["nodes"]}
    assert nodes[old_active]["status"] == "abandoned"
    assert nodes[updated["active_loop_id"]]["parent_loop_id"] == loop_1

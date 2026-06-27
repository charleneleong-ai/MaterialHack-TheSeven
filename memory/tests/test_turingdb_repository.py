import ast
import re
import unittest

from materialhack_memory import (
    CandidateOrigin,
    ChangeOperation,
    ChangeSet,
    ConditionSet,
    DesignObjective,
    EvaluationKind,
    EvaluationResult,
    LoopReflection,
    LoopStatus,
    MetricGoal,
    MetricValue,
    ProteinCandidate,
    ProteinChange,
    SeedCandidate,
    TuringDbMemoryRepository,
)


class FakeTuringDbClient:
    def __init__(self) -> None:
        self.graphs: set[str] = set()
        self.graph_name: str | None = None
        self.records: dict[str, dict[str, str]] = {}
        self.change_counter = 0
        self.checkout_calls: list[str | None] = []
        self.queries: list[str] = []

    def create_graph(self, graph_name: str) -> None:
        self.graphs.add(graph_name)

    def set_graph(self, graph_name: str) -> None:
        if graph_name not in self.graphs:
            self.graphs.add(graph_name)
        self.graph_name = graph_name

    def new_change(self) -> str:
        self.change_counter += 1
        return f"change-{self.change_counter}"

    def checkout(self, change: str | None = None) -> None:
        self.checkout_calls.append(change)

    def query(self, query: str):
        self.queries.append(query)
        if query in {"COMMIT", "CHANGE SUBMIT"}:
            return []
        if query.startswith("CREATE (:MaterialHackMemoryRecord"):
            record_id = self._extract_map_value(query, "record_id")
            self.records[record_id] = {
                "record_id": record_id,
                "record_type": self._extract_map_value(query, "record_type"),
                "payload_json": self._extract_map_value(query, "payload_json"),
                "updated_at": self._extract_map_value(query, "updated_at"),
            }
            return []
        if query.startswith("MATCH (n:MaterialHackMemoryRecord") and " SET " in query:
            record_id = self._extract_match_record_id(query)
            self.records[record_id].update(
                {
                    "record_type": self._extract_set_value(query, "record_type"),
                    "payload_json": self._extract_set_value(query, "payload_json"),
                    "updated_at": self._extract_set_value(query, "updated_at"),
                }
            )
            return []
        if query.startswith("MATCH (n:MaterialHackMemoryRecord") and "RETURN n.record_id AS record_id" in query:
            if "{record_id:" in query:
                record_id = self._extract_match_record_id(query)
                if record_id in self.records:
                    return [{"record_id": record_id}]
                return []
            return [
                {
                    "record_id": record["record_id"],
                    "record_type": record["record_type"],
                    "payload_json": record["payload_json"],
                }
                for record in self.records.values()
            ]
        raise AssertionError(f"Unsupported fake TuringDB query: {query}")

    @staticmethod
    def _extract_map_value(query: str, key: str) -> str:
        match = re.search(rf"{key}: ('(?:\\\\|\\'|[^'])*')", query)
        if not match:
            raise AssertionError(f"Missing map key {key} in query: {query}")
        return ast.literal_eval(match.group(1))

    @staticmethod
    def _extract_set_value(query: str, key: str) -> str:
        match = re.search(rf"n\.{key} = ('(?:\\\\|\\'|[^'])*')", query)
        if not match:
            raise AssertionError(f"Missing SET key {key} in query: {query}")
        return ast.literal_eval(match.group(1))

    @staticmethod
    def _extract_match_record_id(query: str) -> str:
        match = re.search(r"record_id: ('(?:\\\\|\\'|[^'])*')", query)
        if not match:
            raise AssertionError(f"Missing record_id match in query: {query}")
        return ast.literal_eval(match.group(1))


class TuringDbMemoryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeTuringDbClient()
        self.repo = TuringDbMemoryRepository(client=self.client)
        self.objective = DesignObjective(
            description="Optimize a metal binder.",
            goals=(MetricGoal(name="binding_score", target=0.85),),
            max_loops=8,
        )
        self.conditions = ConditionSet.common(
            binding_target="target-protein-x",
            ligand="Zn2+",
            ph=5.0,
            temperature_c=37,
        )

    def test_turingdb_repository_persists_and_hydrates_seed_handoff_run(self) -> None:
        pool = self.repo.create_seed_pool(
            pool_id="pool_tdb",
            objective=self.objective,
            conditions=self.conditions,
            candidates=(
                SeedCandidate(
                    seed_candidate_id="seed_tdb",
                    sequence="ACDEFGHIKL",
                    origin=CandidateOrigin.CCDC_CSD,
                    source_database="CCDC/CSD",
                    source_id="CSD-TDB-1",
                    evaluations=(
                        EvaluationResult(
                            kind=EvaluationKind.VERIFIER,
                            evaluator_name="wf-verifier",
                            metrics=(MetricValue(name="binding_score", value=0.73),),
                        ),
                    ),
                ),
            ),
        )
        decision = self.repo.record_seed_selection_decision(
            decision_id="decision_tdb",
            pool_id=pool.pool_id,
            selected_seed_candidate_id="seed_tdb",
            rationale="WF selected the only candidate in this fake TuringDB test.",
        )
        run = self.repo.create_run_from_seed_selection(
            decision_id=decision.decision_id,
            run_id="run_tdb",
            loop_id="loop_0_tdb",
        )

        fresh_repo = TuringDbMemoryRepository(client=self.client)
        context = fresh_repo.get_active_context(run.run_id)
        loop_0 = fresh_repo.get_loop(run_id=run.run_id, loop_id=run.root_loop_id)

        self.assertEqual(context.sequence, "ACDEFGHIKL")
        self.assertEqual(context.seed_selection_decision.rationale, decision.rationale)
        self.assertEqual(loop_0.latest_metric_map()["binding_score"], 0.73)
        self.assertIn("run:run_tdb", self.client.records)
        self.assertIn("loop:run_tdb:loop_0_tdb", self.client.records)
        self.assertIn("seed_pool:pool_tdb", self.client.records)
        self.assertIn("seed_selection:decision_tdb", self.client.records)

    def test_turingdb_repository_persists_finalized_loop_state(self) -> None:
        run = self.repo.create_run(
            objective=self.objective,
            seed_candidate=ProteinCandidate(sequence="ACDEFGHIKL", origin=CandidateOrigin.CCDC_CSD),
            conditions=self.conditions,
            run_id="run_loop_tdb",
            loop_id="loop_0",
        )
        loop = self.repo.append_loop(
            run_id=run.run_id,
            loop_id="loop_1",
            candidate=ProteinCandidate(sequence="ACDEYGHIKL", origin=CandidateOrigin.DERIVED),
            change_set=ChangeSet(
                summary="Test F5Y",
                why="Improve predicted contact.",
                changes=(
                    ProteinChange(
                        operation=ChangeOperation.SUBSTITUTE,
                        machine_diff="F5Y",
                        rationale="Add a polar aromatic contact.",
                    ),
                ),
            ),
        )
        self.repo.attach_evaluation(
            run_id=run.run_id,
            loop_id=loop.loop_id,
            evaluation=EvaluationResult(kind=EvaluationKind.BOLTZ, evaluator_name="boltz"),
        )
        self.repo.attach_evaluation(
            run_id=run.run_id,
            loop_id=loop.loop_id,
            evaluation=EvaluationResult(kind=EvaluationKind.SCREENING, evaluator_name="screen"),
        )
        self.repo.attach_evaluation(
            run_id=run.run_id,
            loop_id=loop.loop_id,
            evaluation=EvaluationResult(kind=EvaluationKind.VERIFIER, evaluator_name="verifier"),
        )
        finalized = self.repo.set_loop_reflection(
            run_id=run.run_id,
            loop_id=loop.loop_id,
            reflection=LoopReflection(
                went_well=("Verifier ran.",),
                went_wrong=("Target not yet met.",),
                next_actions=("Try a smaller aromatic substitution.",),
            ),
        )
        finalized = self.repo.finalize_loop(run_id=run.run_id, loop_id=finalized.loop_id)

        fresh_repo = TuringDbMemoryRepository(client=self.client)
        fresh_loop = fresh_repo.get_loop(run_id=run.run_id, loop_id=finalized.loop_id)

        self.assertEqual(finalized.status, LoopStatus.ACTIVE)
        self.assertEqual(fresh_loop.status, LoopStatus.ACTIVE)
        self.assertEqual(fresh_repo.extract_sequence(run_id=run.run_id), "ACDEYGHIKL")


if __name__ == "__main__":
    unittest.main()

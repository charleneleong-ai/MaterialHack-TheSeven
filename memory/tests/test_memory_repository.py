import unittest

from materialhack_memory import (
    CandidateOrigin,
    ChangeOperation,
    ChangeSet,
    ConditionSet,
    DesignObjective,
    EvaluationKind,
    EvaluationResult,
    InMemoryProteinMemoryRepository,
    LoopReflection,
    LoopStatus,
    MetricGoal,
    MetricValue,
    ProteinCandidate,
    ProteinChange,
)


class MemoryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryProteinMemoryRepository()
        self.objective = DesignObjective(
            description="Optimize binder until verifier affinity and stability targets are met.",
            goals=(
                MetricGoal(name="binding_score", target=0.85, comparator="gte"),
                MetricGoal(name="instability_index", target=35.0, comparator="lte"),
            ),
            max_loops=12,
        )
        self.conditions = ConditionSet.common(
            binding_target="target-protein-x",
            ligand="ligand-a",
            ph=7.4,
            temperature_c=37,
            solvent="aqueous",
        )
        self.run = self.repo.create_run(
            objective=self.objective,
            seed_candidate=ProteinCandidate(
                sequence="ACDEFGHIKLMNPQRSTVWY",
                origin=CandidateOrigin.CCDC_CSD,
                name="seed_from_csd",
            ),
            conditions=self.conditions,
            seed_evaluations=(
                EvaluationResult(
                    kind=EvaluationKind.BOLTZ,
                    evaluator_name="boltz",
                    evaluator_version="placeholder",
                    metrics=(MetricValue(name="binding_score", value=0.41),),
                    summary="Seed binds weakly but has a plausible pocket.",
                ),
            ),
            run_id="run_test",
            loop_id="loop_0",
        )

    def test_active_context_exposes_seed_sequence_conditions_and_metrics(self) -> None:
        context = self.repo.get_active_context("run_test")

        self.assertEqual(context.active_loop_id, "loop_0")
        self.assertEqual(context.sequence, "ACDEFGHIKLMNPQRSTVWY")
        self.assertEqual(context.conditions.parameters["ph"], 7.4)
        self.assertEqual(context.latest_metrics["binding_score"], 0.41)

    def test_append_loop_records_one_change_set_rationale_and_feedback(self) -> None:
        loop = self.repo.append_loop(
            run_id="run_test",
            loop_id="loop_1",
            candidate=ProteinCandidate(sequence="ACDEYGHIKLMNPQRSTVWY", origin=CandidateOrigin.DERIVED),
            change_set=ChangeSet(
                summary="Increase hydrophobic contact near predicted pocket.",
                why="Boltz suggested the pocket was under-packed around residue 5.",
                changes=(
                    ProteinChange(
                        operation=ChangeOperation.SUBSTITUTE,
                        machine_diff="F5Y",
                        position=5,
                        from_residue="F",
                        to_residue="Y",
                        rationale="Add a polar aromatic contact while keeping local packing.",
                    ),
                ),
            ),
            evaluations=(
                EvaluationResult(
                    kind=EvaluationKind.VERIFIER,
                    evaluator_name="binding-verifier",
                    metrics=(MetricValue(name="binding_score", value=0.57),),
                    summary="Predicted binding improved.",
                ),
            ),
            reflection=LoopReflection(
                went_well=("Binding score improved from the seed.",),
                went_wrong=("Stability target is still unknown.",),
                next_actions=("Probe nearby charged substitutions without disrupting the pocket.",),
            ),
        )

        context = self.repo.get_active_context("run_test")
        self.assertEqual(loop.status, LoopStatus.ACTIVE)
        self.assertEqual(context.sequence, "ACDEYGHIKLMNPQRSTVWY")
        self.assertEqual(context.previous_change_sets[0].changes[0].machine_diff, "F5Y")
        self.assertEqual(context.reflection.next_actions[0], "Probe nearby charged substitutions without disrupting the pocket.")

    def test_rollback_preserves_abandoned_branch_and_can_branch_from_prior_loop(self) -> None:
        self.repo.append_loop(
            run_id="run_test",
            loop_id="loop_1",
            candidate=ProteinCandidate(sequence="ACDEYGHIKLMNPQRSTVWY", origin=CandidateOrigin.DERIVED),
            change_set=ChangeSet(
                summary="First change",
                why="Improve binding.",
                changes=(
                    ProteinChange(
                        operation=ChangeOperation.SUBSTITUTE,
                        machine_diff="F5Y",
                        rationale="Test aromatic contact.",
                    ),
                ),
            ),
        )
        self.repo.append_loop(
            run_id="run_test",
            loop_id="loop_2",
            candidate=ProteinCandidate(sequence="ACDEYGHIKLMNPQKSTVWY", origin=CandidateOrigin.DERIVED),
            change_set=ChangeSet(
                summary="Second change",
                why="Improve electrostatic complementarity.",
                changes=(
                    ProteinChange(
                        operation=ChangeOperation.SUBSTITUTE,
                        machine_diff="R15K",
                        rationale="Reduce clash risk while preserving positive charge.",
                    ),
                ),
            ),
        )

        active = self.repo.rollback_to_loop(
            run_id="run_test",
            loop_id="loop_1",
            actor="human",
            reason="Loop 2 hurt the verifier score.",
        )
        self.assertEqual(active.loop_id, "loop_1")
        self.assertEqual(self.repo.get_loop(run_id="run_test", loop_id="loop_2").status, LoopStatus.ABANDONED)

        branch = self.repo.append_loop(
            run_id="run_test",
            loop_id="loop_3",
            parent_loop_id="loop_1",
            branch_label="human_rollback_branch",
            candidate=ProteinCandidate(sequence="ACDEYGHIKLMNPQRSTAWY", origin=CandidateOrigin.DERIVED),
            change_set=ChangeSet(
                summary="Alternative second change",
                why="Keep loop 1 and explore a less disruptive contact.",
                changes=(
                    ProteinChange(
                        operation=ChangeOperation.SUBSTITUTE,
                        machine_diff="V18A",
                        rationale="Create more space near the predicted interface.",
                    ),
                ),
            ),
        )

        self.assertEqual(branch.status, LoopStatus.ACTIVE)
        self.assertEqual(self.repo.extract_sequence(run_id="run_test"), "ACDEYGHIKLMNPQRSTAWY")
        self.assertEqual(
            [loop.loop_id for loop in self.repo.get_lineage(run_id="run_test", loop_id="loop_3")],
            ["loop_0", "loop_1", "loop_3"],
        )


if __name__ == "__main__":
    unittest.main()

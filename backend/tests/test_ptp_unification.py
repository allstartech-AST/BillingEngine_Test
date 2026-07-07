"""PTP batch/live unification (Phase 5) regression tests."""

from __future__ import annotations

from app.engine.conflict_evaluation import evaluate_cpt_conflicts, evaluate_ptp_conflicts_live
from app.engine.loader import MetadataStore
from app.engine.ptp import classify_ptp_conflicts, resolve_ptp_conflicts
from app.engine.realtime.rules import incremental_conflicts


def test_ptp_batch_live_hard_and_bypassable_parity(store: MetadataStore) -> None:
    for active in [{"97110", "97530"}, {"97110", "97140"}, {"97110"}, {"97140", "97530"}]:
        hard, bypassable = classify_ptp_conflicts(active, store)
        removed, _, _, _, batch_conflicts = resolve_ptp_conflicts(active, store)
        live_bc, _, live_hard = evaluate_ptp_conflicts_live(active, store)

        assert removed == {c.component for c in hard}
        assert live_hard == removed
        assert len(live_bc) == len(batch_conflicts)
        assert len(bypassable) == len(batch_conflicts)


def test_incremental_conflicts_matches_shared_evaluator(store: MetadataStore) -> None:
    for active in [{"97110", "97140", "97530"}, {"97110", "97530"}]:
        assert incremental_conflicts(active, store) == evaluate_cpt_conflicts(active, store)

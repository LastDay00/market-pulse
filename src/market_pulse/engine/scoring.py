"""Agrégation transparente de scores pondérés."""
from market_pulse.engine.signals.base import SignalResult


def aggregate_score(results: list[tuple[SignalResult, float]]) -> float:
    """Moyenne pondérée des scores, en ignorant les signaux skipped.

    Args:
        results: liste de (SignalResult, poids). Poids > 0.

    Raises:
        ValueError si la somme des poids vaut 0.
    """
    total_weight = sum(w for _, w in results)
    if total_weight == 0:
        raise ValueError("sum of weights must be > 0")
    active = [(r, w) for r, w in results if not r.metadata.get("skipped")]
    if not active:
        return 50.0
    active_weight = sum(w for _, w in active)
    return sum(r.score * w for r, w in active) / active_weight

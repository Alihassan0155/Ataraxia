import math

def _validate_score(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(field_name + " must be a number.")

    if not math.isfinite(value):
        raise ValueError(field_name + " must be finite.")

    if value < 0.0 or value > 1.0:
        raise ValueError(field_name + " must be between 0 and 1.")

    return float(value)


def calculate_recovery_need(fatigue_risk):
    """
    Calculate the user's initial recovery need from overall fatigue risk.

    Recovery need is a user-level signal indicating how strongly the
    recommender should prioritize restorative content.

    This initial FYP-1 implementation uses fatigue risk directly.
    It is an engineering heuristic, not a clinical measure.
    """

    fatigue_risk = _validate_score(fatigue_risk, "Fatigue risk")

    return round(fatigue_risk, 6)


def calculate_recovery_bonus(recovery_need, recovery_suitability):
    """
    Calculate the recovery-related ranking contribution for a candidate.

    recovery_need:
        User-level recovery need in [0, 1].

    recovery_suitability:
        Candidate-level annotation in [0, 1].

    Missing suitability must be handled by the caller. It must not
    silently be interpreted as zero.
    """

    recovery_need = _validate_score(recovery_need, "Recovery need")
    recovery_suitability = _validate_score(recovery_suitability, "Recovery suitability",)
    bonus = recovery_need * recovery_suitability

    return round(bonus, 6)


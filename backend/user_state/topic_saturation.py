import math

# Initial experimental parameters. These can be tuned later using validation and ablation experiments.

EXPOSURE_MAX_WATCH_MS = 30 * 1000
RECENCY_HALF_LIFE_MINUTES = 30
SATURATION_SENSITIVITY = 0.5


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(value, maximum))


def _validate_number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(field_name + " must be a number.")

    if not math.isfinite(value):
        raise ValueError(field_name + " must be finite.")

    return float(value)


def calculate_topic_saturation(exposures):
    """
    Calculate topic saturation from previously viewed videos.

    Each exposure must contain:
        similarity: cosine similarity with the candidate video
        watch_duration_ms: total accumulated watch duration
        age_minutes: time elapsed since the exposure

    Returns a saturation score between 0.0 and 1.0.
    """

    if not isinstance(exposures, (list, tuple)):
        raise TypeError("Exposures must be a list or tuple.")

    total_exposure = 0.0

    for exposure in exposures:
        if not isinstance(exposure, dict):
            raise TypeError("Each exposure must be a dictionary.")

        required_fields = [
            "similarity",
            "watch_duration_ms",
            "age_minutes"
        ]

        for field in required_fields:
            if field not in exposure:
                raise ValueError("Missing exposure field: " + field)

        similarity = _validate_number(exposure["similarity"], "Similarity")

        watch_duration_ms = _validate_number( exposure["watch_duration_ms"], "Watch duration")
        age_minutes = _validate_number(exposure["age_minutes"], "Age")

        if watch_duration_ms < 0:
            raise ValueError("Watch duration cannot be negative.")

        if age_minutes < 0:
            raise ValueError("Exposure age cannot be negative.")

        if similarity < -1.0 or similarity > 1.0:
            raise ValueError("Cosine similarity must be between -1 and 1.")

        # Ignore negative similarity because it does not represent semantic similarity or repeated-topic exposure.
        similarity = max(0.0, similarity)

        # Short watches contribute proportionally. Exposure reaches its maximum after 30 seconds.
        exposure_strength = _clamp(watch_duration_ms / EXPOSURE_MAX_WATCH_MS)

        # Older exposures gradually contribute less.
        recency_decay = 0.5 ** (age_minutes / RECENCY_HALF_LIFE_MINUTES)
        weighted_exposure = (exposure_strength * recency_decay * similarity)

        total_exposure += weighted_exposure

    # Convert accumulated exposure into a bounded saturation score.
    saturation = 1.0 - math.exp( -SATURATION_SENSITIVITY * total_exposure)

    return round(_clamp(saturation), 6)

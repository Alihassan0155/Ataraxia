import math

# Initial experimental parameters. Keep these centralized for future validation.
EXPOSURE_MAX_WATCH_MS = 30 * 1000
RECENCY_HALF_LIFE_MINUTES = 30
SATURATION_SENSITIVITY = 0.5

EMOTION_WEIGHT = 0.50
VALENCE_WEIGHT = 0.25
AROUSAL_WEIGHT = 0.25

EMOTION_KEYS = ("joy", "sadness", "anger", "fear_anxiety", "surprise", "disgust", "calm_contentment", "neutral",)

EMOTION_SUM_MIN = 0.99
EMOTION_SUM_MAX = 1.01
VALIDATION_TOLERANCE = 1e-9


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(value, maximum))


def _validate_number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(field_name + " must be a number.")

    if not math.isfinite(value):
        raise ValueError(field_name + " must be finite.")

    return float(value)


def _validate_affect_profile(profile, field_name):
    if not isinstance(profile, dict):
        raise TypeError(field_name + " must be a dictionary.")

    required_fields = ["valence", "arousal", "emotions"]

    for field in required_fields:
        if field not in profile:
            raise ValueError("Missing " + field_name + " field: " + field)

    valence = _validate_number(profile["valence"], field_name + " valence")
    arousal = _validate_number(profile["arousal"], field_name + " arousal")

    if valence < -1.0 or valence > 1.0:
        raise ValueError(field_name + " valence must be between -1 and 1.")

    if arousal < 0.0 or arousal > 1.0:
        raise ValueError(field_name + " arousal must be between 0 and 1.")

    emotions = profile["emotions"]

    if not isinstance(emotions, dict):
        raise TypeError(field_name + " emotions must be a dictionary.")

    if set(emotions.keys()) != set(EMOTION_KEYS):
        raise ValueError(field_name + " must contain exactly the eight supported emotions.")

    validated_emotions = {}
    emotion_total = 0.0

    for emotion in EMOTION_KEYS:
        score = _validate_number(emotions[emotion], field_name + " emotion " + emotion)

        if score < 0.0 or score > 1.0:
            raise ValueError(field_name + " emotion scores must be between 0 and 1.")

        validated_emotions[emotion] = score
        emotion_total += score

    if emotion_total < EMOTION_SUM_MIN - VALIDATION_TOLERANCE:
        raise ValueError(field_name + " emotion scores must sum to at least 0.99.")

    if emotion_total > EMOTION_SUM_MAX + VALIDATION_TOLERANCE:
        raise ValueError(field_name + " emotion scores must sum to at most 1.01.")

    # Normalize permissible rounding drift, as specified by the annotation policy.
    for emotion in EMOTION_KEYS:
        validated_emotions[emotion] /= emotion_total

    return {"valence": valence, "arousal": arousal, "emotions": validated_emotions,}


def _calculate_affect_similarity(candidate, previous):
    # Valence similarity: maximum difference across the full [-1, 1] range is 2.
    valence_similarity = 1.0 - (abs(candidate["valence"] - previous["valence"]) / 2.0)

    # Arousal similarity: both values are in [0, 1].
    arousal_similarity = 1.0 - abs(candidate["arousal"] - previous["arousal"])

    # Total variation distance compares the complete emotion distributions.
    total_variation_distance = 0.0

    for emotion in EMOTION_KEYS:
        difference = abs(candidate["emotions"][emotion] - previous["emotions"][emotion])

        total_variation_distance += difference

    total_variation_distance *= 0.5
    emotion_similarity = 1.0 - total_variation_distance
    combined_similarity = (VALENCE_WEIGHT * valence_similarity + AROUSAL_WEIGHT * arousal_similarity + EMOTION_WEIGHT * emotion_similarity)

    return _clamp(combined_similarity)


def calculate_affective_saturation(candidate_affect, exposures):
    """
    Calculate candidate-specific affective saturation.

    candidate_affect must contain:
        valence: emotional tone in [-1, 1]
        arousal: emotional intensity in [0, 1]
        emotions: eight normalized emotion scores

    Each exposure must contain:
        affect: the previous video's affect profile
        watch_duration_ms: total accumulated actual watch duration
        age_minutes: age of the exposure

    Confidence and recovery_suitability are intentionally not used.

    Returns a saturation score between 0.0 and 1.0.
    """

    candidate = _validate_affect_profile(candidate_affect, "Candidate")

    if not isinstance(exposures, (list, tuple)):
        raise TypeError("Exposures must be a list or tuple.")

    total_exposure = 0.0

    for exposure in exposures:
        if not isinstance(exposure, dict):
            raise TypeError("Each exposure must be a dictionary.")

        required_fields = [
            "affect",
            "watch_duration_ms",
            "age_minutes",
        ]

        for field in required_fields:
            if field not in exposure:
                raise ValueError("Missing exposure field: " + field)

        previous = _validate_affect_profile(exposure["affect"], "Exposure affect")
        watch_duration_ms = _validate_number(exposure["watch_duration_ms"], "Watch duration")
        age_minutes = _validate_number(exposure["age_minutes"], "Exposure age")

        if watch_duration_ms < 0:
            raise ValueError("Watch duration cannot be negative.")

        if age_minutes < 0:
            raise ValueError("Exposure age cannot be negative.")

        affect_similarity = _calculate_affect_similarity(candidate, previous)

        # Exposure reaches its maximum contribution after 30 seconds.
        exposure_strength = _clamp(watch_duration_ms / EXPOSURE_MAX_WATCH_MS)

        # Older exposures gradually contribute less.
        recency_decay = 0.5 ** (age_minutes / RECENCY_HALF_LIFE_MINUTES)
        weighted_exposure = (exposure_strength * recency_decay * affect_similarity)

        total_exposure += weighted_exposure

    # Convert accumulated exposure into a bounded saturation score.
    saturation = 1.0 - math.exp(-SATURATION_SENSITIVITY * total_exposure)

    return round(_clamp(saturation), 6)

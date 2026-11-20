
from datetime import timedelta


SESSION_WATCH_MAX_MS = 30 * 60 * 1000
RECENT_WATCH_MAX_MS = 4 * 60 * 1000

SESSION_WEIGHT = 0.40
INTENSITY_WEIGHT = 0.35
EARLY_SKIP_WEIGHT = 0.25

CARRYOVER_HALF_LIFE_MINUTES = 30


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(value, maximum))



def calculate_current_fatigue(
    session_watch_ms,
    recent_watch_ms,
    recent_departures,
):
    if session_watch_ms < 0 or recent_watch_ms < 0:
        raise ValueError("Watch durations cannot be negative.")

    session_load = _clamp(
        session_watch_ms / SESSION_WATCH_MAX_MS
    )

    recent_intensity = _clamp(
        recent_watch_ms / RECENT_WATCH_MAX_MS
    )

    valid_classifications = ["early", "mid", "late", "unknown"]

    early_skips = 0
    known_departures = 0

    for departure in recent_departures:
        if departure not in valid_classifications:
            raise ValueError(
                "Invalid departure classification: " + str(departure)
            )

        if departure != "unknown":
            known_departures += 1

            if departure == "early":
                early_skips += 1

    early_skip_rate = 0.0

    if known_departures >= 3:
        early_skip_rate = early_skips / known_departures

    fatigue = (
        SESSION_WEIGHT * session_load
        + INTENSITY_WEIGHT * recent_intensity
        + EARLY_SKIP_WEIGHT * early_skip_rate
    )

    return round(_clamp(fatigue), 6)



def calculate_carryover(
    previous_fatigue,
    elapsed_since_previous_session,
):
    if not isinstance(elapsed_since_previous_session, timedelta):
        raise TypeError("Elapsed time must be a timedelta.")

    if elapsed_since_previous_session.total_seconds() < 0:
        raise ValueError("Elapsed time cannot be negative.")

    previous_fatigue = _clamp(previous_fatigue)

    elapsed_minutes = (
        elapsed_since_previous_session.total_seconds() / 60
    )

    decay = 0.5 ** (
        elapsed_minutes / CARRYOVER_HALF_LIFE_MINUTES
    )

    return round(previous_fatigue * decay, 6)


def calculate_fatigue(current_fatigue, carryover_fatigue):
    current_fatigue = _clamp(current_fatigue)
    carryover_fatigue = _clamp(carryover_fatigue)

    result = (
        0.80 * current_fatigue
        + 0.20 * carryover_fatigue
    )

    return round(_clamp(result), 6)

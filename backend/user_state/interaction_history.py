
"""Read-only aggregation of interaction events for user-state calculations."""

from datetime import datetime, timedelta


RECENT_WATCH_WINDOW = timedelta(minutes=5)
RECENT_DEPARTURE_LIMIT = 10


def _validate_aware_datetime(value, field_name):
    if not isinstance(value, datetime):
        raise TypeError(field_name + " must be a datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(field_name + " must be timezone-aware.")


def _validate_nonnegative_duration(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(field_name + " must be an integer.")

    if value < 0:
        raise ValueError(field_name + " cannot be negative.")


def _event_sort_key(event):
    occurred_at = event["occurred_at"]
    received_at = event.get("received_at")

    if received_at is None:
        received_at = occurred_at

    interaction_id = str(event.get("interaction_id", ""))

    return occurred_at, received_at, interaction_id


def aggregate_interaction_history(
    events,
    session_watch_ms,
    now,
    recent_window=RECENT_WATCH_WINDOW,
    departure_limit=RECENT_DEPARTURE_LIMIT,
):
    """
    Aggregate retrieved interaction events into user-state inputs.

    Args:
        events:
            Interaction records returned by InteractionRepository.
        session_watch_ms:
            Total watch-event duration for the active session.
        now:
            Current timezone-aware datetime.
        recent_window:
            Window used to calculate recent watch duration.
        departure_limit:
            Maximum number of recent skip classifications to retain.

    Returns:
        Dictionary containing:
            session_watch_ms
            recent_watch_ms
            recent_departures
            watch_exposures

    Each watch exposure retains its own timestamp and duration.
    Skip durations and marker events are never counted as watch time.
    """

    if not isinstance(events, (list, tuple)):
        raise TypeError("Events must be a list or tuple.")

    _validate_nonnegative_duration(
        session_watch_ms,
        "Session watch duration",
    )

    _validate_aware_datetime(now, "Current time")

    if not isinstance(recent_window, timedelta):
        raise TypeError("Recent window must be a timedelta.")

    if recent_window.total_seconds() <= 0:
        raise ValueError("Recent window must be positive.")

    if isinstance(departure_limit, bool):
        raise TypeError("Departure limit must be a positive integer.")

    if not isinstance(departure_limit, int):
        raise TypeError("Departure limit must be a positive integer.")

    if departure_limit <= 0:
        raise ValueError("Departure limit must be positive.")

    recent_cutoff = now - recent_window

    ordered_events = []

    for event in events:
        if not isinstance(event, dict):
            raise TypeError("Each event must be a dictionary.")

        required_fields = [
            "event_type",
            "occurred_at",
            "video_id",
        ]

        for field in required_fields:
            if field not in event:
                raise ValueError("Missing event field: " + field)

        _validate_aware_datetime(
            event["occurred_at"],
            "Event occurred_at",
        )

        received_at = event.get("received_at")

        if received_at is not None:
            _validate_aware_datetime(
                received_at,
                "Event received_at",
            )

        ordered_events.append(event)

    ordered_events.sort(key=_event_sort_key)

    recent_watch_ms = 0
    recent_skip_events = []
    watch_exposures = []

    for event in ordered_events:
        event_type = event["event_type"]
        occurred_at = event["occurred_at"]

        if event_type == "watch":
            duration = event.get("watch_duration_ms")

            if duration is None:
                duration = 0

            _validate_nonnegative_duration(
                duration,
                "Watch duration",
            )

            if occurred_at >= recent_cutoff and occurred_at <= now:
                recent_watch_ms += duration

            if duration > 0 and occurred_at <= now:
                age_minutes = (
                    now - occurred_at
                ).total_seconds() / 60

                watch_exposures.append({
                    "video_id": event["video_id"],
                    "occurred_at": occurred_at,
                    "watch_duration_ms": duration,
                    "age_minutes": age_minutes,
                })

        elif event_type == "skip":
            if occurred_at > now:
                continue

            metadata = event.get("metadata", {})

            if not isinstance(metadata, dict):
                raise TypeError("Event metadata must be a dictionary.")

            classification = metadata.get(
                "skip_classification",
                "unknown",
            )

            valid_classifications = {
                "early",
                "mid",
                "late",
                "unknown",
            }

            if classification not in valid_classifications:
                raise ValueError(
                    "Invalid skip classification: "
                    + str(classification)
                )

            recent_skip_events.append(classification)

    recent_departures = []

    if len(recent_skip_events) > departure_limit:
        recent_skip_events = recent_skip_events[-departure_limit:]

    for classification in recent_skip_events:
        recent_departures.append(classification)

    return {
        "session_watch_ms": session_watch_ms,
        "recent_watch_ms": recent_watch_ms,
        "recent_departures": recent_departures,
        "watch_exposures": watch_exposures,
    }

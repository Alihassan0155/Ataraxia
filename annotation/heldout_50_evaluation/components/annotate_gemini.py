
import os
import time
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from google import genai
from tqdm import tqdm

from common_annotation import (
    OUTPUT_ROOT,
    PILOT_DIR,
    VideoAnnotation,
    build_prompt,
    finalize_annotation,
    load_processed_ids,
    save_annotation,
)


BASE_DIR = Path(__file__).resolve().parent.parent

METADATA_PATH = PILOT_DIR / "pilot_metadata.csv"

OUTPUT_FILE = (
    OUTPUT_ROOT /
    "gemini" /
    "annotations.jsonl"
)

MODEL = "gemini-3.8-flash"
PROGRESS_HOOK = lambda video_id,stage,**details: print(f'Gemini {video_id}: {stage} {details}',flush=True)


class AllGeminiKeysUnavailable(RuntimeError):
    """Raised when no configured Gemini API key can process the video."""


def load_api_keys():

    raw_keys = os.getenv("GEMINI_API_KEYS", "")

    if raw_keys.strip():
        candidates = raw_keys.split(",")
    else:
        candidates = [os.getenv("GEMINI_API_KEY", "")]

    keys = []

    for candidate in candidates:
        key = candidate.strip()

        if key and key not in keys:
            keys.append(key)

    if not keys:
        raise ValueError(
            "GEMINI_API_KEYS (comma-separated) or "
            "GEMINI_API_KEY is required."
        )

    return keys


def is_rate_limit_error(error):

    message = str(error).upper()

    return any(
        marker in message
        for marker in (
            "429",
            "RESOURCE_EXHAUSTED",
            "RATE_LIMIT_EXCEEDED",
            "QUOTA_EXCEEDED",
            "TOO_MANY_REQUESTS",
        )
    )


def is_authentication_error(error):

    message = str(error).upper()

    return any(
        marker in message
        for marker in (
            "401",
            "UNAUTHENTICATED",
            "ACCESS_TOKEN_TYPE_UNSUPPORTED",
            "API_KEY_INVALID",
        )
    )


def is_temporary_service_error(error):

    message = str(error).upper()

    return any(
        marker in message
        for marker in (
            "503",
            "UNAVAILABLE",
            "SERVICE_UNAVAILABLE",
            "HIGH DEMAND",
        )
    )


def wait_until_active(client, uploaded_file, video_id='unknown'):

    deadline=time.monotonic()+180
    while True:
        if time.monotonic()>=deadline:raise TimeoutError('Gemini upload processing exceeded 180 seconds')

        uploaded_file = client.files.get(
            name=uploaded_file.name
        )

        state = uploaded_file.state.name
        PROGRESS_HOOK(video_id,'processing',state=state)

        if state == "ACTIVE":
            return uploaded_file

        if state == "FAILED":
            raise RuntimeError(
                "Gemini video processing failed."
            )

        time.sleep(2)


def annotate_video(
    clients,
    video_path,
    video_id,
    start_client_index=0,
    disabled_client_indexes=None,
):

    if disabled_client_indexes is None:
        disabled_client_indexes = set()

    prompt, context = build_prompt(
        video_id,
        raw_audio_access=True,
    )

    for offset in range(len(clients)):

        client_index = (
            start_client_index + offset
        ) % len(clients)

        if client_index in disabled_client_indexes:
            continue

        client = clients[client_index]

        try:

            PROGRESS_HOOK(video_id,'uploading',key_slot=client_index+1)
            uploaded = client.files.upload(
                file=str(video_path)
            )

            uploaded = wait_until_active(
                client,
                uploaded,
                video_id,
            )

            PROGRESS_HOOK(video_id,'generating',key_slot=client_index+1)
            response = client.interactions.create(
                model=MODEL,
                timeout=180,
                input=[
                    {
                        "type": "video",
                        "uri": uploaded.uri,
                        "mime_type": uploaded.mime_type,
                        "processing": "static",
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": VideoAnnotation.model_json_schema(),
                },
            )

            PROGRESS_HOOK(video_id,'validating')
            raw = VideoAnnotation.model_validate_json(
                response.output_text
            ).model_dump()

            if raw.get("video_id") != video_id:
                raise ValueError("Gemini returned mismatched video ID")

            from pathlib import Path
            import json
            raw_path = OUTPUT_ROOT / "gemini" / "raw_responses.jsonl"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            with raw_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"video_id": video_id, "text": response.output_text, "provider_response": response.model_dump(mode="json")}, ensure_ascii=False) + "\n")

            annotation = finalize_annotation(
                raw,
                video_id,
                MODEL,
                video_path.name,
                context,
                raw_audio_access=True,
            )

            return annotation, client_index

        except Exception as e:

            if is_authentication_error(e):
                disabled_client_indexes.add(client_index)

                print(
                    f"\nGemini key {client_index + 1}/{len(clients)} "
                    "failed authentication and has been disabled for "
                    "the rest of this run; trying the next key..."
                )
                continue

            if is_rate_limit_error(e):
                reason = "rate limited"
            elif is_temporary_service_error(e) or isinstance(e,TimeoutError) or 'TIMEOUT' in str(e).upper() or 'TIMED OUT' in str(e).upper():
                reason = "temporarily unavailable"
            else:
                raise

            print(
                f"\nGemini key {client_index + 1}/{len(clients)} "
                f"was {reason} for {video_id}; "
                "trying the next configured key..."
            )

    active_key_count = len(clients) - len(
        disabled_client_indexes
    )

    raise AllGeminiKeysUnavailable(
        f"No configured Gemini API key could process {video_id}. "
        f"Active keys remaining: {active_key_count}/{len(clients)}. "
        "They were rate limited or the service was temporarily unavailable."
    )


def main():

    load_dotenv()

    api_keys = load_api_keys()

    clients = [
        genai.Client(api_key=api_key)
        for api_key in api_keys
    ]

    print(
        f"Gemini API keys configured: {len(clients)}"
    )

    df = pd.read_csv(
        METADATA_PATH
    )

   
    limit = int(os.getenv("ATARAXIA_LIMIT", "0"))

    if limit > 0:
        df = df.head(limit)

    print(f"Videos selected for this run: {len(df)}")

    processed = load_processed_ids(
        OUTPUT_FILE
    )

    print(
        f"Gemini already processed: "
        f"{len(processed)}"
    )

    current_client_index = 0
    disabled_client_indexes = set()

    for _, row in tqdm(
        df.iterrows(),
        total=len(df)
    ):

        video_path = (
            PILOT_DIR /
            row["pilot_video_path"]
        )

        video_id = video_path.stem

        if video_id in processed:
            continue

        try:

            result, current_client_index = annotate_video(
                clients,
                video_path,
                video_id,
                start_client_index=current_client_index,
                disabled_client_indexes=disabled_client_indexes,
            )

            save_annotation(
                OUTPUT_FILE,
                result
            )

            print(
                f"\n✓ {video_id}"
                f" | {result['dominant_emotion']}"
                f" | V={result['valence']}"
                f" | A={result['arousal']}"
                f" | R={result['recovery_suitability']}"
            )

        except AllGeminiKeysUnavailable as e:

            print(
                f"\nStopped: {e} "
                "Existing annotations are saved; rerun later to resume."
            )
            break

        except Exception as e:

            print(
                f"\n✗ {video_id}: {e}"
            )


if __name__ == "__main__":
    main()

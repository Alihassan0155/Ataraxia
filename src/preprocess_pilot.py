import json
import subprocess
from pathlib import Path

import pandas as pd
import mlx_whisper
import opensmile
from tqdm import tqdm

from common_annotation import PILOT_DIR


BASE_DIR = Path(__file__).resolve().parent.parent

METADATA_PATH = PILOT_DIR / "pilot_metadata.csv"

AUDIO_DIR = PILOT_DIR / "audio"
TRANSCRIPT_DIR = PILOT_DIR / "transcripts"
CONTEXT_DIR = PILOT_DIR / "context"

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

CAPTION_COLUMNS = [
    "caption",
    "video_caption",
    "description",
    "text",
    "title",
]


smile = opensmile.Smile(
    feature_set=opensmile.FeatureSet.eGeMAPSv02,
    feature_level=opensmile.FeatureLevel.Functionals,
)


def find_caption_column(df):
    mapping = {c.lower(): c for c in df.columns}

    for candidate in CAPTION_COLUMNS:
        if candidate.lower() in mapping:
            return mapping[candidate.lower()]

    print("No known caption column detected.")
    print("Columns:", list(df.columns))

    return None


def extract_audio(video_path, audio_path):

    if audio_path.exists():
        return

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            str(audio_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def transcribe(audio_path, transcript_path):

    if transcript_path.exists():
        return transcript_path.read_text(
            encoding="utf-8"
        ).strip()

    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=WHISPER_MODEL,
    )

    text = result.get("text", "").strip()

    transcript_path.write_text(
        text,
        encoding="utf-8"
    )

    return text


def get_feature(features, contains):

    for column in features.index:

        name = str(column).lower()

        if all(x.lower() in name for x in contains):
            try:
                return round(
                    float(features[column]),
                    4
                )
            except Exception:
                pass

    return None


def extract_acoustic_summary(audio_path):

    result = smile.process_file(
        str(audio_path)
    )

    row = result.iloc[0]

    summary = {
        "mean_loudness": get_feature(
            row,
            ["loudness", "amean"]
        ),
        "loudness_variability": get_feature(
            row,
            ["loudness", "stddev"]
        ),
        "mean_pitch": get_feature(
            row,
            ["f0semitone", "amean"]
        ),
        "pitch_variability": get_feature(
            row,
            ["f0semitone", "stddev"]
        ),
        "spectral_flux": get_feature(
            row,
            ["spectralflux", "amean"]
        ),
        "sound_level_db": get_feature(
            row,
            ["equivalentsoundlevel"]
        ),
    }

    return summary


def main():

    AUDIO_DIR.mkdir(exist_ok=True)
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    CONTEXT_DIR.mkdir(exist_ok=True)

    df = pd.read_csv(METADATA_PATH)

    caption_col = find_caption_column(df)

    print("Caption column:", caption_col)

    for _, row in tqdm(
        df.iterrows(),
        total=len(df)
    ):

        video_path = (
            PILOT_DIR /
            row["pilot_video_path"]
        )

        video_id = video_path.stem

        context_path = (
            CONTEXT_DIR /
            f"{video_id}.json"
        )

        if context_path.exists():
            continue

        audio_path = (
            AUDIO_DIR /
            f"{video_id}.wav"
        )

        transcript_path = (
            TRANSCRIPT_DIR /
            f"{video_id}.txt"
        )

        try:

            extract_audio(
                video_path,
                audio_path
            )

            transcript = transcribe(
                audio_path,
                transcript_path
            )

            acoustic = extract_acoustic_summary(
                audio_path
            )

            caption = ""

            if caption_col:

                value = row.get(
                    caption_col,
                    ""
                )

                if pd.notna(value):
                    caption = str(value).strip()

            context = {
                "video_id": video_id,

                "transcript": transcript,

                "acoustic_features": acoustic,

                "metadata_caption": caption,

                "caption_priority": "low",
            }

            with open(
                context_path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    context,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print(
                f"\n✓ {video_id}"
            )

        except Exception as e:

            print(
                f"\n✗ {video_id}: {e}"
            )


if __name__ == "__main__":
    main()

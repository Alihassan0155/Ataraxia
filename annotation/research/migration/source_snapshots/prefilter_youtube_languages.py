"""Rank YouTube Shorts language candidates using metadata text only."""

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from lingua import Language, LanguageDetectorBuilder


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"
TEXT_COLUMNS = ("title", "description", "tags", "channel_name")
ROMAN_HINDI_URDU_WORDS = {
    "aap",
    "ab",
    "acha",
    "accha",
    "agar",
    "apna",
    "apni",
    "aur",
    "bahut",
    "bhai",
    "hai",
    "hain",
    "ham",
    "hum",
    "ka",
    "kar",
    "karo",
    "ke",
    "ki",
    "ko",
    "kya",
    "main",
    "mein",
    "mera",
    "meri",
    "nahi",
    "nahin",
    "se",
    "tha",
    "thi",
    "tum",
    "wala",
    "wali",
    "woh",
    "ye",
    "yeh",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Guess likely language from title, description, tags, and channel "
            "name without downloading videos."
        )
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
    )
    parser.add_argument(
        "--minimum-english-confidence",
        type=float,
        default=0.65,
    )
    parser.add_argument(
        "--minimum-native-script-characters",
        type=int,
        default=4,
    )
    parser.add_argument(
        "--minimum-roman-hindi-urdu-hits",
        type=int,
        default=3,
    )
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def metadata_text(row):
    values = []
    for column in TEXT_COLUMNS:
        value = str(row.get(column, "") or "").strip()
        if value and value.lower() != "nan":
            values.append(value)
    return "\n".join(values)


def count_script_characters(text):
    devanagari = sum("\u0900" <= character <= "\u097f" for character in text)
    arabic = sum(
        "\u0600" <= character <= "\u06ff"
        or "\u0750" <= character <= "\u077f"
        or "\u08a0" <= character <= "\u08ff"
        for character in text
    )
    return devanagari, arabic


def roman_hindi_urdu_hits(text):
    tokens = set(re.findall(r"[a-zA-Z]+", text.lower()))
    return len(tokens & ROMAN_HINDI_URDU_WORDS)


def language_name(language):
    return language.name.lower() if language is not None else "unknown"


def classify_text(
    text,
    detector,
    minimum_english_confidence,
    minimum_native_script_characters,
    minimum_roman_hits,
):
    devanagari, arabic = count_script_characters(text)
    roman_hits = roman_hindi_urdu_hits(text)

    if len(text.strip()) < 15:
        return {
            "metadata_language": "unknown",
            "metadata_language_confidence": 0.0,
            "english_score": 0.0,
            "hindi_score": 0.0,
            "urdu_score": 0.0,
            "devanagari_characters": devanagari,
            "arabic_script_characters": arabic,
            "roman_hindi_urdu_hits": roman_hits,
            "prefilter_status": "uncertain_candidate",
            "audit_priority": 3,
            "target_score": 0.0,
        }

    confidences = detector.compute_language_confidence_values(text)
    score_by_language = {
        item.language: float(item.value) for item in confidences
    }
    top = confidences[0] if confidences else None
    top_language = top.language if top is not None else None
    top_confidence = float(top.value) if top is not None else 0.0
    english_score = score_by_language.get(Language.ENGLISH, 0.0)
    hindi_score = score_by_language.get(Language.HINDI, 0.0)
    urdu_score = score_by_language.get(Language.URDU, 0.0)
    hindi_urdu_score = max(hindi_score, urdu_score)

    native_hindi_urdu_signal = (
        devanagari >= minimum_native_script_characters
        or arabic >= minimum_native_script_characters
    )
    roman_signal = roman_hits >= minimum_roman_hits

    if (
        top_language in {Language.HINDI, Language.URDU}
        or native_hindi_urdu_signal
        or roman_signal
    ):
        status = "hindi_urdu_candidate"
        priority = 1
        target_score = max(
            hindi_urdu_score,
            min(1.0, roman_hits / 10.0),
            min(1.0, (devanagari + arabic) / 20.0),
        )
    elif (
        top_language == Language.ENGLISH
        and top_confidence >= minimum_english_confidence
    ):
        status = "english_candidate"
        priority = 2
        target_score = english_score
    elif top_confidence < 0.80:
        status = "uncertain_candidate"
        priority = 3
        target_score = max(english_score, hindi_score, urdu_score)
    else:
        status = "likely_non_target"
        priority = 4
        target_score = max(english_score, hindi_score, urdu_score)

    return {
        "metadata_language": language_name(top_language),
        "metadata_language_confidence": round(top_confidence, 6),
        "english_score": round(english_score, 6),
        "hindi_score": round(hindi_score, 6),
        "urdu_score": round(urdu_score, 6),
        "devanagari_characters": devanagari,
        "arabic_script_characters": arabic,
        "roman_hindi_urdu_hits": roman_hits,
        "prefilter_status": status,
        "audit_priority": priority,
        "target_score": round(target_score, 6),
    }


def main():
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    metadata_path = dataset_dir / "metadata.csv"
    manifest_path = dataset_dir / "metadata_language_prefilter.csv"
    counts_path = dataset_dir / "metadata_language_counts.csv"

    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Missing {metadata_path}. Run load_youtube_shorts.py first."
        )
    if not 0 <= args.minimum_english_confidence <= 1:
        raise ValueError("English confidence must be between 0 and 1")

    rows = read_csv(metadata_path)
    detector = (
        LanguageDetectorBuilder.from_all_languages()
        .with_preloaded_language_models()
        .build()
    )

    output_rows = []
    for index, row in enumerate(rows, start=1):
        result = classify_text(
            metadata_text(row),
            detector,
            args.minimum_english_confidence,
            args.minimum_native_script_characters,
            args.minimum_roman_hindi_urdu_hits,
        )
        output_rows.append({**row, **result})
        if index % 5000 == 0:
            print(f"Processed metadata rows: {index:,}/{len(rows):,}")

    extra_fields = list(output_rows[0])
    write_csv(manifest_path, output_rows, extra_fields)

    status_counts = Counter(row["prefilter_status"] for row in output_rows)
    language_counts = Counter(row["metadata_language"] for row in output_rows)
    count_rows = []
    for status, count in status_counts.most_common():
        count_rows.append(
            {"count_type": "prefilter_status", "value": status, "count": count}
        )
    for language, count in language_counts.most_common():
        count_rows.append(
            {
                "count_type": "metadata_language_guess",
                "value": language,
                "count": count,
            }
        )
    write_csv(
        counts_path,
        count_rows,
        ["count_type", "value", "count"],
    )

    print(f"Rows classified: {len(output_rows):,}")
    print("Prefilter candidates:")
    for status, count in status_counts.most_common():
        print(f"  {status}: {count:,}")
    print(f"Manifest: {manifest_path}")
    print(f"Counts: {counts_path}")


if __name__ == "__main__":
    main()

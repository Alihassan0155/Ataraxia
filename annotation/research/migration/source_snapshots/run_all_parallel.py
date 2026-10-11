import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "src"
QWEN_ENV_PYTHON = BASE_DIR / ".venv-qwen-mlx" / "bin" / "python"
PILOT_DIR = BASE_DIR / "pilot_50_reels_30h"
OUTPUT_ROOT = BASE_DIR / "outputs" / "reels_30h"

load_dotenv(BASE_DIR / ".env")

TEST_LIMIT = 2

MODELS = {
    "gemini": SRC_DIR / "annotate_gemini.py",
    "qwen": SRC_DIR / "annotate_qwen.py",
}


def run_model(name, script):
    output_dir = OUTPUT_ROOT / name
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / "run.log"

    env = os.environ.copy()
    env["ATARAXIA_LIMIT"] = str(TEST_LIMIT)
    env["ATARAXIA_PILOT_DIR"] = str(PILOT_DIR)
    env["ATARAXIA_OUTPUT_ROOT"] = str(OUTPUT_ROOT)

    python_executable = sys.executable
    if name == "qwen":
        if not QWEN_ENV_PYTHON.exists():
            raise FileNotFoundError(
                f"Missing Qwen MLX environment: {QWEN_ENV_PYTHON}"
            )
        python_executable = str(QWEN_ENV_PYTHON)
    with open(
        log_path,
        "a",
        encoding="utf-8",
        buffering=1,
    ) as log_file:
        print(f"[STARTING] {name}")

        process = subprocess.run(
            [
                python_executable,
                "-u",
                str(script),
            ],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )

        if process.stdout:
            for line in process.stdout.splitlines():
                print(f"[{name.upper()}] {line}")
                log_file.write(line + "\n")
                log_file.flush()

        print(f"[FINISHED] {name} (exit code {process.returncode})")
        return process.returncode


def main():
    print("=" * 60)
    print("ATARAXIA PARALLEL ANNOTATION")
    print("=" * 60)
    print(f"Test limit: {TEST_LIMIT} videos per model")

    results = {}

    with ThreadPoolExecutor(max_workers=len(MODELS)) as executor:
        future_map = {
            executor.submit(run_model, name, script): name
            for name, script in MODELS.items()
        }

        for future in as_completed(future_map):
            name = future_map[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                print(f"[{name.upper()}] ERROR: {exc}")
                results[name] = 1

    print("\n" + "=" * 60)
    print("ANNOTATION RUN FINISHED")
    print("=" * 60)

    for name, result in results.items():
        print(f"{name}: {result}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nParallel annotation interrupted.")

# Dependency boundaries

`pyproject.toml` declares the lightweight application API, contracts, and
calibration dependencies. CUDA and Gemini workers use independent interpreters.
Historical full snapshots remain in their original locations unchanged.

- Core: `python -m pip install -e .` from the project root.
- CUDA: `python -m pip install -r dependencies/cuda.txt`; install torch using the
  existing `setup_vlm_cuda.ps1` instructions. Do not replace the working CUDA stack.
- Gemini: `python -m pip install -r dependencies/gemini.txt`.
- MLX/data collection: original snapshots and scripts remain under the research
  namespace; MLX workflows require Apple Silicon and are not Windows workers.

During migration only missing dotenv/build tools were installed; model-library
versions were not changed. Editable installation was tested with `--no-deps
--no-build-isolation` in both existing environments after installing build tools.

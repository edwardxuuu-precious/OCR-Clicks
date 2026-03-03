# Changelog

This repository uses a timestamp + index version format:

- Format: `YYYYMMDD.NNN` (example: `20260303.001`)
- Source of truth: `VERSION.json`
- Label format: `vYYYYMMDD.NNN`

## [v20260303.007] - 2026-03-03T12:25:22+08:00

### Version Metadata
- version: `20260303.007`
- index: `007`
- version_date: `2026-03-03`
- source_commit: `b544f9d`
- timezone: `Asia/Shanghai`

### Detailed Change Scope
- Versioning and release docs:
  - `VERSION.json`: bumped to `v20260303.007`
  - `CHANGELOG.md`: added this detailed release entry
- Core OCR logic:
  - `src/desktop_ocr_tool.py`
    - add unresolved-target toolbar fallback OCR for low-contrast English placeholders (e.g., `Search`)
    - add same-region nested-text dedup to prevent duplicate fragment/full-line matches (e.g., `免费`)
- Benchmark runner and records:
  - `test/run_benchmark.py`
    - support multi-image benchmark by `cases[].image_path`
    - add per-image aggregates in `results.json`
    - add split output files:
      - `raw_runs.csv` (per-sample per-run)
      - `raw_runs_overall.csv` (overall per-run)
      - `case_results.csv` (per-case per-run)
    - add per-sample section in `summary.md`
- Test assets and protocol:
  - `test/ground_truth.json`: add regression cases `sample2_search_placeholder_en`, `sample2_free_keyword_zh`
  - `test/benchmark_config.json`: default image stays `sample_1`
  - `test/TEST_PROTOCOL.md`: document multi-image + split-record standard
  - `test/BASELINE.md`: update baseline record and active sample set
  - `test/test_sample_img/`: use `sample_1.png`, `sample_2.png`; removed `test/test_capture.png`
- Runtime and startup UX:
  - `start_gui.ps1`, `start_gui.bat`: startup self-check + auto dependency bootstrap
  - `src/ocr_mouse_tester_gui.py`: layout improvements and version metadata propagation
  - `src/ocr_mouse_tester.py`, `src/desktop_ocr_tool.py`, `src/project_version.py`: unified version source + `--version`
- Agent process documentation:
  - `AGENTS.md`: add/update global version broadcast and benchmark asset broadcast rules

### Latest Benchmark Rerun
- result folder: `test/results/20260303_041011`
- overall:
  - `mean_ocr_sec = 52.6219`
  - `text_accuracy = 1.0000`
  - `position_accuracy = 1.0000`
- per sample:
  - `sample_1 mean_ocr_sec = 24.6080`
  - `sample_2 mean_ocr_sec = 28.0139`
- regression cases:
  - `sample2_search_placeholder_en`: 5/5 found, text_ok
  - `sample2_free_keyword_zh`: 5/5 found, text_ok
- comparison vs previous run (`20260303_031751`):
  - `delta_ocr_sec = +5.0060` (`+10.51%`, slower)
  - accuracy guardrails unchanged (`1.0000`)

## [v20260303.006] - 2026-03-03T11:22:19+08:00

### Version Metadata
- version: `20260303.006`
- index: `006`
- version_date: `2026-03-03`
- source_commit: `b544f9d`
- timezone: `Asia/Shanghai`

### Highlights
- Benchmark records are now explicitly split for drill-down analysis:
  - `raw_runs.csv`: per-sample per-run metrics
  - `raw_runs_overall.csv`: overall per-run metrics
  - `case_results.csv`: per-case per-run metrics (with sample/image mapping)
- `results.json` now includes `benchmark.per_image_aggregates`.
- `summary.md` now includes a `Per-Sample Breakdown` section and explicit output-file index.
- Updated benchmark protocol to define the new split-record output contract.
- New validation run:
  - result folder: `test/results/20260303_031751`
  - mean OCR time improved from `54.7683s` to `47.6159s` (`-13.06%`, `1.1502x`)
  - text accuracy: `1.0000`
  - position accuracy: `1.0000`

## [v20260303.005] - 2026-03-03T11:06:56+08:00

### Version Metadata
- version: `20260303.005`
- index: `005`
- version_date: `2026-03-03`
- source_commit: `b544f9d`
- timezone: `Asia/Shanghai`

### Highlights
- Fixed `Search` miss on low-contrast top-toolbar placeholder text (YouTube-like dark search input):
  - added unresolved-target toolbar fallback rescans in `run_ocr` (target-driven mode)
  - enabled robust recovery for OCR variants like `Sesrch` while preserving accuracy
- Fixed duplicate hit issue for `免费` where the same sentence produced both full-line and fragment matches:
  - added region-level and nested-text dedup in `find_text` to keep one representative candidate per same region
- Upgraded benchmark from single-image to multi-image case grouping:
  - `test/run_benchmark.py` now supports `cases[].image_path`
  - one run can evaluate `sample_1` + `sample_2` together
- Added regression cases for both issues in `test/ground_truth.json`:
  - `sample2_search_placeholder_en`
  - `sample2_free_keyword_zh`
- Updated benchmark docs/rules and baseline references to the new two-image workflow.
- Verified benchmark performance/accuracy on updated test set:
  - result folder: `test/results/20260303_030151`
  - mean OCR time improved from `62.4646s` to `54.7683s` (`-12.32%`, `1.1405x`)
  - text accuracy: `1.0000`
  - position accuracy: `1.0000`

## [v20260303.004] - 2026-03-03T10:34:26+08:00

### Version Metadata
- version: `20260303.004`
- index: `004`
- version_date: `2026-03-03`
- source_commit: `b544f9d`
- timezone: `Asia/Shanghai`

### Highlights
- Benchmark baseline image path migrated to `test/test_sample_img/sample_1.png`.
- Updated benchmark assets/config documents:
  - `test/benchmark_config.json`
  - `test/ground_truth.json`
  - `test/TEST_PROTOCOL.md`
  - `test/BASELINE.md`
- Added benchmark path consistency guard in runner:
  - `test/run_benchmark.py` now validates `benchmark_config.image_path == ground_truth.image_path`.
- Added permanent broadcast rule for benchmark image move/rename in `AGENTS.md`.

## [v20260303.003] - 2026-03-03T10:24:15+08:00

### Version Metadata
- version: `20260303.003`
- index: `003`
- version_date: `2026-03-03`
- source_commit: `b544f9d`
- timezone: `Asia/Shanghai`

### Highlights
- GUI layout updated to improve default log visibility:
  - switched `Result` + `Log` area to a vertical `ttk.Panedwindow` split view
  - default split ratio now reserves visible space for `Log` at startup
  - reduced some panel heights (`Targets` / `Runtime` / `Performance`) to avoid log area being pushed off-screen
  - adjusted default window size/min size for laptop-friendly initial rendering

## [v20260303.002] - 2026-03-03T10:13:49+08:00

### Version Metadata
- version: `20260303.002`
- index: `002`
- version_date: `2026-03-03`
- source_commit: `b544f9d`
- timezone: `Asia/Shanghai`

### Highlights
- `start_gui.ps1` now supports startup self-healing:
  - auto-create `.venv` if missing
  - verify runtime imports (`mss`, `numpy`, `cv2`, `rapidocr_onnxruntime`, `pyautogui`)
  - auto-install dependencies from `requirements.txt` when missing
  - track `requirements.txt` hash in `.venv/.requirements.sha256` for fast startup on subsequent runs
- `start_gui.bat` is simplified to delegate to `start_gui.ps1`, so double-click startup uses the same self-check logic.

## [v20260303.001] - 2026-03-03T10:06:47+08:00

### Version Metadata
- version: `20260303.001`
- index: `001`
- version_date: `2026-03-03`
- source_commit: `b544f9d`
- timezone: `Asia/Shanghai`

### Upgrade Range
- previous local baseline: `d9d0bf7` (`chore: clean cache artifacts and add gitignore`)
- synced remote head: `b544f9d` (`perf: add target center bias calibration and keep no-cache benchmark`)
- commit count in range: `5`

### Highlights
- Added GPU toggle, runtime profiling, and benchmark workflow.
- Unified zh/en benchmark process and reset benchmark baseline.
- Enforced strict no-cache benchmark policy.
- Improved OCR speed by trimming recovery and disabling cls.
- Added target center bias calibration and retained no-cache benchmark mode.

### Commits (new -> old)
- `b544f9d` perf: add target center bias calibration and keep no-cache benchmark
- `e3c6681` perf: speed up OCR stage by trimming recovery and disabling cls
- `c7273de` test: enforce strict no-cache benchmark policy
- `c0ff2ea` feat: unify zh-en benchmark and reset baseline
- `f0e5167` feat: add GPU toggle, runtime profiling, and benchmark workflow

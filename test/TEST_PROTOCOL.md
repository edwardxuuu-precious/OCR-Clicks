# OCR Benchmark Protocol (Unified Standard)

This document defines the single benchmark standard for speed and accuracy.

## 1. Baseline Asset

- Baseline image: `test/test_capture.png`
- Benchmark config: `test/benchmark_config.json`
- Ground truth labels: `test/ground_truth.json`
- Benchmark runner: `test/run_benchmark.py`

All future benchmark runs must use this baseline image unless the protocol version is explicitly updated.

## 2. Evaluation Goals

Two accuracy dimensions and one efficiency dimension are measured:

1. Text match accuracy
2. Position accuracy
3. Runtime efficiency (highest priority)

## 3. Metrics Definition

For each benchmark mode (`gpu` and `cpu`):

1. `mean_total_sec`: average total runtime per run
2. `mean_ocr_sec`: average OCR stage runtime per run
3. `mean_match_sec`: average text matching stage runtime per run
4. `found_rate`: detected targets / total targets
5. `text_accuracy`: text-correct targets / total targets
6. `position_accuracy`: position-correct targets / position-evaluable targets
7. `mean_position_error_px`: average center distance error in pixels

Comparison metrics:

1. `speedup_total_gpu_vs_cpu`
2. `speedup_ocr_gpu_vs_cpu`
3. `text_accuracy_delta_gpu_minus_cpu`
4. `position_accuracy_delta_gpu_minus_cpu`

## 4. Fixed Test Method

1. Keep the same config and ground truth files.
2. Run warmup loops first (`warmup_runs`).
3. Run measurement loops (`measure_runs`) for each mode.
4. Use the same `min_score`, `threshold`, `topk`, and `case_sensitive` values for both modes.
5. Use the same target list and expected centers from `ground_truth.json`.
6. Do not change the image during a benchmark campaign.

Command:

```powershell
.\.venv\Scripts\python.exe test\run_benchmark.py --config test\benchmark_config.json
```

## 5. Result Storage Standard

All benchmark outputs are saved to:

- `test/results/<UTC_TIMESTAMP>/`

Each run directory contains:

1. `benchmark_config_snapshot.json`: exact config used
2. `results.json`: full structured results
3. `raw_runs.csv`: per-run raw timing and accuracy metrics
4. `summary.md`: quick human-readable summary

Do not overwrite previous result folders.

## 6. Ground Truth Update Rule

When target text or expected position needs correction:

1. Update only `test/ground_truth.json`
2. Keep tolerances explicit (`tolerance_px`)
3. Record a new benchmark run after changes
4. Compare only runs that used the same ground truth revision


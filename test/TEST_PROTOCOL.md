# OCR Benchmark Protocol (Unified Iteration Standard)

This document defines the single benchmark standard for optimization iteration tracking.

## 1. Baseline Asset

- Baseline image: `test/test_capture.png`
- Benchmark config: `test/benchmark_config.json`
- Ground truth labels: `test/ground_truth.json`
- Benchmark runner: `test/run_benchmark.py`

All future benchmark runs must use this baseline image unless the protocol version is explicitly updated.

## 1.1 Ground Truth Case Schema

Each case in `test/ground_truth.json` should follow:

1. `id`: stable case id
2. `lang`: `zh` or `en`
3. `target`: primary target text (compatibility field)
4. `query_texts`: one or more query variants used for retrieval
5. `expected_texts`: one or more accepted OCR outputs for accuracy judgment
6. `expected_center`: expected click center `[x, y]`
7. `tolerance_px`: position tolerance in pixels

For Chinese-heavy screenshots, always provide Chinese entries with `lang: "zh"` and Chinese `query_texts` / `expected_texts`.

## 2. Evaluation Goal Priority

1. OCR stage efficiency (primary KPI)
2. Text accuracy (guardrail)
3. Position accuracy (guardrail)

Only OCR-stage runtime is used as the optimization success metric.  
Matching and post-processing times are recorded only for diagnostics.

## 3. Metrics Definition

Primary efficiency metrics (from OCR stage):

1. `mean_ocr_sec`
2. `p50_ocr_sec`
3. `p90_ocr_sec`
4. `std_ocr_sec`

Accuracy guardrail metrics:

1. `found_rate`
2. `text_accuracy`
3. `text_accuracy_zh`
4. `text_accuracy_en`
5. `position_accuracy`
6. `mean_position_error_px`

Iteration comparison metrics (current run vs previous run):

1. `delta_ocr_sec`
2. `change_pct`
3. `speedup_vs_previous`
4. `improved`

## 4. Fixed Test Method

1. Keep the same config and ground truth files.
2. Run warmup loops first (`warmup_runs`).
3. Run measurement loops (`measure_runs`) in one runtime mode only.
4. Use `runtime_mode = auto` in config by default:
   - GPU machine: tool will use GPU when available.
   - Non-GPU machine: tool will automatically fall back to CPU.
5. Use the same `min_score`, `threshold`, `topk`, and `case_sensitive` values across optimization iterations.
6. Use the same target list and expected centers from `ground_truth.json`.
7. Do not change the image during a benchmark campaign.

Command:

```powershell
.\.venv\Scripts\python.exe test\run_benchmark.py --config test\benchmark_config.json
```

Optional explicit baseline (manual comparison target):

```powershell
.\.venv\Scripts\python.exe test\run_benchmark.py --config test\benchmark_config.json --baseline test/results/20260302_143224
```

## 5. Result Storage Standard

All benchmark outputs are saved to:

- `test/results/<UTC_TIMESTAMP>/`

Each run directory contains:

1. `benchmark_config_snapshot.json`: exact config used
2. `results.json`: full structured results
3. `raw_runs.csv`: per-run raw OCR and accuracy metrics
4. `summary.md`: quick human-readable summary

`results.json` includes `ground_truth_signature`.  
Iteration comparison is only executed when baseline and current signatures are identical.

Do not overwrite previous result folders.

## 6. Interpretation Rule

Optimization is considered successful only when:

1. `mean_ocr_sec` improves compared with previous run (`delta_ocr_sec < 0`)
2. `text_accuracy_zh`, `text_accuracy_en`, and `position_accuracy` do not regress materially

If OCR speed improves but accuracy drops, mark the iteration as failed and tune parameters before next run.

## 7. Ground Truth Update Rule

When target text or expected position needs correction:

1. Update only `test/ground_truth.json`
2. Keep tolerances explicit (`tolerance_px`)
3. Record a new benchmark run after changes
4. Compare only runs that used the same ground truth revision

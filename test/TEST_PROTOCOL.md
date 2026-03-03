# OCR Benchmark Protocol (Exact-Match Standard)

This document defines the benchmark standard for optimization iteration tracking.

## 1. Baseline Assets

- Baseline default image: `test/test_sample_img/sample_1.png`
- Active benchmark image set: `sample_1.png` + `sample_2.png` + `sample_3.png`
- Benchmark config: `test/benchmark_config.json`
- Ground truth labels: `test/ground_truth.json`
- Benchmark runner: `test/run_benchmark.py`

All benchmark runs must use this image set unless the protocol version is explicitly updated.

Image storage convention:

1. All benchmark screenshots must be stored under `test/test_sample_img/`.
2. Naming format: `sample_<index>.png`.
3. Current default baseline image is `sample_1.png`.
4. `test/benchmark_config.json:image_path` must equal top-level `test/ground_truth.json:image_path`.
5. Additional benchmark images are attached per case using `cases[].image_path`.

## 1.1 Ground Truth Case Schema

Each case in `test/ground_truth.json` should follow:

1. `id`: stable case id.
2. `lang`: `zh` or `en`.
3. `target`: primary target text.
4. `query_texts`: query list. Exact matching mode means literal text forms only.
5. `expected_texts`: accepted OCR outputs for scoring (literal text forms).
6. `expected_center`: expected click center `[x, y]`.
7. `tolerance_px`: position tolerance in pixels.
8. `image_path` (optional): override image path for this case.

Rules:

1. `query_texts[0]` is the primary target for OCR-stage early-stop guidance.
2. Matching mode is literal-text only; do not use semantic containment or alias expansion.
3. Keep `target_center_bias` entries aligned with exact primary targets only.

## 2. Evaluation Priority

1. OCR stage efficiency (primary KPI).
2. Text accuracy (guardrail).
3. Position accuracy (guardrail).

Only OCR-stage runtime is used as optimization success metric.

## 3. Metrics

Primary efficiency metrics:

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

## 4. Fixed Test Method

1. Keep the same config and ground truth files.
2. Enforce `cache_policy = strict_no_cache`.
3. Set `warmup_runs = 0`.
4. Recreate OCR engine for every measured run.
5. Use `runtime_mode = auto`.
6. Keep `min_score`, `threshold`, `topk`, `case_sensitive` fixed across iterations.
7. Do not change benchmark image set during one benchmark campaign.

Current regression-focused cases:

1. `sample2_search_placeholder_en`: exact `Search` hit in low-contrast toolbar.
2. `sample2_free_keyword_zh`: exact `免费试看` hit without partial semantic containment.
3. `sample3_contact_exact_en`: exact `etin Fandi` hit in sample_3.

Command:

```powershell
.\.venv\Scripts\python.exe test\run_benchmark.py --config test\benchmark_config.json
```

## 5. Result Storage Standard

All benchmark outputs are saved to `test/results/<UTC_TIMESTAMP>/`.

Each run directory contains:

1. `benchmark_config_snapshot.json`
2. `results.json`
3. `raw_runs.csv`
4. `raw_runs_overall.csv`
5. `case_results.csv`
6. `summary.md`

## 6. Pass/Fail Rule

Optimization is successful only when:

1. `mean_ocr_sec` improves (`delta_ocr_sec < 0`).
2. `text_accuracy_zh`, `text_accuracy_en`, and `position_accuracy` do not regress materially.

If OCR speed improves but accuracy regresses, the iteration is failed.

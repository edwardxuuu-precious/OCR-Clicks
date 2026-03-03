# Test Suite

This directory contains OCR regression specs and runner scripts.

## Scope

- Image directory: `test/test_sample_img/`
- Runner: `test/run_test_suite.py`
- Active specs:
  - `test/spec_sample_1.json`
  - `test/spec_sample_2.json`

## Spec Notes

- `spec_sample_1.json`: baseline functional and performance regression set.
- `spec_sample_2.json`: additional stability set (9 targets) provided by latest requirement.
  This spec enables `aggressive_dense_scan` for harder screenshots.

## Pass Rules

1. Cases with `expected_found=true` must be detected.
2. Cases with `expected_found=false` must remain undetected.
3. If `expected_center` is provided for a found case, `distance_px <= tolerance_px` must hold.
4. If `expected_center` is not provided, the case is judged by found/not-found only.
5. `overall_pass=True` only when all case checks and performance checks pass.

## Run

Run sample_1:

```powershell
.\.venv\Scripts\python.exe test\run_test_suite.py --spec test/spec_sample_1.json --mode cpu
```

Run sample_2:

```powershell
.\.venv\Scripts\python.exe test\run_test_suite.py --spec test/spec_sample_2.json --mode cpu
```

Run auto mode:

```powershell
.\.venv\Scripts\python.exe test\run_test_suite.py --spec test/spec_sample_2.json --mode auto
```

## Output

Each run writes to `test/results/<UTC_TIMESTAMP>/`:

1. `results.json`
2. `summary.md`

## Matching Policy

- Matching uses exact-only mode with normalization.
- Chinese matching keeps literal matching (no semantic expansion).
- English matching supports case normalization and controlled literal containment.

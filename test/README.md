# Test Suite (Rebuilt)

This `test` directory was rebuilt from scratch based on the latest requirement.

## Scope

- Test image set kept under `test/test_sample_img/`.
- Current active spec is `test/spec_sample_1.json`.
- Current runner is `test/run_test_suite.py`.

## Required Targets (from requirement)

Current sample is validated against these 9 queries on `sample_1.png`:

1. `笛笛宝宝`
2. `在吗`
3. `19:21`
4. `公众号`
5. `常看的号`
6. `天道久远`
7. `一小时前`
8. `余下十条`
9. `今日参考汇率`

## Pass Rules

1. All targets must be found.
2. Coordinates must be within each case tolerance (`distance_px <= tolerance_px`).
3. Recognize + match stage must satisfy:
   - GPU mode <= 4.0 seconds
   - CPU mode <= 12.0 seconds
4. `overall_pass` is `True` only if all above rules pass.

## Run

CPU or auto:

```powershell
.\.venv\Scripts\python.exe test\run_test_suite.py --spec test/spec_sample_1.json --mode auto
```

Force CPU:

```powershell
.\.venv\Scripts\python.exe test\run_test_suite.py --spec test/spec_sample_1.json --mode cpu
```

Force GPU:

```powershell
.\.venv\Scripts\python.exe test\run_test_suite.py --spec test/spec_sample_1.json --mode gpu
```

## Output

Each run writes to `test/results/<UTC_TIMESTAMP>/`:

1. `results.json`
2. `summary.md`
3. Latest consolidated status is tracked in `test/LATEST_RESULT.md`.

## Notes

- Current spec includes all required words.
- If a target does not physically exist in the sample image or OCR cannot extract it, that case remains failed and blocks `overall_pass`.

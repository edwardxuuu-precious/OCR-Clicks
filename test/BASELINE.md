# OCR Baseline (Current)

- Baseline date (UTC): 2026-03-03T03:21:55.957874+00:00
- Baseline run folder: `test/results/20260303_031751`
- Default image: `test/test_sample_img/sample_1.png`
- Active image set: `test/test_sample_img/sample_1.png`, `test/test_sample_img/sample_2.png`
- Runtime actual: `cpu` (gpu_enabled=`False`)
- Ground truth signature (current file): `4b594cd2e4aa7d92ac2b8410f484692a8bee1ef2`

## Efficiency KPI

- mean_ocr_sec: `47.6159`
- p50_ocr_sec: `47.3977`
- p90_ocr_sec: `48.4190`
- std_ocr_sec: `0.6627`

## Accuracy Guardrail

- found_rate: `1.0000`
- text_accuracy: `1.0000`
- text_accuracy_zh: `1.0000`
- text_accuracy_en: `1.0000`
- position_accuracy: `1.0000`
- mean_position_error_px: `1.3299`

## Notes

- Historical folders under `test/results/` were removed.
- This baseline should be used for future iteration comparisons.
- All future benchmark screenshots are stored in `test/test_sample_img/`.
- Current baseline includes regression cases for `Search` placeholder miss and `免费` duplicate-fragment matching.

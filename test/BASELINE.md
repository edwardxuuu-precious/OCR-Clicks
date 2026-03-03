# OCR Baseline (Current)

- Baseline date (UTC): 2026-03-03T06:17:46.696436+00:00
- Baseline run folder: `test/results/20260303_061431`
- Default image: `test/test_sample_img/sample_1.png`
- Active image set: `test/test_sample_img/sample_1.png`, `test/test_sample_img/sample_2.png`, `test/test_sample_img/sample_3.png`
- Runtime actual: `cpu` (gpu_enabled=`False`)
- Ground truth signature (current file): `e83497daf5d23acb77bbc3f088138b5a80bcef7a`

## Efficiency KPI

- mean_ocr_sec: `38.4500`
- p50_ocr_sec: `36.1465`
- p90_ocr_sec: `44.0520`
- std_ocr_sec: `4.4929`

## Accuracy Guardrail

- found_rate: `1.0000`
- text_accuracy: `1.0000`
- text_accuracy_zh: `1.0000`
- text_accuracy_en: `1.0000`
- position_accuracy: `1.0000`
- mean_position_error_px: `0.9104`

## Per-Sample KPI

- sample_1 mean_ocr_sec: `16.8406`
- sample_2 mean_ocr_sec: `18.8740`
- sample_3 mean_ocr_sec: `2.7354`

## Notes

- Matching policy for this baseline is exact-match mode (no semantic/alias matching).
- Included regression cases:
  - `sample2_search_placeholder_en` (exact `Search` hit)
  - `sample2_free_keyword_zh` (exact literal `免费试看` text hit)
  - `sample3_contact_exact_en` (exact `etin Fandi` hit)

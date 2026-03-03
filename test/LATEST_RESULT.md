# Latest Result (CPU)

- Run folder: `test/results/20260303_065215`
- Mode: `cpu`
- Recognize + match: `24.0711s`
- CPU budget target: `12.0s`
- Case pass: `7/9`
- Overall pass: `False`

## Passed Targets

1. `笛笛宝宝`
2. `在吗`
3. `19:21`
4. `公众号`
5. `常看的号`
6. `天道久远`
7. `一小时前` (mapped to OCR text `1小时前` after Chinese numeral normalization)

## Failed Targets

1. `余下十条` -> `not_found`
2. `今日参考汇率` -> `not_found`

## Blocking Facts

1. Current `sample_1.png` OCR output does not contain a literal hit for `余下十条`.
2. Current `sample_1.png` OCR output contains `今日汇率参考(2026/3/2)` but not literal `今日参考汇率`.
3. CPU runtime is currently around `24s` in target-driven mode, above the required `12s`.

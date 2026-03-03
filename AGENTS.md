# AGENTS.md

## Versioning Policy (Timestamp + Index)

The repository must use a single global project version with this format:

- `YYYYMMDD.NNN`
- Example: `20260303.001`
- Canonical source: `VERSION.json`

Field rules in `VERSION.json`:

- `version`: full version string (`YYYYMMDD.NNN`)
- `label`: prefixed display label (`vYYYYMMDD.NNN`)
- `version_date`: release date (`YYYY-MM-DD`)
- `version_index`: integer index (same value as `NNN`)
- `released_at`: full timestamp with timezone offset
- `source_commit`: short commit id used as baseline for this version

Index rules:

1. If the date changes, reset index to `001`.
2. If the date is unchanged and any content/code/doc changes, increment index by `+1`.
3. Do not skip index values.
4. `version`, `label`, and `version_index` must always stay consistent.

## Mandatory Broadcast Rule

After any merged content change, the version update must be broadcast to all version consumers in the same change set.

Broadcast targets:

1. `VERSION.json` (source of truth)
2. `CHANGELOG.md` (new version section with timestamp and change summary)
3. Runtime/version readers (currently `src/project_version.py`)
4. User-visible surfaces:
   - CLI `--version` outputs
   - GUI title/log version display
5. Produced artifacts metadata:
   - GUI saved config payload
   - Benchmark `results.json`
   - Benchmark `summary.md`
   - Benchmark `raw_runs.csv`, `raw_runs_overall.csv`, `case_results.csv`

## Execution Workflow (Required)

When updating version, execute all steps in order:

1. Decide next version number by date + current index policy.
2. Update `VERSION.json` fully (`version`, `label`, `version_date`, `version_index`, `released_at`, `source_commit`).
3. Add/update changelog entry in `CHANGELOG.md` with:
   - exact timestamp
   - version label
   - scope summary
   - commit references
4. Ensure code paths consume `src/project_version.py` instead of hardcoded version literals.
5. Sync metadata output fields in runtime artifacts (config/benchmark outputs).
6. Run verification commands:
   - `python -m py_compile src\\*.py test\\run_benchmark.py`
   - `rg -n "202[0-9]{5}\\.[0-9]{3}|project_version|VERSION.json" -S`
7. Confirm `git status` only contains expected files and no missed version consumers.

## Consistency Guardrails

- Never maintain multiple independent version sources.
- Never bump changelog without bumping `VERSION.json`.
- Never bump `VERSION.json` without updating consumer outputs.
- If any consumer cannot be updated, document the exception in the same PR/commit.

## Benchmark Asset Broadcast Rule

When benchmark image assets are moved/renamed, update all affected code and texts in one change set.

Required sync targets:

1. `test/benchmark_config.json` -> default `image_path`
2. `test/ground_truth.json` -> top-level `image_path` and any affected `cases[].image_path`
3. `test/TEST_PROTOCOL.md` baseline path and folder convention
4. `test/BASELINE.md` baseline image path notes
5. `test/run_benchmark.py` consistency checks (config vs ground truth image path)

Current benchmark image storage convention:

- folder: `test/test_sample_img/`
- file naming: `sample_<index>.png`
- canonical baseline image: `test/test_sample_img/sample_1.png`
- active benchmark image set currently includes: `sample_1.png`, `sample_2.png`

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from desktop_ocr_tool import DesktopOCRTool  # noqa: E402


def _normalize_text(text: str) -> str:
    text = text.lower().strip()
    return re.sub(r"[\s`'\".,:;|_~!@#$%^&*()\-+=\[\]{}<>/?\\]+", "", text)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_path(path_text: str) -> Path:
    p = Path(path_text)
    if p.is_absolute():
        return p
    return (ROOT_DIR / p).resolve()


def _file_sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _safe_rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _contains_cjk(text: str) -> bool:
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            s = str(v).strip()
            if s:
                out.append(s)
        return out
    return []


def _case_query_texts(case: dict[str, Any]) -> list[str]:
    candidates = _as_string_list(case.get("query_texts"))
    if candidates:
        return candidates
    target = str(case.get("target", "")).strip()
    return [target] if target else []


def _case_expected_texts(case: dict[str, Any]) -> list[str]:
    candidates = _as_string_list(case.get("expected_texts"))
    if candidates:
        return candidates
    expected = str(case.get("expected_text", "")).strip()
    if expected:
        return [expected]
    target = str(case.get("target", "")).strip()
    return [target] if target else []


def _case_language(case: dict[str, Any]) -> str:
    lang = str(case.get("lang", "")).strip().lower()
    if lang in {"zh", "en"}:
        return lang
    probe_text = " ".join(_case_query_texts(case) + _case_expected_texts(case))
    return "zh" if _contains_cjk(probe_text) else "en"


def _is_text_match(match_text: str, expected_texts: list[str]) -> tuple[bool, str]:
    match_norm = _normalize_text(match_text)
    if not match_norm:
        return False, ""
    for expected in expected_texts:
        expected_norm = _normalize_text(expected)
        if not expected_norm:
            continue
        if (
            expected_norm == match_norm
            or expected_norm in match_norm
            or match_norm in expected_norm
        ):
            return True, expected
    return False, ""


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * max(0.0, min(1.0, pct))
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _parse_runtime_mode(cfg: dict[str, Any]) -> str:
    mode = str(cfg.get("runtime_mode", "auto")).strip().lower()
    if mode not in {"auto", "gpu", "cpu"}:
        raise ValueError("runtime_mode must be one of: auto, gpu, cpu")
    return mode


def _parse_cache_policy(cfg: dict[str, Any]) -> str:
    policy = str(cfg.get("cache_policy", "strict_no_cache")).strip().lower()
    if policy not in {"strict_no_cache", "normal"}:
        raise ValueError("cache_policy must be one of: strict_no_cache, normal")
    return policy


def _resolve_use_gpu_requested(runtime_mode: str) -> bool:
    # "auto" requests GPU, while DesktopOCRTool handles CPU fallback automatically.
    return runtime_mode != "cpu"


def _parse_center_bias_map(cfg: dict[str, Any]) -> dict[str, list[float] | tuple[float, float]]:
    value = cfg.get("target_center_bias", {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("target_center_bias must be a mapping: {target_text: [dx, dy]}")
    parsed: dict[str, list[float] | tuple[float, float]] = {}
    for k, v in value.items():
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            continue
        parsed[str(k)] = [float(v[0]), float(v[1])]
    return parsed


def _evaluate_case(
    match: dict[str, Any] | None,
    case: dict[str, Any],
    default_tolerance: float,
) -> dict[str, Any]:
    case_id = str(case.get("id", "")).strip() or str(case.get("target", "")).strip()
    query_texts = _case_query_texts(case)
    expected_texts = _case_expected_texts(case)
    case_lang = _case_language(case)
    primary_target = query_texts[0] if query_texts else case_id
    expected_center = case.get("expected_center")
    tolerance_px = float(case.get("tolerance_px", default_tolerance))

    if not match:
        return {
            "id": case_id,
            "target": primary_target,
            "query_texts": query_texts,
            "expected_texts": expected_texts,
            "lang": case_lang,
            "found": False,
            "text_ok": False,
            "expected_text_hit": "",
            "position_eval": bool(expected_center),
            "position_ok": False,
            "distance_px": None,
            "match_text": "",
            "match_score": 0.0,
            "ocr_score": 0.0,
            "center": None,
            "tolerance_px": tolerance_px,
        }

    match_text = str(match.get("match_text", ""))
    text_ok, expected_text_hit = _is_text_match(match_text, expected_texts)

    center = match.get("center")
    distance_px: float | None = None
    position_ok = False
    position_eval = isinstance(expected_center, list) and len(expected_center) == 2
    if position_eval and isinstance(center, list) and len(center) == 2:
        dx = float(center[0]) - float(expected_center[0])
        dy = float(center[1]) - float(expected_center[1])
        distance_px = math.hypot(dx, dy)
        position_ok = distance_px <= tolerance_px

    return {
        "id": case_id,
        "target": primary_target,
        "query_texts": query_texts,
        "expected_texts": expected_texts,
        "lang": case_lang,
        "found": True,
        "text_ok": text_ok,
        "expected_text_hit": expected_text_hit,
        "position_eval": position_eval,
        "position_ok": position_ok,
        "distance_px": distance_px,
        "match_text": match_text,
        "match_score": float(match.get("match_score", 0.0)),
        "ocr_score": float(match.get("ocr_score", 0.0)),
        "center": center,
        "tolerance_px": tolerance_px,
    }


def _run_once(
    tool: DesktopOCRTool,
    *,
    image_path: Path,
    screen_left: int,
    screen_top: int,
    min_score: float,
    threshold: float,
    topk: int,
    case_sensitive: bool,
    default_tolerance: float,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_targets_set: set[str] = set()
    for case in cases:
        case_queries = _case_query_texts(case)
        if case_queries:
            # Use primary query only for OCR-stage early-stop guidance.
            # Alternative queries are for matching tolerance, not mandatory simultaneous presence.
            expected_targets_set.add(case_queries[0])
    expected_targets = sorted(expected_targets_set)

    ocr_started = time.perf_counter()
    items = tool.run_ocr(
        image_path,
        screen_left=screen_left,
        screen_top=screen_top,
        min_score=min_score,
        expected_targets=expected_targets,
        early_stop_threshold=max(0.45, float(threshold) - 0.02),
        priority_tile_limit=2,
    )
    ocr_sec = max(0.0, time.perf_counter() - ocr_started)

    match_index = tool.build_match_index(items, case_sensitive=case_sensitive)

    eval_started = time.perf_counter()
    case_results: list[dict[str, Any]] = []
    for case in cases:
        best: dict[str, Any] | None = None
        best_key: tuple[float, float] = (-1.0, -1.0)
        for query_text in _case_query_texts(case):
            matches = tool.find_text(
                None,
                query_text,
                threshold=threshold,
                case_sensitive=case_sensitive,
                topk=topk,
                preindexed_items=match_index,
            )
            if not matches:
                continue
            candidate = matches[0]
            key = (float(candidate.get("match_score", 0.0)), float(candidate.get("ocr_score", 0.0)))
            if best is None or key > best_key:
                best = candidate
                best_key = key
        case_results.append(_evaluate_case(best, case, default_tolerance))
    eval_sec = max(0.0, time.perf_counter() - eval_started)

    found_count = sum(1 for r in case_results if r["found"])
    text_ok_count = sum(1 for r in case_results if r["text_ok"])
    position_eval_count = sum(1 for r in case_results if r["position_eval"])
    position_ok_count = sum(1 for r in case_results if r["position_ok"])
    distance_values = [float(r["distance_px"]) for r in case_results if r["distance_px"] is not None]
    zh_case_count = sum(1 for r in case_results if r.get("lang") == "zh")
    zh_text_ok_count = sum(1 for r in case_results if r.get("lang") == "zh" and r["text_ok"])
    en_case_count = sum(1 for r in case_results if r.get("lang") == "en")
    en_text_ok_count = sum(1 for r in case_results if r.get("lang") == "en" and r["text_ok"])

    return {
        "ocr_sec": ocr_sec,
        "eval_sec": eval_sec,
        "num_cases": len(case_results),
        "found_count": found_count,
        "text_ok_count": text_ok_count,
        "position_eval_count": position_eval_count,
        "position_ok_count": position_ok_count,
        "mean_distance_px": statistics.mean(distance_values) if distance_values else None,
        "zh_case_count": zh_case_count,
        "zh_text_ok_count": zh_text_ok_count,
        "en_case_count": en_case_count,
        "en_text_ok_count": en_text_ok_count,
        "case_results": case_results,
    }


def _aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    ocr_values = [float(r["ocr_sec"]) for r in runs]
    eval_values = [float(r["eval_sec"]) for r in runs]

    total_cases = sum(int(r["num_cases"]) for r in runs)
    total_found = sum(int(r["found_count"]) for r in runs)
    total_text_ok = sum(int(r["text_ok_count"]) for r in runs)
    total_position_eval = sum(int(r["position_eval_count"]) for r in runs)
    total_position_ok = sum(int(r["position_ok_count"]) for r in runs)
    zh_total_cases = sum(int(r.get("zh_case_count", 0)) for r in runs)
    zh_total_text_ok = sum(int(r.get("zh_text_ok_count", 0)) for r in runs)
    en_total_cases = sum(int(r.get("en_case_count", 0)) for r in runs)
    en_total_text_ok = sum(int(r.get("en_text_ok_count", 0)) for r in runs)
    distance_values = [float(r["mean_distance_px"]) for r in runs if r["mean_distance_px"] is not None]

    def _mean(values: list[float]) -> float:
        return statistics.mean(values) if values else 0.0

    def _std(values: list[float]) -> float:
        return statistics.pstdev(values) if len(values) > 1 else 0.0

    return {
        "runs": len(runs),
        "mean_ocr_sec": _mean(ocr_values),
        "std_ocr_sec": _std(ocr_values),
        "p50_ocr_sec": _percentile(ocr_values, 0.50),
        "p90_ocr_sec": _percentile(ocr_values, 0.90),
        "min_ocr_sec": min(ocr_values) if ocr_values else 0.0,
        "max_ocr_sec": max(ocr_values) if ocr_values else 0.0,
        "mean_eval_sec": _mean(eval_values),
        "found_rate": _safe_rate(total_found, total_cases),
        "text_accuracy": _safe_rate(total_text_ok, total_cases),
        "text_accuracy_zh": _safe_rate(zh_total_text_ok, zh_total_cases),
        "text_accuracy_en": _safe_rate(en_total_text_ok, en_total_cases),
        "position_accuracy": _safe_rate(total_position_ok, total_position_eval),
        "mean_position_error_px": _mean(distance_values) if distance_values else None,
        "total_cases": total_cases,
        "total_found": total_found,
        "total_text_ok": total_text_ok,
        "total_cases_zh": zh_total_cases,
        "total_text_ok_zh": zh_total_text_ok,
        "total_cases_en": en_total_cases,
        "total_text_ok_en": en_total_text_ok,
        "total_position_eval": total_position_eval,
        "total_position_ok": total_position_ok,
    }


def _write_raw_runs_csv(path: Path, runs: list[dict[str, Any]], runtime_info: dict[str, Any]) -> None:
    fields = [
        "run_index",
        "ocr_sec",
        "eval_sec",
        "found_rate",
        "text_accuracy",
        "text_accuracy_zh",
        "text_accuracy_en",
        "position_accuracy",
        "mean_position_error_px",
        "runtime_mode",
        "use_gpu_requested",
        "gpu_enabled",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for idx, run in enumerate(runs, start=1):
            writer.writerow(
                {
                    "run_index": idx,
                    "ocr_sec": f"{float(run['ocr_sec']):.6f}",
                    "eval_sec": f"{float(run['eval_sec']):.6f}",
                    "found_rate": f"{_safe_rate(run['found_count'], run['num_cases']):.6f}",
                    "text_accuracy": f"{_safe_rate(run['text_ok_count'], run['num_cases']):.6f}",
                    "text_accuracy_zh": f"{_safe_rate(run.get('zh_text_ok_count', 0), run.get('zh_case_count', 0)):.6f}",
                    "text_accuracy_en": f"{_safe_rate(run.get('en_text_ok_count', 0), run.get('en_case_count', 0)):.6f}",
                    "position_accuracy": (
                        f"{_safe_rate(run['position_ok_count'], run['position_eval_count']):.6f}"
                        if run["position_eval_count"] > 0
                        else ""
                    ),
                    "mean_position_error_px": (
                        f"{float(run['mean_distance_px']):.6f}" if run["mean_distance_px"] is not None else ""
                    ),
                    "runtime_mode": runtime_info.get("acceleration_mode", ""),
                    "use_gpu_requested": runtime_info.get("use_gpu_requested", False),
                    "gpu_enabled": runtime_info.get("gpu_enabled", False),
                }
            )


def _extract_aggregate_from_result(
    payload: dict[str, Any],
    *,
    prefer_gpu_enabled: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    benchmark = payload.get("benchmark")
    if isinstance(benchmark, dict):
        aggregate = benchmark.get("aggregate")
        runtime_info = benchmark.get("runtime_info")
        if isinstance(aggregate, dict):
            return aggregate, runtime_info if isinstance(runtime_info, dict) else None

    modes = payload.get("modes")
    if isinstance(modes, dict) and modes:
        desired_mode = "gpu" if prefer_gpu_enabled else "cpu"
        selected_key = desired_mode if desired_mode in modes else next(iter(modes.keys()))
        selected = modes.get(selected_key, {})
        aggregate = selected.get("aggregate")
        runtime_info = selected.get("runtime_info")
        if isinstance(aggregate, dict):
            return aggregate, runtime_info if isinstance(runtime_info, dict) else None

    return None, None


def _build_comparison_vs_previous(
    current_aggregate: dict[str, Any],
    previous_aggregate: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not previous_aggregate:
        return None

    current_mean_ocr = float(current_aggregate.get("mean_ocr_sec", 0.0))
    previous_mean_ocr = float(previous_aggregate.get("mean_ocr_sec", 0.0))
    if previous_mean_ocr <= 1e-9:
        return None

    delta_sec = current_mean_ocr - previous_mean_ocr
    change_pct = (delta_sec / previous_mean_ocr) * 100.0
    speedup = previous_mean_ocr / current_mean_ocr if current_mean_ocr > 1e-9 else None

    return {
        "previous_mean_ocr_sec": previous_mean_ocr,
        "current_mean_ocr_sec": current_mean_ocr,
        "delta_ocr_sec": delta_sec,
        "change_pct": change_pct,
        "speedup_vs_previous": speedup,
        "improved": bool(delta_sec < 0),
    }


def _find_latest_previous_result(
    out_root: Path,
    *,
    exclude_dir_name: str,
) -> Path | None:
    candidates: list[Path] = []
    if not out_root.exists():
        return None
    for child in out_root.iterdir():
        if not child.is_dir():
            continue
        if child.name == exclude_dir_name:
            continue
        if (child / "results.json").exists():
            candidates.append(child)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _resolve_baseline_result_path(
    baseline_arg: str | None,
    out_root: Path,
    current_out_dir_name: str,
) -> Path | None:
    if baseline_arg:
        raw = _resolve_path(baseline_arg)
        if raw.is_dir():
            p = raw / "results.json"
            return p if p.exists() else None
        return raw if raw.exists() else None

    previous_dir = _find_latest_previous_result(out_root, exclude_dir_name=current_out_dir_name)
    if not previous_dir:
        return None
    return previous_dir / "results.json"


def _build_summary_markdown(results: dict[str, Any]) -> str:
    benchmark = results["benchmark"]
    runtime = benchmark["runtime_info"]
    aggregate = benchmark["aggregate"]
    comparison = results.get("comparison_vs_previous")
    baseline = results.get("baseline_reference")
    skip_reason = str(results.get("comparison_skip_reason", "")).strip()

    lines: list[str] = []
    lines.append("# OCR Iteration Benchmark Summary")
    lines.append("")
    lines.append(f"- generated_at_utc: {results['generated_at_utc']}")
    lines.append(f"- image: {results['image_path']}")
    lines.append(
        f"- warmup_runs: {results['warmup_runs']}"
        f" (requested={results.get('warmup_runs_requested', results['warmup_runs'])})"
    )
    lines.append(f"- measure_runs: {results['measure_runs']}")
    lines.append(f"- runtime_mode_requested: {results['runtime_mode_requested']}")
    lines.append(f"- cache_policy: {results.get('cache_policy', 'strict_no_cache')}")
    lines.append(f"- recreate_engine_per_run: {results.get('recreate_engine_per_run', False)}")
    lines.append(f"- target_center_bias_enabled: {results.get('target_center_bias_enabled', False)}")
    lines.append(
        f"- runtime_mode_actual: {runtime.get('acceleration_mode')} "
        f"(gpu_enabled={runtime.get('gpu_enabled')})"
    )
    lines.append("")
    lines.append("## OCR Efficiency (Primary KPI)")
    lines.append("")
    lines.append(f"- mean_ocr_sec: {aggregate['mean_ocr_sec']:.4f}")
    lines.append(f"- p50_ocr_sec: {aggregate['p50_ocr_sec']:.4f}")
    lines.append(f"- p90_ocr_sec: {aggregate['p90_ocr_sec']:.4f}")
    lines.append(f"- std_ocr_sec: {aggregate['std_ocr_sec']:.4f}")
    lines.append(f"- min_ocr_sec: {aggregate['min_ocr_sec']:.4f}")
    lines.append(f"- max_ocr_sec: {aggregate['max_ocr_sec']:.4f}")
    lines.append("")
    lines.append("## Accuracy Guardrail")
    lines.append("")
    lines.append(f"- found_rate: {aggregate['found_rate']:.4f}")
    lines.append(f"- text_accuracy: {aggregate['text_accuracy']:.4f}")
    total_cases_zh = int(aggregate.get("total_cases_zh", 0))
    total_cases_en = int(aggregate.get("total_cases_en", 0))
    if total_cases_zh > 0:
        lines.append(f"- text_accuracy_zh: {aggregate.get('text_accuracy_zh', 0.0):.4f} ({total_cases_zh} cases)")
    if total_cases_en > 0:
        lines.append(f"- text_accuracy_en: {aggregate.get('text_accuracy_en', 0.0):.4f} ({total_cases_en} cases)")
    lines.append(f"- position_accuracy: {aggregate['position_accuracy']:.4f}")
    mean_pos = aggregate["mean_position_error_px"]
    lines.append(f"- mean_position_error_px: {mean_pos:.4f}" if mean_pos is not None else "- mean_position_error_px: N/A")
    lines.append("")
    lines.append("## Iteration Comparison")
    lines.append("")
    if comparison and baseline:
        lines.append(f"- baseline_results: {baseline.get('path', '')}")
        if baseline.get("generated_at_utc"):
            lines.append(f"- baseline_generated_at_utc: {baseline['generated_at_utc']}")
        lines.append(f"- previous_mean_ocr_sec: {comparison['previous_mean_ocr_sec']:.4f}")
        lines.append(f"- current_mean_ocr_sec: {comparison['current_mean_ocr_sec']:.4f}")
        lines.append(f"- delta_ocr_sec: {comparison['delta_ocr_sec']:.4f}")
        lines.append(f"- change_pct: {comparison['change_pct']:.2f}%")
        speedup = comparison.get("speedup_vs_previous")
        lines.append(f"- speedup_vs_previous: {speedup:.4f}x" if isinstance(speedup, float) else "- speedup_vs_previous: N/A")
        lines.append(f"- improved: {comparison['improved']}")
    else:
        lines.append("- baseline_results: N/A")
        if skip_reason:
            lines.append(f"- comparison: skipped ({skip_reason})")
        else:
            lines.append("- comparison: skipped (no previous comparable result found)")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run standardized OCR benchmark (OCR efficiency focused).")
    parser.add_argument("--config", type=str, default="test/benchmark_config.json", help="Path to benchmark config.")
    parser.add_argument(
        "--out-root",
        type=str,
        default="test/results",
        help="Root directory where timestamped benchmark results are stored.",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default="",
        help="Optional baseline path (result directory or results.json). Defaults to latest previous result.",
    )
    args = parser.parse_args()

    cfg_path = _resolve_path(args.config)
    cfg = _load_json(cfg_path)

    image_path = _resolve_path(str(cfg["image_path"]))
    if not image_path.exists():
        raise FileNotFoundError(f"Benchmark image not found: {image_path}")

    gt_path = _resolve_path(str(cfg["ground_truth_path"]))
    gt = _load_json(gt_path)
    ground_truth_signature = _file_sha1(gt_path)
    cases: list[dict[str, Any]] = list(gt.get("cases", []))
    if not cases:
        raise ValueError(f"No benchmark cases found in ground truth file: {gt_path}")

    warmup_runs = int(cfg.get("warmup_runs", 1))
    measure_runs = int(cfg.get("measure_runs", 5))
    runtime_mode = _parse_runtime_mode(cfg)
    cache_policy = _parse_cache_policy(cfg)
    recreate_engine_per_run = cache_policy == "strict_no_cache"
    center_bias_map = _parse_center_bias_map(cfg)
    use_gpu = _resolve_use_gpu_requested(runtime_mode)
    compare_with_previous = bool(cfg.get("compare_with_previous", True))
    screen_left = int(cfg.get("screen_left", 0))
    screen_top = int(cfg.get("screen_top", 0))
    min_score = float(cfg.get("min_score", 0.35))
    threshold = float(cfg.get("threshold", 0.62))
    topk = int(cfg.get("topk", 5))
    case_sensitive = bool(cfg.get("case_sensitive", False))
    position_tolerance_px = float(cfg.get("position_tolerance_px", 35))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_root = _resolve_path(args.out_root)
    out_dir = out_root / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    runtime_info: dict[str, Any] = {}
    effective_warmup_runs = max(0, warmup_runs)
    if recreate_engine_per_run and effective_warmup_runs > 0:
        # In strict no-cache mode, warmup itself would bias timing.
        effective_warmup_runs = 0

    if recreate_engine_per_run:
        for _ in range(effective_warmup_runs):
            warm_tool = DesktopOCRTool(use_gpu=use_gpu, center_bias_map=center_bias_map)
            _ = warm_tool.get_runtime_info()
            _run_once(
                warm_tool,
                image_path=image_path,
                screen_left=screen_left,
                screen_top=screen_top,
                min_score=min_score,
                threshold=threshold,
                topk=topk,
                case_sensitive=case_sensitive,
                default_tolerance=position_tolerance_px,
                cases=cases,
            )
    else:
        tool = DesktopOCRTool(use_gpu=use_gpu, center_bias_map=center_bias_map)
        runtime_info = tool.get_runtime_info()
        for _ in range(effective_warmup_runs):
            _run_once(
                tool,
                image_path=image_path,
                screen_left=screen_left,
                screen_top=screen_top,
                min_score=min_score,
                threshold=threshold,
                topk=topk,
                case_sensitive=case_sensitive,
                default_tolerance=position_tolerance_px,
                cases=cases,
            )

    runs: list[dict[str, Any]] = []
    for _ in range(max(1, measure_runs)):
        if recreate_engine_per_run:
            run_tool = DesktopOCRTool(use_gpu=use_gpu, center_bias_map=center_bias_map)
            if not runtime_info:
                runtime_info = run_tool.get_runtime_info()
            runs.append(
                _run_once(
                    run_tool,
                    image_path=image_path,
                    screen_left=screen_left,
                    screen_top=screen_top,
                    min_score=min_score,
                    threshold=threshold,
                    topk=topk,
                    case_sensitive=case_sensitive,
                    default_tolerance=position_tolerance_px,
                    cases=cases,
                )
            )
        else:
            runs.append(
                _run_once(
                    tool,
                    image_path=image_path,
                    screen_left=screen_left,
                    screen_top=screen_top,
                    min_score=min_score,
                    threshold=threshold,
                    topk=topk,
                    case_sensitive=case_sensitive,
                    default_tolerance=position_tolerance_px,
                    cases=cases,
                )
            )
    if not runtime_info:
        runtime_info = DesktopOCRTool(use_gpu=use_gpu, center_bias_map=center_bias_map).get_runtime_info()
    aggregate = _aggregate_runs(runs)

    baseline_reference: dict[str, Any] | None = None
    comparison_vs_previous: dict[str, Any] | None = None
    comparison_skip_reason = ""
    if compare_with_previous:
        baseline_arg = args.baseline.strip() if args.baseline else str(cfg.get("baseline_result_path", "")).strip()
        baseline_results_path = _resolve_baseline_result_path(
            baseline_arg if baseline_arg else None,
            out_root,
            out_dir.name,
        )
        if baseline_results_path and baseline_results_path.exists():
            previous_payload = _load_json(baseline_results_path)
            previous_signature = str(previous_payload.get("ground_truth_signature", "")).strip()
            previous_cache_policy = str(previous_payload.get("cache_policy", "")).strip().lower()
            if previous_cache_policy != cache_policy:
                comparison_skip_reason = "cache_policy_mismatch"
            elif not previous_signature:
                comparison_skip_reason = "baseline_missing_ground_truth_signature"
            elif previous_signature != ground_truth_signature:
                comparison_skip_reason = "ground_truth_signature_mismatch"
            else:
                previous_aggregate, previous_runtime = _extract_aggregate_from_result(
                    previous_payload,
                    prefer_gpu_enabled=bool(runtime_info.get("gpu_enabled", False)),
                )
                comparison_vs_previous = _build_comparison_vs_previous(aggregate, previous_aggregate)
                if previous_aggregate:
                    baseline_reference = {
                        "path": str(baseline_results_path),
                        "generated_at_utc": previous_payload.get("generated_at_utc", ""),
                        "runtime_info": previous_runtime or {},
                        "aggregate": previous_aggregate,
                    }

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(cfg_path),
        "image_path": str(image_path),
        "ground_truth_path": str(gt_path),
        "ground_truth_signature": ground_truth_signature,
        "warmup_runs_requested": warmup_runs,
        "warmup_runs": effective_warmup_runs,
        "measure_runs": measure_runs,
        "runtime_mode_requested": runtime_mode,
        "cache_policy": cache_policy,
        "recreate_engine_per_run": recreate_engine_per_run,
        "target_center_bias_enabled": bool(center_bias_map),
        "benchmark": {
            "runtime_info": runtime_info,
            "runs": runs,
            "aggregate": aggregate,
        },
        "baseline_reference": baseline_reference,
        "comparison_vs_previous": comparison_vs_previous,
        "comparison_skip_reason": comparison_skip_reason,
    }

    (out_dir / "benchmark_config_snapshot.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_raw_runs_csv(out_dir / "raw_runs.csv", runs, runtime_info)
    (out_dir / "summary.md").write_text(_build_summary_markdown(payload), encoding="utf-8")

    print(f"Benchmark completed. Results stored at: {out_dir}")


if __name__ == "__main__":
    main()

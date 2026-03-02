from __future__ import annotations

import argparse
import csv
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


def _safe_rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _evaluate_case(
    match: dict[str, Any] | None,
    case: dict[str, Any],
    default_tolerance: float,
) -> dict[str, Any]:
    target = str(case["target"])
    expected_text = str(case.get("expected_text", target))
    expected_center = case.get("expected_center")
    tolerance_px = float(case.get("tolerance_px", default_tolerance))

    if not match:
        return {
            "target": target,
            "found": False,
            "text_ok": False,
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
    target_norm = _normalize_text(expected_text)
    match_norm = _normalize_text(match_text)
    text_ok = bool(target_norm) and (
        target_norm == match_norm or target_norm in match_norm or match_norm in target_norm
    )

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
        "target": target,
        "found": True,
        "text_ok": text_ok,
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
    total_started = time.perf_counter()

    ocr_started = time.perf_counter()
    items = tool.run_ocr(
        image_path,
        screen_left=screen_left,
        screen_top=screen_top,
        min_score=min_score,
    )
    ocr_sec = max(0.0, time.perf_counter() - ocr_started)

    match_index = tool.build_match_index(items, case_sensitive=case_sensitive)

    match_started = time.perf_counter()
    case_results: list[dict[str, Any]] = []
    for case in cases:
        target = str(case["target"])
        matches = tool.find_text(
            None,
            target,
            threshold=threshold,
            case_sensitive=case_sensitive,
            topk=topk,
            preindexed_items=match_index,
        )
        best = matches[0] if matches else None
        case_results.append(_evaluate_case(best, case, default_tolerance))
    match_sec = max(0.0, time.perf_counter() - match_started)

    total_sec = max(0.0, time.perf_counter() - total_started)

    found_count = sum(1 for r in case_results if r["found"])
    text_ok_count = sum(1 for r in case_results if r["text_ok"])
    position_eval_count = sum(1 for r in case_results if r["position_eval"])
    position_ok_count = sum(1 for r in case_results if r["position_ok"])
    distance_values = [float(r["distance_px"]) for r in case_results if r["distance_px"] is not None]

    return {
        "total_sec": total_sec,
        "ocr_sec": ocr_sec,
        "match_sec": match_sec,
        "num_cases": len(case_results),
        "found_count": found_count,
        "text_ok_count": text_ok_count,
        "position_eval_count": position_eval_count,
        "position_ok_count": position_ok_count,
        "mean_distance_px": statistics.mean(distance_values) if distance_values else None,
        "case_results": case_results,
    }


def _aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    total_values = [float(r["total_sec"]) for r in runs]
    ocr_values = [float(r["ocr_sec"]) for r in runs]
    match_values = [float(r["match_sec"]) for r in runs]

    total_cases = sum(int(r["num_cases"]) for r in runs)
    total_found = sum(int(r["found_count"]) for r in runs)
    total_text_ok = sum(int(r["text_ok_count"]) for r in runs)
    total_position_eval = sum(int(r["position_eval_count"]) for r in runs)
    total_position_ok = sum(int(r["position_ok_count"]) for r in runs)
    distance_values = [float(r["mean_distance_px"]) for r in runs if r["mean_distance_px"] is not None]

    def _mean(values: list[float]) -> float:
        return statistics.mean(values) if values else 0.0

    def _std(values: list[float]) -> float:
        return statistics.pstdev(values) if len(values) > 1 else 0.0

    return {
        "runs": len(runs),
        "mean_total_sec": _mean(total_values),
        "std_total_sec": _std(total_values),
        "mean_ocr_sec": _mean(ocr_values),
        "std_ocr_sec": _std(ocr_values),
        "mean_match_sec": _mean(match_values),
        "std_match_sec": _std(match_values),
        "found_rate": _safe_rate(total_found, total_cases),
        "text_accuracy": _safe_rate(total_text_ok, total_cases),
        "position_accuracy": _safe_rate(total_position_ok, total_position_eval),
        "mean_position_error_px": _mean(distance_values) if distance_values else None,
        "total_cases": total_cases,
        "total_found": total_found,
        "total_text_ok": total_text_ok,
        "total_position_eval": total_position_eval,
        "total_position_ok": total_position_ok,
    }


def _write_raw_runs_csv(path: Path, mode_results: dict[str, Any]) -> None:
    fields = [
        "mode",
        "run_index",
        "total_sec",
        "ocr_sec",
        "match_sec",
        "found_rate",
        "text_accuracy",
        "position_accuracy",
        "mean_position_error_px",
        "runtime_mode",
        "use_gpu_requested",
        "gpu_enabled",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for mode, payload in mode_results.items():
            aggregate = payload["aggregate"]
            for idx, run in enumerate(payload["runs"], start=1):
                writer.writerow(
                    {
                        "mode": mode,
                        "run_index": idx,
                        "total_sec": f"{float(run['total_sec']):.6f}",
                        "ocr_sec": f"{float(run['ocr_sec']):.6f}",
                        "match_sec": f"{float(run['match_sec']):.6f}",
                        "found_rate": f"{_safe_rate(run['found_count'], run['num_cases']):.6f}",
                        "text_accuracy": f"{_safe_rate(run['text_ok_count'], run['num_cases']):.6f}",
                        "position_accuracy": (
                            f"{_safe_rate(run['position_ok_count'], run['position_eval_count']):.6f}"
                            if run["position_eval_count"] > 0
                            else ""
                        ),
                        "mean_position_error_px": (
                            f"{float(run['mean_distance_px']):.6f}"
                            if run["mean_distance_px"] is not None
                            else ""
                        ),
                        "runtime_mode": payload["runtime_info"].get("acceleration_mode", ""),
                        "use_gpu_requested": payload["runtime_info"].get("use_gpu_requested", False),
                        "gpu_enabled": payload["runtime_info"].get("gpu_enabled", False),
                    }
                )
            writer.writerow(
                {
                    "mode": f"{mode}_aggregate",
                    "run_index": aggregate["runs"],
                    "total_sec": f"{aggregate['mean_total_sec']:.6f}",
                    "ocr_sec": f"{aggregate['mean_ocr_sec']:.6f}",
                    "match_sec": f"{aggregate['mean_match_sec']:.6f}",
                    "found_rate": f"{aggregate['found_rate']:.6f}",
                    "text_accuracy": f"{aggregate['text_accuracy']:.6f}",
                    "position_accuracy": f"{aggregate['position_accuracy']:.6f}",
                    "mean_position_error_px": (
                        f"{aggregate['mean_position_error_px']:.6f}"
                        if aggregate["mean_position_error_px"] is not None
                        else ""
                    ),
                    "runtime_mode": payload["runtime_info"].get("acceleration_mode", ""),
                    "use_gpu_requested": payload["runtime_info"].get("use_gpu_requested", False),
                    "gpu_enabled": payload["runtime_info"].get("gpu_enabled", False),
                }
            )


def _build_summary_markdown(results: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# OCR Benchmark Summary")
    lines.append("")
    lines.append(f"- generated_at_utc: {results['generated_at_utc']}")
    lines.append(f"- image: {results['image_path']}")
    lines.append(f"- warmup_runs: {results['warmup_runs']}")
    lines.append(f"- measure_runs: {results['measure_runs']}")
    lines.append("")
    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append("| mode | mean_total_s | mean_ocr_s | mean_match_s | found_rate | text_accuracy | position_accuracy | mean_pos_err_px |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for mode, payload in results["modes"].items():
        agg = payload["aggregate"]
        mean_pos = agg["mean_position_error_px"]
        lines.append(
            "| "
            + " | ".join(
                [
                    mode,
                    f"{agg['mean_total_sec']:.4f}",
                    f"{agg['mean_ocr_sec']:.4f}",
                    f"{agg['mean_match_sec']:.4f}",
                    f"{agg['found_rate']:.4f}",
                    f"{agg['text_accuracy']:.4f}",
                    f"{agg['position_accuracy']:.4f}",
                    f"{mean_pos:.4f}" if mean_pos is not None else "N/A",
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Runtime Info")
    lines.append("")
    for mode, payload in results["modes"].items():
        runtime = payload["runtime_info"]
        lines.append(f"- {mode}: mode={runtime.get('acceleration_mode')}, gpu_enabled={runtime.get('gpu_enabled')}")
    lines.append("")
    comparison = results.get("comparison", {})
    if comparison:
        lines.append("## Mode Comparison")
        lines.append("")
        for key, value in comparison.items():
            if isinstance(value, float):
                lines.append(f"- {key}: {value:.4f}")
            else:
                lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run standardized OCR speed and accuracy benchmark.")
    parser.add_argument("--config", type=str, default="test/benchmark_config.json", help="Path to benchmark config.")
    parser.add_argument(
        "--out-root",
        type=str,
        default="test/results",
        help="Root directory where timestamped benchmark results are stored.",
    )
    args = parser.parse_args()

    cfg_path = _resolve_path(args.config)
    cfg = _load_json(cfg_path)

    image_path = _resolve_path(str(cfg["image_path"]))
    if not image_path.exists():
        raise FileNotFoundError(f"Benchmark image not found: {image_path}")

    gt_path = _resolve_path(str(cfg["ground_truth_path"]))
    gt = _load_json(gt_path)
    cases: list[dict[str, Any]] = list(gt.get("cases", []))
    if not cases:
        raise ValueError(f"No benchmark cases found in ground truth file: {gt_path}")

    warmup_runs = int(cfg.get("warmup_runs", 1))
    measure_runs = int(cfg.get("measure_runs", 5))
    modes = [str(m).lower().strip() for m in cfg.get("modes", ["gpu", "cpu"])]
    screen_left = int(cfg.get("screen_left", 0))
    screen_top = int(cfg.get("screen_top", 0))
    min_score = float(cfg.get("min_score", 0.35))
    threshold = float(cfg.get("threshold", 0.62))
    topk = int(cfg.get("topk", 5))
    case_sensitive = bool(cfg.get("case_sensitive", False))
    position_tolerance_px = float(cfg.get("position_tolerance_px", 35))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = _resolve_path(args.out_root) / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    mode_results: dict[str, Any] = {}
    for mode in modes:
        use_gpu = mode == "gpu"
        tool = DesktopOCRTool(use_gpu=use_gpu)
        runtime_info = tool.get_runtime_info()

        for _ in range(max(0, warmup_runs)):
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

        mode_results[mode] = {
            "runtime_info": runtime_info,
            "runs": runs,
            "aggregate": _aggregate_runs(runs),
        }

    comparison: dict[str, Any] = {}
    gpu_agg = mode_results.get("gpu", {}).get("aggregate")
    cpu_agg = mode_results.get("cpu", {}).get("aggregate")
    if gpu_agg and cpu_agg:
        gpu_total = float(gpu_agg["mean_total_sec"])
        cpu_total = float(cpu_agg["mean_total_sec"])
        gpu_ocr = float(gpu_agg["mean_ocr_sec"])
        cpu_ocr = float(cpu_agg["mean_ocr_sec"])
        comparison["speedup_total_gpu_vs_cpu"] = (cpu_total / gpu_total) if gpu_total > 1e-9 else None
        comparison["speedup_ocr_gpu_vs_cpu"] = (cpu_ocr / gpu_ocr) if gpu_ocr > 1e-9 else None
        comparison["text_accuracy_delta_gpu_minus_cpu"] = float(gpu_agg["text_accuracy"]) - float(cpu_agg["text_accuracy"])
        comparison["position_accuracy_delta_gpu_minus_cpu"] = float(gpu_agg["position_accuracy"]) - float(cpu_agg["position_accuracy"])

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(cfg_path),
        "image_path": str(image_path),
        "ground_truth_path": str(gt_path),
        "warmup_runs": warmup_runs,
        "measure_runs": measure_runs,
        "modes": mode_results,
        "comparison": comparison,
    }

    (out_dir / "benchmark_config_snapshot.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_raw_runs_csv(out_dir / "raw_runs.csv", mode_results)
    (out_dir / "summary.md").write_text(_build_summary_markdown(payload), encoding="utf-8")

    print(f"Benchmark completed. Results stored at: {out_dir}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from desktop_ocr_tool import DesktopOCRTool  # noqa: E402
from project_version import PROJECT_VERSION_LABEL  # noqa: E402


@dataclass
class CaseResult:
    id: str
    query: str
    expected_found: bool
    found: bool
    match_text: str
    center: list[int] | None
    match_score: float
    ocr_score: float
    expected_center: list[int] | None
    tolerance_px: float
    distance_px: float | None
    position_ok: bool
    case_pass: bool
    fail_reason: str


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve(path_text: str) -> Path:
    p = Path(path_text)
    if p.is_absolute():
        return p
    return (ROOT_DIR / p).resolve()


def _parse_mode(raw: str) -> str:
    mode = raw.strip().lower()
    if mode not in {"auto", "cpu", "gpu"}:
        raise ValueError("mode must be one of: auto, cpu, gpu")
    return mode


def _mode_use_gpu(mode: str) -> bool:
    return mode != "cpu"


def _distance(a: list[int], b: list[int]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _evaluate_case(
    tool: DesktopOCRTool,
    match_index: list[dict[str, Any]],
    *,
    query: str,
    case_id: str,
    expected_found: bool,
    threshold: float,
    topk: int,
    expected_center: list[int] | None,
    tolerance_px: float,
) -> CaseResult:
    matches = tool.find_text(
        None,
        query,
        threshold=threshold,
        topk=max(1, int(topk)),
        case_sensitive=False,
        exact_only=True,
        preindexed_items=match_index,
    )

    if not matches:
        missing_is_expected = not expected_found
        return CaseResult(
            id=case_id,
            query=query,
            expected_found=expected_found,
            found=False,
            match_text="",
            center=None,
            match_score=0.0,
            ocr_score=0.0,
            expected_center=expected_center,
            tolerance_px=tolerance_px,
            distance_px=None,
            position_ok=missing_is_expected,
            case_pass=missing_is_expected,
            fail_reason="" if missing_is_expected else "not_found",
        )

    best = matches[0]
    if not expected_found:
        return CaseResult(
            id=case_id,
            query=query,
            expected_found=expected_found,
            found=True,
            match_text=str(best.get("match_text", "")),
            center=best.get("center"),
            match_score=float(best.get("match_score", 0.0)),
            ocr_score=float(best.get("ocr_score", 0.0)),
            expected_center=expected_center,
            tolerance_px=tolerance_px,
            distance_px=None,
            position_ok=False,
            case_pass=False,
            fail_reason="unexpected_found",
        )

    center = best.get("center")
    center_pt = center if isinstance(center, list) and len(center) == 2 else None
    if center_pt is None:
        return CaseResult(
            id=case_id,
            query=query,
            expected_found=expected_found,
            found=True,
            match_text=str(best.get("match_text", "")),
            center=None,
            match_score=float(best.get("match_score", 0.0)),
            ocr_score=float(best.get("ocr_score", 0.0)),
            expected_center=expected_center,
            tolerance_px=tolerance_px,
            distance_px=None,
            position_ok=False,
            case_pass=False,
            fail_reason="invalid_center",
        )

    if not isinstance(expected_center, list) or len(expected_center) != 2:
        return CaseResult(
            id=case_id,
            query=query,
            expected_found=expected_found,
            found=True,
            match_text=str(best.get("match_text", "")),
            center=center_pt,
            match_score=float(best.get("match_score", 0.0)),
            ocr_score=float(best.get("ocr_score", 0.0)),
            expected_center=None,
            tolerance_px=tolerance_px,
            distance_px=None,
            position_ok=True,
            case_pass=True,
            fail_reason="",
        )

    dist = _distance(center_pt, expected_center)
    pos_ok = dist <= tolerance_px
    return CaseResult(
        id=case_id,
        query=query,
        expected_found=expected_found,
        found=True,
        match_text=str(best.get("match_text", "")),
        center=center_pt,
        match_score=float(best.get("match_score", 0.0)),
        ocr_score=float(best.get("ocr_score", 0.0)),
        expected_center=expected_center,
        tolerance_px=tolerance_px,
        distance_px=dist,
        position_ok=pos_ok,
        case_pass=pos_ok,
        fail_reason="" if pos_ok else "position_out_of_tolerance",
    )


def _run_once(spec: dict[str, Any], *, mode: str) -> dict[str, Any]:
    ocr_cfg = dict(spec.get("ocr_config", {}))
    image_path = _resolve(str(spec["image_path"]))
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    cases = list(spec.get("cases", []))
    queries = [
        str(c.get("query", "")).strip()
        for c in cases
        if str(c.get("query", "")).strip() and bool(c.get("expected_found", True))
    ]

    tool = DesktopOCRTool(use_gpu=_mode_use_gpu(mode))
    runtime = tool.get_runtime_info()
    active_mode = str(runtime.get("acceleration_mode", "cpu")).lower()

    ocr_started = time.perf_counter()
    items = tool.run_ocr(
        image_path,
        screen_left=int(ocr_cfg.get("screen_left", 0)),
        screen_top=int(ocr_cfg.get("screen_top", 0)),
        min_score=float(ocr_cfg.get("min_score", 0.35)),
        expected_targets=queries if bool(ocr_cfg.get("use_target_driven_ocr", False)) else [],
        early_stop_threshold=max(0.30, float(ocr_cfg.get("threshold", 0.62)) - 0.04),
        priority_tile_limit=max(1, int(ocr_cfg.get("priority_tile_limit", 3))),
        scan_max_side_override=ocr_cfg.get("scan_max_side"),
        aggressive_dense_scan=bool(ocr_cfg.get("aggressive_dense_scan", False)),
    )
    ocr_sec = max(0.0, time.perf_counter() - ocr_started)

    match_started = time.perf_counter()
    match_index = tool.build_match_index(items, case_sensitive=False)
    case_results: list[CaseResult] = []
    for case in cases:
        case_results.append(
            _evaluate_case(
                tool,
                match_index,
                query=str(case.get("query", "")).strip(),
                case_id=str(case.get("id", "")).strip() or str(case.get("query", "")).strip(),
                expected_found=bool(case.get("expected_found", True)),
                threshold=float(ocr_cfg.get("threshold", 0.62)),
                topk=int(ocr_cfg.get("topk", 30)),
                expected_center=case.get("expected_center"),
                tolerance_px=float(case.get("tolerance_px", 60.0)),
            )
        )
    match_sec = max(0.0, time.perf_counter() - match_started)
    stage_sec = ocr_sec + match_sec

    budget = float(spec.get("mode_time_budget_sec", {}).get(active_mode, float("inf")))
    perf_ok = stage_sec <= budget
    case_passes = sum(1 for c in case_results if c.case_pass)
    all_cases_ok = case_passes == len(case_results)

    return {
        "mode_requested": mode,
        "mode_actual": active_mode,
        "runtime": runtime,
        "ocr_items": len(items),
        "ocr_sec": ocr_sec,
        "match_sec": match_sec,
        "recognize_match_sec": stage_sec,
        "time_budget_sec": budget,
        "performance_ok": perf_ok,
        "case_total": len(case_results),
        "case_pass": case_passes,
        "all_cases_ok": all_cases_ok,
        "overall_pass": all_cases_ok and perf_ok,
        "cases": [asdict(c) for c in case_results],
    }


def _save_outputs(spec: dict[str, Any], payload: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines: list[str] = []
    lines.append("# Test Summary")
    lines.append("")
    lines.append(f"- project_version: {PROJECT_VERSION_LABEL}")
    lines.append(f"- generated_at_utc: {payload['generated_at_utc']}")
    lines.append(f"- spec: {payload['spec_name']}")
    lines.append(f"- image: {payload['image_path']}")
    lines.append(f"- mode_requested: {payload['run']['mode_requested']}")
    lines.append(f"- mode_actual: {payload['run']['mode_actual']}")
    lines.append(f"- ocr_items: {payload['run']['ocr_items']}")
    lines.append(f"- ocr_sec: {payload['run']['ocr_sec']:.4f}")
    lines.append(f"- match_sec: {payload['run']['match_sec']:.4f}")
    lines.append(f"- recognize_match_sec: {payload['run']['recognize_match_sec']:.4f}")
    lines.append(f"- time_budget_sec: {payload['run']['time_budget_sec']:.4f}")
    lines.append(f"- performance_ok: {payload['run']['performance_ok']}")
    lines.append(f"- case_pass: {payload['run']['case_pass']}/{payload['run']['case_total']}")
    lines.append(f"- overall_pass: {payload['run']['overall_pass']}")
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    for case in payload["run"]["cases"]:
        query_esc = str(case["query"]).encode("unicode_escape").decode("ascii")
        lines.append(
            (
                f"- {case['id']}: query=`{case['query']}` query_u=`{query_esc}` found={case['found']} "
                f"expected_found={case['expected_found']} "
                f"position_ok={case['position_ok']} case_pass={case['case_pass']} "
                f"center={case['center']} expected={case['expected_center']} "
                f"distance_px={case['distance_px']} fail_reason={case['fail_reason']}"
            )
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run screenshot exact-match test suite.")
    parser.add_argument("--spec", default="test/spec_sample_1.json", help="Spec JSON path.")
    parser.add_argument("--mode", default="auto", help="auto|cpu|gpu")
    parser.add_argument("--out-dir", default="", help="Output directory. Default: test/results/<timestamp>")
    args = parser.parse_args()

    spec_path = _resolve(str(args.spec))
    spec = _load_json(spec_path)
    mode = _parse_mode(str(args.mode))

    run = _run_once(spec, mode=mode)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "spec_path": str(spec_path),
        "spec_name": str(spec.get("name", "unnamed_spec")),
        "image_path": str(_resolve(str(spec["image_path"]))),
        "run": run,
    }

    if args.out_dir:
        out_dir = _resolve(str(args.out_dir))
    else:
        out_dir = ROOT_DIR / "test" / "results" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _save_outputs(spec, payload, out_dir)
    print(f"Test completed. Results stored at: {out_dir}")


if __name__ == "__main__":
    main()

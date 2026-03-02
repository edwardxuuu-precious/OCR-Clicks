from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR


@dataclass
class CaptureResult:
    image_path: str
    width: int
    height: int
    left: int
    top: int
    timestamp: float


@dataclass
class OCRItem:
    text: str
    score: float
    box: list[list[int]]
    center: list[int]
    left: int
    top: int
    right: int
    bottom: int


class DesktopOCRTool:
    def __init__(self) -> None:
        self.acceleration_mode, self.available_providers, runtime_kwargs = self._detect_runtime()
        self.ocr_engine = RapidOCR(**runtime_kwargs)

    @staticmethod
    def _detect_runtime() -> tuple[str, list[str], dict[str, Any]]:
        providers: list[str] = []
        kwargs: dict[str, Any] = {}
        mode = "cpu"
        try:
            import onnxruntime as ort

            providers = list(ort.get_available_providers())
        except Exception:
            return mode, providers, kwargs

        if "CUDAExecutionProvider" in providers:
            mode = "cuda"
            kwargs.update(
                {
                    "det_use_cuda": True,
                    "cls_use_cuda": True,
                    "rec_use_cuda": True,
                }
            )
            return mode, providers, kwargs

        if "DmlExecutionProvider" in providers:
            mode = "dml"
            kwargs.update(
                {
                    "det_use_dml": True,
                    "cls_use_dml": True,
                    "rec_use_dml": True,
                }
            )
            return mode, providers, kwargs

        cpu_count = os.cpu_count() or 4
        kwargs["intra_op_num_threads"] = max(1, min(12, cpu_count))
        kwargs["inter_op_num_threads"] = 1
        return mode, providers, kwargs

    def get_runtime_info(self) -> dict[str, Any]:
        return {
            "acceleration_mode": self.acceleration_mode,
            "providers": self.available_providers,
        }

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        text = text.lower().strip()
        # Remove spaces and lightweight punctuation noise before fuzzy matching.
        return re.sub(r"[\s`'\".,:;|_~!@#$%^&*()\-+=\[\]{}<>/?\\]+", "", text)

    @staticmethod
    def _enhance_for_dark_ui(bgr: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(gray)
        # Keep 3 channels for OCR model compatibility.
        return cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)

    @staticmethod
    def _tile_positions(total: int, tile: int, overlap: int) -> list[int]:
        if total <= tile:
            return [0]
        step = max(1, tile - overlap)
        positions = list(range(0, max(1, total - tile + 1), step))
        tail = total - tile
        if not positions or positions[-1] != tail:
            positions.append(tail)
        return positions

    @staticmethod
    def _bbox_iou(a: OCRItem, b: OCRItem) -> float:
        x1 = max(a.left, b.left)
        y1 = max(a.top, b.top)
        x2 = min(a.right, b.right)
        y2 = min(a.bottom, b.bottom)
        inter_w = max(0, x2 - x1)
        inter_h = max(0, y2 - y1)
        inter = inter_w * inter_h
        if inter == 0:
            return 0.0
        area_a = max(1, (a.right - a.left) * (a.bottom - a.top))
        area_b = max(1, (b.right - b.left) * (b.bottom - b.top))
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def _collect_ocr_items(
        self,
        image: np.ndarray,
        *,
        screen_left: int,
        screen_top: int,
        min_score: float,
        scale: float = 1.0,
        coord_scale: float = 1.0,
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> list[OCRItem]:
        if scale != 1.0:
            work = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        else:
            work = image

        result, _ = self.ocr_engine(work)
        if not result:
            return []

        inv_scale = 1.0 / max(scale * coord_scale, 1e-6)
        items: list[OCRItem] = []
        for line in result:
            box_raw, text_raw, score_raw = line
            score = float(score_raw)
            if score < min_score:
                continue

            box: list[list[int]] = []
            for pt in box_raw:
                px = int(round(float(pt[0]) * inv_scale)) + offset_x + screen_left
                py = int(round(float(pt[1]) * inv_scale)) + offset_y + screen_top
                box.append([px, py])

            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            left = int(min(xs))
            right = int(max(xs))
            top = int(min(ys))
            bottom = int(max(ys))
            center = [int((left + right) / 2), int((top + bottom) / 2)]

            items.append(
                OCRItem(
                    text=str(text_raw),
                    score=score,
                    box=box,
                    center=center,
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                )
            )
        return items

    def _deduplicate_items(self, items: list[OCRItem]) -> list[OCRItem]:
        if not items:
            return []
        sorted_items = sorted(items, key=lambda x: x.score, reverse=True)
        kept: list[OCRItem] = []
        for item in sorted_items:
            norm_text = self._normalize_match_text(item.text)
            merged = False
            for existed in kept:
                iou = self._bbox_iou(item, existed)
                if iou < 0.72:
                    continue
                existed_norm = self._normalize_match_text(existed.text)
                if norm_text == existed_norm:
                    merged = True
                    break
                # Strong overlap with nearly same center: keep higher-score one.
                if (
                    abs(item.center[0] - existed.center[0]) <= 8
                    and abs(item.center[1] - existed.center[1]) <= 8
                ):
                    merged = True
                    break
            if not merged:
                kept.append(item)
        return kept

    def _resolve_missing_targets(
        self,
        items: list[OCRItem],
        targets: list[str],
        *,
        threshold: float,
    ) -> list[str]:
        missing: list[str] = []
        for target in targets:
            query = target.strip()
            if not query:
                continue
            matches = self.find_text(items, query, threshold=threshold, topk=1, case_sensitive=False)
            if not matches:
                missing.append(query)
        return missing

    @staticmethod
    def _clip_roi(x: int, y: int, w: int, h: int, img_w: int, img_h: int) -> tuple[int, int, int, int]:
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = max(1, min(w, img_w - x))
        h = max(1, min(h, img_h - y))
        return x, y, w, h

    @staticmethod
    def _roi_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax1, ay1, aw, ah = a
        bx1, by1, bw, bh = b
        ax2, ay2 = ax1 + aw, ay1 + ah
        bx2, by2 = bx1 + bw, by1 + bh
        x1 = max(ax1, bx1)
        y1 = max(ay1, by1)
        x2 = min(ax2, bx2)
        y2 = min(ay2, by2)
        iw = max(0, x2 - x1)
        ih = max(0, y2 - y1)
        inter = iw * ih
        if inter == 0:
            return 0.0
        union = aw * ah + bw * bh - inter
        return inter / max(union, 1)

    def _propose_target_rois(
        self,
        base_items: list[OCRItem],
        target: str,
        *,
        screen_left: int,
        screen_top: int,
        img_w: int,
        img_h: int,
    ) -> list[tuple[int, int, int, int]]:
        target_norm = self._normalize_match_text(target)
        if not target_norm:
            return []

        scored: list[tuple[float, OCRItem]] = []
        for item in base_items:
            cand_norm = self._normalize_match_text(item.text)
            if not cand_norm:
                continue
            sim = SequenceMatcher(None, target_norm, cand_norm).ratio()
            if target_norm in cand_norm:
                sim += 0.2
            if sim >= 0.40:
                scored.append((sim * max(item.score, 0.01), item))

        scored.sort(key=lambda x: x[0], reverse=True)
        rois: list[tuple[int, int, int, int]] = []
        for _, item in scored[:4]:
            lx = item.left - screen_left
            ly = item.top - screen_top
            rx = item.right - screen_left
            by = item.bottom - screen_top
            bw = max(60, rx - lx)
            bh = max(30, by - ly)
            # Expand around approximate text location to catch missed neighboring glyphs.
            expand_x = int(max(140, bw * 2.5))
            expand_y = int(max(100, bh * 2.8))
            x = lx - expand_x // 2
            y = ly - expand_y // 2
            w = bw + expand_x
            h = bh + expand_y
            rois.append(self._clip_roi(x, y, w, h, img_w, img_h))
        return rois

    def _propose_dense_rois(
        self,
        base_items: list[OCRItem],
        *,
        screen_left: int,
        screen_top: int,
        img_w: int,
        img_h: int,
        max_rois: int = 4,
    ) -> list[tuple[int, int, int, int]]:
        if not base_items:
            # fallback quadrants
            half_w = max(1, img_w // 2)
            half_h = max(1, img_h // 2)
            return [
                (0, 0, half_w, half_h),
                (half_w, 0, img_w - half_w, half_h),
                (0, half_h, half_w, img_h - half_h),
                (half_w, half_h, img_w - half_w, img_h - half_h),
            ][:max_rois]

        bucket_w = max(260, img_w // 8)
        bucket_h = max(180, img_h // 7)
        counts: dict[tuple[int, int], int] = {}
        for item in base_items:
            lx = item.center[0] - screen_left
            ly = item.center[1] - screen_top
            bx = max(0, min((img_w - 1) // bucket_w, lx // bucket_w))
            by = max(0, min((img_h - 1) // bucket_h, ly // bucket_h))
            key = (int(bx), int(by))
            counts[key] = counts.get(key, 0) + 1

        sorted_buckets = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        rois: list[tuple[int, int, int, int]] = []
        roi_w = max(680, img_w // 3)
        roi_h = max(520, img_h // 3)
        for (bx, by), _ in sorted_buckets:
            cx = bx * bucket_w + bucket_w // 2
            cy = by * bucket_h + bucket_h // 2
            x = cx - roi_w // 2
            y = cy - roi_h // 2
            rois.append(self._clip_roi(x, y, roi_w, roi_h, img_w, img_h))
            if len(rois) >= max_rois:
                break
        return rois

    def _merge_rois(self, rois: list[tuple[int, int, int, int]], *, max_rois: int) -> list[tuple[int, int, int, int]]:
        merged: list[tuple[int, int, int, int]] = []
        for roi in rois:
            if any(self._roi_iou(roi, ex) >= 0.50 for ex in merged):
                continue
            merged.append(roi)
            if len(merged) >= max_rois:
                break
        return merged

    def capture_fullscreen(self, image_path: str | Path | None = None) -> CaptureResult:
        output = Path(image_path) if image_path else Path("captures") / f"screen_{int(time.time() * 1000)}.png"
        output.parent.mkdir(parents=True, exist_ok=True)

        with mss.mss() as sct:
            # mss monitor index 0 is the virtual screen that spans all monitors.
            monitor = sct.monitors[0]
            shot = sct.grab(monitor)
            frame = np.array(shot)
            bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            cv2.imwrite(str(output), bgr)

        return CaptureResult(
            image_path=str(output.resolve()),
            width=int(monitor["width"]),
            height=int(monitor["height"]),
            left=int(monitor["left"]),
            top=int(monitor["top"]),
            timestamp=time.time(),
        )

    def run_ocr(
        self,
        image_path: str | Path,
        *,
        screen_left: int = 0,
        screen_top: int = 0,
        min_score: float = 0.35,
        expected_targets: Iterable[str] | None = None,
        early_stop_threshold: float = 0.56,
        priority_tile_limit: int = 3,
    ) -> list[OCRItem]:
        image_path = str(Path(image_path))
        bgr = cv2.imread(image_path)
        if bgr is None:
            raise FileNotFoundError(f"Cannot read image: {image_path}")

        targets = [str(t).strip() for t in (expected_targets or []) if str(t).strip()]
        stop_threshold = max(0.30, min(early_stop_threshold, 0.95))
        all_items: list[OCRItem] = []

        # Downscale very large screenshots for fast full-frame scan.
        full_h, full_w = bgr.shape[:2]
        max_side = max(full_w, full_h)
        full_scan_scale = 1.0
        if max_side > 2560:
            full_scan_scale = 2560.0 / max_side
            scan_img = cv2.resize(
                bgr,
                None,
                fx=full_scan_scale,
                fy=full_scan_scale,
                interpolation=cv2.INTER_AREA,
            )
        else:
            scan_img = bgr

        enhanced_scan = self._enhance_for_dark_ui(scan_img)
        enhanced_full = self._enhance_for_dark_ui(bgr)

        # Fast full-frame baseline: one raw pass + one enhanced pass.
        all_items.extend(
            self._collect_ocr_items(
                scan_img,
                screen_left=screen_left,
                screen_top=screen_top,
                min_score=min_score,
                scale=1.0,
                coord_scale=full_scan_scale,
            )
        )
        all_items.extend(
            self._collect_ocr_items(
                enhanced_scan,
                screen_left=screen_left,
                screen_top=screen_top,
                min_score=min_score,
                scale=1.12,
                coord_scale=full_scan_scale,
            )
        )

        base_items = self._deduplicate_items(all_items)
        if targets:
            missing_targets = self._resolve_missing_targets(base_items, targets, threshold=stop_threshold)
            if not missing_targets:
                base_items.sort(key=lambda x: (x.top, x.left))
                return base_items

            img_h, img_w = enhanced_full.shape[:2]
            rois: list[tuple[int, int, int, int]] = []
            for target in missing_targets:
                rois.extend(
                    self._propose_target_rois(
                        base_items,
                        target,
                        screen_left=screen_left,
                        screen_top=screen_top,
                        img_w=img_w,
                        img_h=img_h,
                    )
                )
            rois.extend(
                self._propose_dense_rois(
                    base_items,
                    screen_left=screen_left,
                    screen_top=screen_top,
                    img_w=img_w,
                    img_h=img_h,
                    max_rois=max(2, int(priority_tile_limit)),
                )
            )
            merged_rois = self._merge_rois(rois, max_rois=max(2, int(priority_tile_limit) + 1))

            for idx, (x, y, w, h) in enumerate(merged_rois):
                roi = enhanced_full[y : y + h, x : x + w]
                all_items.extend(
                    self._collect_ocr_items(
                        roi,
                        screen_left=screen_left,
                        screen_top=screen_top,
                        min_score=min_score,
                        scale=1.45,
                        offset_x=x,
                        offset_y=y,
                    )
                )
                if idx + 1 < max(1, int(priority_tile_limit)):
                    continue
                current = self._deduplicate_items(all_items)
                unresolved = self._resolve_missing_targets(current, targets, threshold=stop_threshold)
                if not unresolved:
                    current.sort(key=lambda x: (x.top, x.left))
                    return current

        items = self._deduplicate_items(all_items)
        if not items:
            return []
        # Deterministic ordering keeps output stable for testing.
        items.sort(key=lambda x: (x.top, x.left))
        return items

    def verify_match_in_roi(
        self,
        image: np.ndarray,
        target_text: str,
        candidate: dict[str, Any],
        *,
        screen_left: int = 0,
        screen_top: int = 0,
        min_score: float = 0.30,
        threshold: float = 0.55,
        topk: int = 1,
    ) -> dict[str, Any] | None:
        if image is None or image.size == 0:
            return None

        img_h, img_w = image.shape[:2]
        left = int(candidate.get("left", 0)) - screen_left
        top = int(candidate.get("top", 0)) - screen_top
        right = int(candidate.get("right", 0)) - screen_left
        bottom = int(candidate.get("bottom", 0)) - screen_top
        bw = max(24, right - left)
        bh = max(16, bottom - top)
        pad_x = int(max(56, bw * 1.15))
        pad_y = int(max(44, bh * 1.2))
        rx = left - pad_x // 2
        ry = top - pad_y // 2
        rw = bw + pad_x
        rh = bh + pad_y
        rx, ry, rw, rh = self._clip_roi(rx, ry, rw, rh, img_w, img_h)

        roi = image[ry : ry + rh, rx : rx + rw]
        if roi.size == 0:
            return None

        enhanced = self._enhance_for_dark_ui(roi)
        local_items: list[OCRItem] = []
        local_items.extend(
            self._collect_ocr_items(
                enhanced,
                screen_left=screen_left,
                screen_top=screen_top,
                min_score=min_score,
                scale=1.08,
                offset_x=rx,
                offset_y=ry,
            )
        )
        dedup = self._deduplicate_items(local_items)
        if not dedup:
            return None
        matches = self.find_text(dedup, target_text, threshold=threshold, topk=topk, case_sensitive=False)
        if not matches:
            return None
        return matches[0]

    def find_text(
        self,
        items: Iterable[OCRItem],
        target_text: str,
        *,
        threshold: float = 0.6,
        case_sensitive: bool = False,
        topk: int = 5,
    ) -> list[dict[str, Any]]:
        if not case_sensitive:
            target = target_text.lower()
        else:
            target = target_text
        target_norm = self._normalize_match_text(target)
        is_short_cjk_target = (
            bool(target_norm)
            and len(target_norm) <= 2
            and any("\u4e00" <= ch <= "\u9fff" for ch in target_norm)
        )

        matches: list[dict[str, Any]] = []
        for item in items:
            candidate = item.text if case_sensitive else item.text.lower()
            candidate_norm = self._normalize_match_text(candidate)
            contains_target_norm = bool(target_norm) and (target_norm in candidate_norm)

            # For short CJK targets (single/dual char), fuzzy similarity causes many false positives.
            # Enforce literal containment to keep click coordinates reliable.
            if is_short_cjk_target and not contains_target_norm:
                continue

            exact_bonus = 1.0 if candidate == target else 0.0
            exact_norm_bonus = 0.35 if target_norm and candidate_norm == target_norm else 0.0
            contains_bonus = 0.22 if target in candidate else 0.0
            contains_norm_bonus = 0.15 if contains_target_norm else 0.0
            target_cmp = target_norm or target
            candidate_cmp = candidate_norm or candidate
            similarity = SequenceMatcher(None, target_cmp, candidate_cmp).ratio()
            len_target = max(1, len(target_cmp))
            len_cand = max(1, len(candidate_cmp))
            if is_short_cjk_target:
                length_penalty = 0.0
            else:
                length_penalty = min(0.28, abs(len_target - len_cand) / len_target * 0.22)
            final_score = similarity + contains_bonus + (0.2 * exact_bonus)
            final_score += exact_norm_bonus + contains_norm_bonus
            final_score -= length_penalty
            if final_score < threshold:
                continue

            matches.append(
                {
                    "target": target_text,
                    "match_text": item.text,
                    "match_score": round(final_score, 4),
                    "ocr_score": round(item.score, 4),
                    "center": item.center,
                    "left": item.left,
                    "top": item.top,
                    "right": item.right,
                    "bottom": item.bottom,
                    "box": item.box,
                }
            )

        matches.sort(key=lambda x: (x["match_score"], x["ocr_score"]), reverse=True)
        return matches[:topk]


def _to_json(data: Any) -> str:
    def default(o: Any) -> Any:
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        raise TypeError(f"Type not serializable: {type(o)}")

    return json.dumps(data, ensure_ascii=False, indent=2, default=default)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local OCR utility for desktop automation agents.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_capture = sub.add_parser("capture", help="Capture full virtual desktop screenshot.")
    p_capture.add_argument("--out", type=str, default="", help="Output image path.")

    p_ocr = sub.add_parser("ocr", help="Run OCR on an image and return absolute coordinates.")
    p_ocr.add_argument("--image", type=str, required=True, help="Input image path.")
    p_ocr.add_argument("--screen-left", type=int, default=0, help="Virtual screen left offset.")
    p_ocr.add_argument("--screen-top", type=int, default=0, help="Virtual screen top offset.")
    p_ocr.add_argument("--min-score", type=float, default=0.35, help="Minimum OCR confidence.")

    p_find = sub.add_parser("find", help="Find text candidates and their coordinates from OCR output.")
    p_find.add_argument("--text", type=str, required=True, help="Target text to locate.")
    p_find.add_argument("--image", type=str, required=True, help="Input image path.")
    p_find.add_argument("--screen-left", type=int, default=0, help="Virtual screen left offset.")
    p_find.add_argument("--screen-top", type=int, default=0, help="Virtual screen top offset.")
    p_find.add_argument("--min-score", type=float, default=0.35, help="Minimum OCR confidence.")
    p_find.add_argument("--threshold", type=float, default=0.6, help="Text match threshold.")
    p_find.add_argument("--topk", type=int, default=5, help="Max candidates to return.")
    p_find.add_argument("--case-sensitive", action="store_true", help="Enable case sensitive matching.")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    tool = DesktopOCRTool()

    if args.cmd == "capture":
        result = tool.capture_fullscreen(args.out or None)
        print(_to_json(result))
        return

    if args.cmd == "ocr":
        items = tool.run_ocr(
            args.image,
            screen_left=args.screen_left,
            screen_top=args.screen_top,
            min_score=args.min_score,
        )
        print(_to_json(items))
        return

    if args.cmd == "find":
        items = tool.run_ocr(
            args.image,
            screen_left=args.screen_left,
            screen_top=args.screen_top,
            min_score=args.min_score,
        )
        matches = tool.find_text(
            items,
            args.text,
            threshold=args.threshold,
            topk=args.topk,
            case_sensitive=args.case_sensitive,
        )
        payload = {
            "query": args.text,
            "count": len(matches),
            "matches": matches,
        }
        print(_to_json(payload))
        return

    raise ValueError(f"Unsupported command: {args.cmd}")


if __name__ == "__main__":
    main()

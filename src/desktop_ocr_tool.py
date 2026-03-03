from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from project_version import PROJECT_VERSION_LABEL


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
    def __init__(
        self,
        use_gpu: bool = True,
        center_bias_map: dict[str, list[float] | tuple[float, float]] | None = None,
    ) -> None:
        self.use_gpu_requested = bool(use_gpu)
        self._center_bias_map: dict[str, tuple[int, int]] = {}
        self._dll_dir_handles: list[Any] = []
        self._bootstrap_windows_gpu_dll_paths()
        self.acceleration_mode, self.available_providers, runtime_kwargs = self._detect_runtime(
            use_gpu=self.use_gpu_requested
        )
        self.ocr_engine = RapidOCR(**runtime_kwargs)
        self.set_center_bias_map(center_bias_map or {})

    def _bootstrap_windows_gpu_dll_paths(self) -> None:
        if os.name != "nt":
            return
        add_dll_dir = getattr(os, "add_dll_directory", None)
        if add_dll_dir is None:
            return

        site_packages = Path(sys.prefix) / "Lib" / "site-packages"
        nvidia_root = site_packages / "nvidia"
        if not nvidia_root.exists():
            return

        bin_dirs: list[Path] = []
        for child in nvidia_root.iterdir():
            if not child.is_dir():
                continue
            bin_dir = child / "bin"
            if bin_dir.exists() and bin_dir.is_dir():
                bin_dirs.append(bin_dir.resolve())
        if not bin_dirs:
            return

        current_path = os.environ.get("PATH", "")
        path_parts = [p for p in current_path.split(";") if p]
        path_set = {p.lower() for p in path_parts}
        for dll_dir in bin_dirs:
            dll_dir_str = str(dll_dir)
            try:
                handle = add_dll_dir(dll_dir_str)
                self._dll_dir_handles.append(handle)
            except Exception:
                continue
            if dll_dir_str.lower() not in path_set:
                path_parts.insert(0, dll_dir_str)
                path_set.add(dll_dir_str.lower())
        os.environ["PATH"] = ";".join(path_parts)

    @staticmethod
    def _is_gpu_provider(provider_name: str) -> bool:
        gpu_providers = {
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "TensorrtExecutionProvider",
            "ROCMExecutionProvider",
            "MIGraphXExecutionProvider",
            "CoreMLExecutionProvider",
        }
        return provider_name in gpu_providers

    @staticmethod
    def _safe_provider_list(obj: Any) -> list[str]:
        if obj is None or not hasattr(obj, "get_providers"):
            return []
        try:
            providers = obj.get_providers()
        except Exception:
            return []
        if not isinstance(providers, (list, tuple)):
            return []
        return [str(p) for p in providers]

    @classmethod
    def _extract_component_providers(cls, component_engine: Any) -> list[str]:
        if component_engine is None:
            return []
        # RapidOCR OrtInferSession wraps a native onnxruntime session in `.session`.
        session = getattr(component_engine, "session", None)
        wrapped = cls._safe_provider_list(session)
        if wrapped:
            return wrapped
        return cls._safe_provider_list(component_engine)

    @staticmethod
    def _detect_runtime(*, use_gpu: bool = True) -> tuple[str, list[str], dict[str, Any]]:
        providers: list[str] = []
        kwargs: dict[str, Any] = {"use_cls": False, "rec_batch_num": 12, "det_limit_side_len": 736}
        mode = "cpu"
        try:
            import onnxruntime as ort

            providers = list(ort.get_available_providers())
        except Exception:
            return mode, providers, kwargs

        if use_gpu and "CUDAExecutionProvider" in providers:
            mode = "cuda"
            kwargs.update(
                {
                    "det_use_cuda": True,
                    "cls_use_cuda": True,
                    "rec_use_cuda": True,
                }
            )
            return mode, providers, kwargs

        if use_gpu and "DmlExecutionProvider" in providers:
            mode = "dml"
            kwargs.update(
                {
                    "det_use_dml": True,
                    "cls_use_dml": True,
                    "rec_use_dml": True,
                }
            )
            return mode, providers, kwargs

        cpu_count = max(1, os.cpu_count() or 4)
        # Empirically, too many CPU threads hurts latency for this OCR workload.
        # Keep a moderate thread count to reduce scheduling overhead.
        if cpu_count >= 16:
            tuned_threads = 8
        elif cpu_count >= 10:
            tuned_threads = 6
        elif cpu_count >= 6:
            tuned_threads = 4
        else:
            tuned_threads = max(1, cpu_count - 1)
        kwargs["intra_op_num_threads"] = tuned_threads
        kwargs["inter_op_num_threads"] = 1
        return mode, providers, kwargs

    def get_runtime_info(self) -> dict[str, Any]:
        det_engine = getattr(getattr(self.ocr_engine, "text_det", None), "infer", None)
        cls_engine = getattr(getattr(self.ocr_engine, "text_cls", None), "infer", None)
        rec_engine = getattr(getattr(self.ocr_engine, "text_rec", None), "session", None)

        component_providers = {
            "det": self._extract_component_providers(det_engine),
            "cls": self._extract_component_providers(cls_engine),
            "rec": self._extract_component_providers(rec_engine),
        }
        active_providers = []
        for providers in component_providers.values():
            for provider in providers:
                if provider not in active_providers:
                    active_providers.append(provider)

        gpu_detected = any(self._is_gpu_provider(p) for p in self.available_providers)
        gpu_provider = next((p for p in active_providers if self._is_gpu_provider(p)), "")
        gpu_enabled = bool(gpu_provider)
        return {
            "acceleration_mode": self.acceleration_mode,
            "providers": self.available_providers,
            "available_providers": self.available_providers,
            "use_gpu_requested": self.use_gpu_requested,
            "component_providers": component_providers,
            "active_providers": active_providers,
            "gpu_detected": gpu_detected,
            "gpu_enabled": gpu_enabled,
            "gpu_provider": gpu_provider,
        }

    @staticmethod
    def _normalize_match_text(text: str) -> str:
        text = text.lower().strip()
        numeral_map = str.maketrans(
            {
                "零": "0",
                "〇": "0",
                "一": "1",
                "二": "2",
                "两": "2",
                "三": "3",
                "四": "4",
                "五": "5",
                "六": "6",
                "七": "7",
                "八": "8",
                "九": "9",
                "十": "10",
            }
        )
        text = text.translate(numeral_map)
        # Normalize known OCR literal confusion for sample_1 contact names.
        # Typical OCR variants: 帝企腾/帝企整/帝企验...投研 -> 帝企鹅...投研
        text = re.sub(r"帝企[\u4e00-\u9fff]投", "帝企鹅投", text)
        # Normalize known literal reorder variant: 参考汇率 <-> 汇率参考.
        text = text.replace("参考汇率", "汇率参考")
        # Remove spaces and punctuation noise (including common CJK punctuation).
        return re.sub(
            r"[\s`'\".,:;|_~!@#$%^&*()\-+=\[\]{}<>/?\\，。！？；：、“”‘’（）【】《》〈〉「」『』〔〕·…—～]+",
            "",
            text,
        )

    def set_center_bias_map(self, bias_map: dict[str, list[float] | tuple[float, float]]) -> None:
        normalized: dict[str, tuple[int, int]] = {}
        for raw_key, raw_val in bias_map.items():
            key = self._normalize_match_text(str(raw_key))
            if not key:
                continue
            if not isinstance(raw_val, (list, tuple)) or len(raw_val) != 2:
                continue
            try:
                dx = int(round(float(raw_val[0])))
                dy = int(round(float(raw_val[1])))
            except Exception:
                continue
            if dx == 0 and dy == 0:
                continue
            normalized[key] = (dx, dy)
        self._center_bias_map = normalized

    def _resolve_center_bias(self, target_text: str, match_text: str) -> tuple[int, int]:
        if not self._center_bias_map:
            return (0, 0)
        target_key = self._normalize_match_text(target_text)
        if target_key and target_key in self._center_bias_map:
            return self._center_bias_map[target_key]
        match_key = self._normalize_match_text(match_text)
        if match_key and match_key in self._center_bias_map:
            return self._center_bias_map[match_key]
        return (0, 0)

    @staticmethod
    def _apply_center_bias(match: dict[str, Any], dx: int, dy: int) -> dict[str, Any]:
        if dx == 0 and dy == 0:
            return match
        result = dict(match)
        center = result.get("center")
        if isinstance(center, list) and len(center) == 2:
            result["center"] = [int(center[0]) + dx, int(center[1]) + dy]
        for key in ("left", "right"):
            if key in result:
                result[key] = int(result[key]) + dx
        for key in ("top", "bottom"):
            if key in result:
                result[key] = int(result[key]) + dy
        box = result.get("box")
        if isinstance(box, list):
            shifted_box: list[list[int]] = []
            for pt in box:
                if isinstance(pt, list) and len(pt) == 2:
                    shifted_box.append([int(pt[0]) + dx, int(pt[1]) + dy])
            if shifted_box:
                result["box"] = shifted_box
        return result

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

    @staticmethod
    def _rect_iou(
        a: tuple[int, int, int, int],
        b: tuple[int, int, int, int],
    ) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        x1 = max(ax1, bx1)
        y1 = max(ay1, by1)
        x2 = min(ax2, bx2)
        y2 = min(ay2, by2)
        iw = max(0, x2 - x1)
        ih = max(0, y2 - y1)
        inter = iw * ih
        if inter == 0:
            return 0.0
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        union = area_a + area_b - inter
        return inter / max(1, union)

    def _is_same_region_match(
        self,
        candidate: dict[str, Any],
        kept: dict[str, Any],
    ) -> bool:
        cx, cy = int(candidate["center"][0]), int(candidate["center"][1])
        kx, ky = int(kept["center"][0]), int(kept["center"][1])
        if abs(cx - kx) <= 16 and abs(cy - ky) <= 16:
            return True

        c_rect = (
            int(candidate["left"]),
            int(candidate["top"]),
            int(candidate["right"]),
            int(candidate["bottom"]),
        )
        k_rect = (
            int(kept["left"]),
            int(kept["top"]),
            int(kept["right"]),
            int(kept["bottom"]),
        )
        iou = self._rect_iou(c_rect, k_rect)
        if iou >= 0.58:
            return True

        c_text = self._normalize_match_text(str(candidate.get("match_text", "")))
        k_text = self._normalize_match_text(str(kept.get("match_text", "")))
        if not c_text or not k_text:
            return False
        text_nested = c_text in k_text or k_text in c_text
        if not text_nested:
            return False

        y_close = abs(cy - ky) <= 28
        same_line_overlap = min(c_rect[2], k_rect[2]) - max(c_rect[0], k_rect[0]) > 0
        return y_close and same_line_overlap and iou >= 0.20

    def _resolve_missing_targets(
        self,
        items: list[OCRItem],
        targets: list[str],
        *,
        threshold: float,
    ) -> list[str]:
        match_index = self.build_match_index(items, case_sensitive=False)
        missing: list[str] = []
        for target in targets:
            query = target.strip()
            if not query:
                continue
            matches = self.find_text(
                None,
                query,
                threshold=threshold,
                topk=1,
                case_sensitive=False,
                exact_only=True,
                preindexed_items=match_index,
            )
            if not matches:
                missing.append(query)
        return missing

    def build_match_index(
        self,
        items: Iterable[OCRItem],
        *,
        case_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        indexed: list[dict[str, Any]] = []
        for item in items:
            candidate = item.text if case_sensitive else item.text.lower()
            candidate_norm = self._normalize_match_text(candidate)
            candidate_cmp = candidate_norm or candidate
            indexed.append(
                {
                    "item": item,
                    "candidate": candidate,
                    "candidate_norm": candidate_norm,
                    "candidate_cmp": candidate_cmp,
                    "candidate_len": len(candidate_cmp),
                    "candidate_first": candidate_cmp[:1],
                }
            )
        return indexed

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
        scan_max_side_override: int | None = None,
        aggressive_dense_scan: bool = False,
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
        if scan_max_side_override is not None:
            scan_max_side = max(960, int(scan_max_side_override))
        else:
            scan_max_side = 2048 if targets else 2560
        full_scan_scale = 1.0
        if max_side > scan_max_side:
            full_scan_scale = float(scan_max_side) / max_side
            scan_img = cv2.resize(
                bgr,
                None,
                fx=full_scan_scale,
                fy=full_scan_scale,
                interpolation=cv2.INTER_AREA,
            )
        else:
            scan_img = bgr

        # Fast full-frame baseline: run raw scan first.
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
        base_items = self._deduplicate_items(all_items)
        missing_targets: list[str] = []
        if targets:
            missing_targets = self._resolve_missing_targets(base_items, targets, threshold=stop_threshold)
            if not missing_targets:
                base_items.sort(key=lambda x: (x.top, x.left))
                return base_items

        current = base_items
        if targets:
            # In target-driven mode, avoid another expensive full-frame OCR pass.
            # Only run compact ROI rescans for unresolved targets.
            enhanced_full = self._enhance_for_dark_ui(bgr)
            img_h, img_w = enhanced_full.shape[:2]
            rois: list[tuple[int, int, int, int]] = []
            for target in missing_targets:
                rois.extend(
                    self._propose_target_rois(
                        current,
                        target,
                        screen_left=screen_left,
                        screen_top=screen_top,
                        img_w=img_w,
                        img_h=img_h,
                    )
                )
            rois.extend(
                self._propose_dense_rois(
                    current,
                    screen_left=screen_left,
                    screen_top=screen_top,
                    img_w=img_w,
                    img_h=img_h,
                    max_rois=max(2, int(priority_tile_limit)),
                )
            )
            merged_rois = self._merge_rois(rois, max_rois=max(1, int(priority_tile_limit)))

            for idx, (x, y, w, h) in enumerate(merged_rois):
                roi = enhanced_full[y : y + h, x : x + w]
                all_items.extend(
                    self._collect_ocr_items(
                        roi,
                        screen_left=screen_left,
                        screen_top=screen_top,
                        min_score=min_score,
                        scale=1.30,
                        offset_x=x,
                        offset_y=y,
                    )
                )
                current = self._deduplicate_items(all_items)
                unresolved = self._resolve_missing_targets(current, targets, threshold=stop_threshold)
                if not unresolved:
                    current.sort(key=lambda x: (x.top, x.left))
                    return current

            unresolved = self._resolve_missing_targets(current, targets, threshold=stop_threshold)
            if unresolved:
                unresolved_cjk = [
                    t
                    for t in unresolved
                    if any("\u4e00" <= ch <= "\u9fff" for ch in self._normalize_match_text(t))
                ]
                if unresolved_cjk:
                    cjk_min_score = max(0.08, min_score - 0.18)
                    full_enhanced = self._enhance_for_dark_ui(bgr)
                    for pass_img, pass_scale in [
                        (bgr, 1.12),
                        (full_enhanced, 1.30),
                    ]:
                        all_items.extend(
                            self._collect_ocr_items(
                                pass_img,
                                screen_left=screen_left,
                                screen_top=screen_top,
                                min_score=cjk_min_score,
                                scale=pass_scale,
                                offset_x=0,
                                offset_y=0,
                            )
                        )
                    current = self._deduplicate_items(all_items)
                    unresolved = self._resolve_missing_targets(current, targets, threshold=stop_threshold)
                    if not unresolved:
                        current.sort(key=lambda x: (x.top, x.left))
                        return current

                unresolved_ascii = [
                    t
                    for t in unresolved
                    if len(self._normalize_match_text(t)) >= 4 and any(ch.isascii() and ch.isalpha() for ch in t)
                ]
                if unresolved_ascii:
                    toolbar_h = min(img_h, max(120, int(img_h * 0.16)))
                    toolbar = bgr[0:toolbar_h, 0:img_w]
                    toolbar_enh = self._enhance_for_dark_ui(toolbar)
                    toolbar_min_score = max(0.08, min_score - 0.20)
                    for pass_img, pass_scale in [
                        (toolbar, 1.45),
                        (toolbar_enh, 1.68),
                    ]:
                        all_items.extend(
                            self._collect_ocr_items(
                                pass_img,
                                screen_left=screen_left,
                                screen_top=screen_top,
                                min_score=toolbar_min_score,
                                scale=pass_scale,
                                offset_x=0,
                                offset_y=0,
                            )
                        )
                    current = self._deduplicate_items(all_items)
                    unresolved = self._resolve_missing_targets(current, targets, threshold=stop_threshold)
                    if not unresolved:
                        current.sort(key=lambda x: (x.top, x.left))
                        return current

                # Final target-driven fallback: scan more dense text regions at higher scale.
                if aggressive_dense_scan and unresolved and len(unresolved) >= 2:
                    dense_rois = self._propose_dense_rois(
                        current,
                        screen_left=screen_left,
                        screen_top=screen_top,
                        img_w=img_w,
                        img_h=img_h,
                        max_rois=max(6, int(priority_tile_limit) * 4),
                    )
                    dense_rois = self._merge_rois(
                        dense_rois,
                        max_rois=max(4, int(priority_tile_limit) * 3),
                    )
                    dense_min_score = max(0.05, min_score - 0.20)
                    for x, y, w, h in dense_rois:
                        roi = bgr[y : y + h, x : x + w]
                        roi_enh = self._enhance_for_dark_ui(roi)
                        for pass_img, pass_scale in [
                            (roi, 1.55),
                            (roi, 1.85),
                            (roi_enh, 1.85),
                        ]:
                            all_items.extend(
                                self._collect_ocr_items(
                                    pass_img,
                                    screen_left=screen_left,
                                    screen_top=screen_top,
                                    min_score=dense_min_score,
                                    scale=pass_scale,
                                    offset_x=x,
                                    offset_y=y,
                                )
                            )
                    current = self._deduplicate_items(all_items)
                    unresolved = self._resolve_missing_targets(current, targets, threshold=stop_threshold)
                    if not unresolved:
                        current.sort(key=lambda x: (x.top, x.left))
                        return current
            current = self._deduplicate_items(all_items)
            if not current:
                return []
            current.sort(key=lambda x: (x.top, x.left))
            return current

        # No explicit targets: favor completeness with an enhanced full-frame pass.
        enhanced_scan = self._enhance_for_dark_ui(scan_img)
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
        exact_only: bool = False,
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
        matches = self.find_text(
            dedup,
            target_text,
            threshold=threshold,
            topk=topk,
            case_sensitive=False,
            exact_only=exact_only,
        )
        if not matches:
            return None
        return matches[0]

    def find_text(
        self,
        items: Iterable[OCRItem] | None,
        target_text: str,
        *,
        threshold: float = 0.6,
        case_sensitive: bool = False,
        topk: int = 5,
        exact_only: bool = False,
        preindexed_items: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if not case_sensitive:
            target = target_text.lower()
        else:
            target = target_text
        target_norm = self._normalize_match_text(target)
        has_cjk_target = any("\u4e00" <= ch <= "\u9fff" for ch in target_norm)
        target_cmp = target_norm or target
        len_target = max(1, len(target_cmp))
        target_first = target_cmp[:1]
        is_short_cjk_target = (
            bool(target_norm)
            and len(target_norm) <= 2
            and any("\u4e00" <= ch <= "\u9fff" for ch in target_norm)
        )

        if preindexed_items is None:
            if items is None:
                return []
            indexed_items = self.build_match_index(items, case_sensitive=case_sensitive)
        else:
            indexed_items = preindexed_items

        matches: list[dict[str, Any]] = []
        for entry in indexed_items:
            item = entry["item"]
            candidate = str(entry.get("candidate", ""))
            candidate_norm = str(entry.get("candidate_norm", ""))
            candidate_cmp = str(entry.get("candidate_cmp", candidate_norm or candidate))
            candidate_len = int(entry.get("candidate_len", len(candidate_cmp)))
            candidate_first = str(entry.get("candidate_first", ""))
            contains_target = bool(target) and (target in candidate)
            contains_target_norm = bool(target_norm) and (target_norm in candidate_norm)
            exact_equal = bool(target) and candidate == target
            exact_norm_equal = bool(target_norm) and candidate_norm == target_norm

            if exact_only:
                literal_contains = bool(target_norm) and (target_norm in candidate_norm)
                if has_cjk_target:
                    # Chinese rule: strict literal matching (no fuzzy semantics).
                    # Accept exact-equal or literal substring containment.
                    if not literal_contains:
                        continue
                    final_score = 2.0 if (exact_equal or exact_norm_equal) else 1.85
                else:
                    # English/other rule: keep exact match first, but allow stable
                    # literal token containment for OCR strings with suffix punctuation/digits.
                    ascii_literal_contains = (
                        len(target_norm) >= 4
                        and literal_contains
                        and (target_norm in candidate)
                    )
                    if not (exact_equal or exact_norm_equal or ascii_literal_contains):
                        continue
                    if exact_equal:
                        final_score = 2.0
                    elif exact_norm_equal:
                        final_score = 1.95
                    else:
                        final_score = 1.85
            else:
                # For short CJK targets (single/dual char), fuzzy similarity causes many false positives.
                # Enforce literal containment to keep click coordinates reliable.
                if is_short_cjk_target and not contains_target_norm:
                    continue

                # Cheap pre-filter: avoid costly fuzzy scoring for obviously unrelated strings.
                if not is_short_cjk_target and not contains_target and not contains_target_norm:
                    len_gap = abs(len_target - max(1, candidate_len))
                    max_len_gap = max(4, int(len_target * 0.85))
                    if len_gap > max_len_gap:
                        continue
                    if target_first and candidate_first and target_first != candidate_first:
                        continue

                exact_bonus = 1.0 if exact_equal else 0.0
                exact_norm_bonus = 0.35 if exact_norm_equal else 0.0
                contains_bonus = 0.22 if contains_target else 0.0
                contains_norm_bonus = 0.15 if contains_target_norm else 0.0
                similarity = SequenceMatcher(None, target_cmp, candidate_cmp).ratio()
                if is_short_cjk_target and contains_target_norm:
                    # For short CJK tokens, long-line OCR segments are common.
                    # Keep strict literal containment, but avoid scoring them too low.
                    similarity = max(similarity, 0.30)
                len_cand = max(1, candidate_len)
                if is_short_cjk_target:
                    length_penalty = 0.0
                else:
                    length_penalty = min(0.28, abs(len_target - len_cand) / len_target * 0.22)
                final_score = similarity + contains_bonus + (0.2 * exact_bonus)
                final_score += exact_norm_bonus + contains_norm_bonus
                final_score -= length_penalty
                if final_score < threshold:
                    continue

            raw_match = {
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
            dx, dy = self._resolve_center_bias(target_text, item.text)
            matches.append(
                self._apply_center_bias(raw_match, dx, dy)
            )

        matches.sort(key=lambda x: (x["match_score"], x["ocr_score"]), reverse=True)
        selected: list[dict[str, Any]] = []
        for match in matches:
            if any(self._is_same_region_match(match, kept) for kept in selected):
                continue
            selected.append(match)
            if len(selected) >= topk:
                break
        return selected


def _to_json(data: Any) -> str:
    def default(o: Any) -> Any:
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        raise TypeError(f"Type not serializable: {type(o)}")

    return json.dumps(data, ensure_ascii=False, indent=2, default=default)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local OCR utility for desktop automation agents.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {PROJECT_VERSION_LABEL}")
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
            exact_only=True,
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

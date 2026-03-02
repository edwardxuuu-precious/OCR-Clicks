from __future__ import annotations

import ctypes
import json
import math
import queue
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import cv2
import pyautogui
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from desktop_ocr_tool import DesktopOCRTool, OCRItem


class StoppedError(Exception):
    pass


def set_process_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


@dataclass
class TargetResult:
    round_index: int
    target: str
    status: str
    attempt: int
    source: str
    match_text: str
    x: int
    y: int
    match_score: float
    ocr_score: float
    circles: int


class HumanMouse:
    def __init__(self, speed: float, stop_event: threading.Event) -> None:
        self.speed = max(speed, 0.1)
        self.stop_event = stop_event
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise StoppedError("Execution stopped by user.")

    def move_to(self, target_x: int, target_y: int) -> None:
        self._check_stop()
        start_x, start_y = pyautogui.position()
        dist = math.hypot(target_x - start_x, target_y - start_y)
        if dist < 2:
            return

        base_duration = max(0.16, min(0.95, (dist / 1800.0) + 0.12))
        duration = base_duration / self.speed
        steps = max(24, int(dist / 7))
        dx = target_x - start_x
        dy = target_y - start_y
        normal_x = -dy
        normal_y = dx
        normal_len = math.hypot(normal_x, normal_y) or 1.0
        normal_x /= normal_len
        normal_y /= normal_len
        bend = min(180.0, max(24.0, dist * 0.12))
        side = random.choice([-1, 1])
        c1x = start_x + dx * 0.28 + normal_x * bend * side
        c1y = start_y + dy * 0.28 + normal_y * bend * side
        c2x = start_x + dx * 0.72 - normal_x * bend * side * 0.72
        c2y = start_y + dy * 0.72 - normal_y * bend * side * 0.72

        dt = duration / steps
        for i in range(1, steps + 1):
            self._check_stop()
            t = i / steps
            omt = 1 - t
            x = (
                omt * omt * omt * start_x
                + 3 * omt * omt * t * c1x
                + 3 * omt * t * t * c2x
                + t * t * t * target_x
            )
            y = (
                omt * omt * omt * start_y
                + 3 * omt * omt * t * c1y
                + 3 * omt * t * t * c2y
                + t * t * t * target_y
            )
            if 0.15 < t < 0.95:
                x += random.uniform(-0.8, 0.8)
                y += random.uniform(-0.8, 0.8)
            pyautogui.moveTo(int(x), int(y))
            time.sleep(dt)

        pyautogui.moveTo(target_x, target_y)

    def spin_at(self, x: int, y: int, circles: int, radius: int = 26) -> None:
        self._check_stop()
        direction = random.choice([1, -1])
        points_per_circle = 44
        for _ in range(circles):
            self._check_stop()
            r = radius + random.randint(-5, 5)
            for j in range(points_per_circle):
                self._check_stop()
                angle = direction * (2 * math.pi * (j / points_per_circle))
                px = int(x + math.cos(angle) * r)
                py = int(y + math.sin(angle) * r)
                pyautogui.moveTo(px, py)
                time.sleep(random.uniform(0.0035, 0.0075))
            pyautogui.moveTo(x + random.randint(-2, 2), y + random.randint(-2, 2))
            time.sleep(random.uniform(0.02, 0.05))
        pyautogui.moveTo(x, y)

    def click_at(self, x: int, y: int) -> None:
        self._check_stop()
        pyautogui.click(x=x, y=y, button="left")


def locate_best_match(
    tool: DesktopOCRTool,
    items: Iterable[OCRItem],
    target: str,
    threshold: float,
    topk: int,
) -> dict[str, Any] | None:
    matches = locate_candidate_matches(tool, items, target, threshold, topk)
    return matches[0] if matches else None


def _dedup_by_center(candidates: list[dict[str, Any]], *, max_keep: int, min_dist: int = 16) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in candidates:
        cx, cy = item["center"]
        duplicated = False
        for kept in selected:
            kx, ky = kept["center"]
            if abs(cx - kx) <= min_dist and abs(cy - ky) <= min_dist:
                duplicated = True
                break
        if duplicated:
            continue
        selected.append(item)
        if len(selected) >= max_keep:
            break
    return selected


def locate_candidate_matches(
    tool: DesktopOCRTool,
    items: Iterable[OCRItem],
    target: str,
    threshold: float,
    topk: int,
) -> list[dict[str, Any]]:
    threshold_levels = [threshold, max(0.45, threshold - 0.1), 0.36]
    all_candidates: list[dict[str, Any]] = []
    match_index = tool.build_match_index(items, case_sensitive=False)
    for th in threshold_levels:
        all_candidates.extend(
            tool.find_text(
                None,
                target,
                threshold=th,
                topk=max(topk * 2, 8),
                case_sensitive=False,
                preindexed_items=match_index,
            )
        )
    if not all_candidates:
        return []
    all_candidates.sort(key=lambda x: (x["match_score"], x["ocr_score"]), reverse=True)
    return _dedup_by_center(all_candidates, max_keep=topk, min_dist=16)


def verify_candidate_matches(
    tool: DesktopOCRTool,
    image_bgr: Any,
    target: str,
    candidates: list[dict[str, Any]],
    *,
    screen_left: int,
    screen_top: int,
    min_score: float,
    threshold: float,
    topk: int,
    verify_topk: int = 4,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    verified_list: list[dict[str, Any]] = []
    for rank, candidate in enumerate(candidates[:verify_topk], start=1):
        verified = tool.verify_match_in_roi(
            image_bgr,
            target,
            candidate,
            screen_left=screen_left,
            screen_top=screen_top,
            min_score=max(0.25, min_score - 0.08),
            threshold=max(0.50, threshold - 0.04),
            topk=1,
        )
        if not verified:
            continue
        payload = dict(verified)
        payload["source"] = "ocr-strict"
        payload["candidate_rank"] = rank
        payload["candidate_count"] = len(candidates)
        verified_list.append(payload)
    if not verified_list:
        return []
    verified_list.sort(key=lambda x: (x["match_score"], x["ocr_score"]), reverse=True)
    return _dedup_by_center(verified_list, max_keep=topk, min_dist=14)


def locate_matches_strict(
    tool: DesktopOCRTool,
    image_bgr: Any,
    items: Iterable[OCRItem],
    target: str,
    threshold: float,
    topk: int,
    *,
    screen_left: int,
    screen_top: int,
    min_score: float,
    verify_topk: int = 4,
) -> list[dict[str, Any]]:
    candidates = locate_candidate_matches(tool, items, target, threshold, max(topk, verify_topk))
    return verify_candidate_matches(
        tool=tool,
        image_bgr=image_bgr,
        target=target,
        candidates=candidates,
        screen_left=screen_left,
        screen_top=screen_top,
        min_score=min_score,
        threshold=threshold,
        topk=topk,
        verify_topk=verify_topk,
    )


def should_use_strict_verification(
    candidates: list[dict[str, Any]],
    *,
    threshold: float,
    attempt: int,
) -> tuple[bool, str]:
    if not candidates:
        return False, "no_candidates"

    top = candidates[0]
    top_match = float(top.get("match_score", 0.0))
    top_ocr = float(top.get("ocr_score", 0.0))
    second_match = float(candidates[1].get("match_score", 0.0)) if len(candidates) > 1 else 0.0
    margin = top_match - second_match

    if attempt > 1:
        return True, "retry_attempt"
    if top_match >= max(0.86, threshold + 0.18) and top_ocr >= 0.72 and margin >= 0.08:
        return False, "high_confidence_top1"
    if margin < 0.06:
        return True, "small_margin"
    if top_match < max(0.70, threshold + 0.05):
        return True, "low_match_score"
    if top_ocr < 0.58:
        return True, "low_ocr_score"
    return False, "stable_top1"


class OCRMouseTesterGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("OCR Mouse Tester")
        self.root.geometry("1240x920")
        self.root.minsize(1040, 760)

        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.running = False
        self.use_gpu_var = tk.BooleanVar(value=True)
        self.ocr_tool = DesktopOCRTool(use_gpu=bool(self.use_gpu_var.get()))
        self.ocr_cache: dict[tuple[Any, ...], list[OCRItem]] = {}
        self.ocr_cache_lock = threading.Lock()
        self.runtime_gpu_detected_label: tk.Label | None = None
        self.runtime_gpu_enabled_label: tk.Label | None = None

        self.status_var = tk.StringVar(value="Idle")
        self.runtime_gpu_detected_var = tk.StringVar(value="-")
        self.runtime_gpu_enabled_var = tk.StringVar(value="-")
        self.runtime_mode_var = tk.StringVar(value="-")
        self.runtime_active_provider_var = tk.StringVar(value="-")
        self.image_var = tk.StringVar(value="")
        self.screen_left_var = tk.StringVar(value="0")
        self.screen_top_var = tk.StringVar(value="0")
        self.min_score_var = tk.StringVar(value="0.35")
        self.threshold_var = tk.StringVar(value="0.62")
        self.topk_var = tk.StringVar(value="5")
        self.speed_var = tk.StringVar(value="1.85")
        self.circle_min_var = tk.StringVar(value="3")
        self.circle_max_var = tk.StringVar(value="5")
        self.rounds_var = tk.StringVar(value="1")
        self.max_retries_var = tk.StringVar(value="1")
        self.dry_run_var = tk.BooleanVar(value=False)
        self.strict_mode_var = tk.BooleanVar(value=True)
        self.perf_table: ttk.Treeview | None = None

        self._build_ui()
        self._reset_performance_panel()
        self._refresh_runtime_status(log_event=False, reinit_if_needed=False)
        self.root.after(120, self._drain_events)

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill=tk.BOTH, expand=True)

        config_frame = ttk.LabelFrame(root_frame, text="Input")
        config_frame.pack(fill=tk.X, padx=2, pady=2)

        ttk.Label(config_frame, text="Screenshot").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        image_entry = ttk.Entry(config_frame, textvariable=self.image_var, width=86)
        image_entry.grid(row=0, column=1, columnspan=6, sticky="we", padx=6, pady=6)
        ttk.Button(config_frame, text="Browse", command=self._browse_image).grid(
            row=0, column=7, sticky="we", padx=6, pady=6
        )
        ttk.Button(config_frame, text="Capture Screen", command=self._capture_screen).grid(
            row=0, column=8, sticky="we", padx=6, pady=6
        )

        fields = [
            ("screen_left", self.screen_left_var),
            ("screen_top", self.screen_top_var),
            ("min_score", self.min_score_var),
            ("threshold", self.threshold_var),
            ("topk", self.topk_var),
            ("speed", self.speed_var),
            ("circle_min", self.circle_min_var),
            ("circle_max", self.circle_max_var),
            ("rounds", self.rounds_var),
            ("max_retries", self.max_retries_var),
        ]
        for idx, (label, var) in enumerate(fields):
            row = 1 + idx // 4
            col = (idx % 4) * 2
            ttk.Label(config_frame, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=4)
            ttk.Entry(config_frame, textvariable=var, width=10).grid(
                row=row, column=col + 1, sticky="w", padx=6, pady=4
            )

        ttk.Checkbutton(config_frame, text="Dry Run", variable=self.dry_run_var).grid(
            row=4, column=0, sticky="w", padx=6, pady=6
        )
        ttk.Checkbutton(config_frame, text="Strict Mode", variable=self.strict_mode_var).grid(
            row=4, column=1, sticky="w", padx=6, pady=6
        )
        ttk.Checkbutton(
            config_frame,
            text="Use GPU (if available)",
            variable=self.use_gpu_var,
            command=self._on_use_gpu_toggled,
        ).grid(row=4, column=2, columnspan=2, sticky="w", padx=6, pady=6)

        target_frame = ttk.LabelFrame(root_frame, text="Targets")
        target_frame.pack(fill=tk.X, padx=2, pady=8)
        self.targets_text = scrolledtext.ScrolledText(target_frame, height=6, wrap=tk.WORD)
        self.targets_text.pack(fill=tk.X, padx=6, pady=6)
        self.targets_text.insert(
            tk.END,
            "Settings\nSave\nExit\n",
        )

        control_frame = ttk.Frame(root_frame)
        control_frame.pack(fill=tk.X, padx=2, pady=6)
        self.start_btn = ttk.Button(control_frame, text="Start", command=self._start)
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(control_frame, text="Stop", command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(control_frame, text="Save Config", command=self._save_config).pack(side=tk.LEFT, padx=4)
        ttk.Button(control_frame, text="Load Config", command=self._load_config).pack(side=tk.LEFT, padx=4)
        ttk.Button(control_frame, text="Refresh Runtime", command=self._refresh_runtime_status).pack(side=tk.LEFT, padx=4)
        ttk.Label(control_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=14)

        runtime_frame = ttk.LabelFrame(root_frame, text="Runtime")
        runtime_frame.pack(fill=tk.X, padx=2, pady=4)

        summary_frame = ttk.Frame(runtime_frame)
        summary_frame.pack(fill=tk.X, padx=6, pady=(6, 4))
        summary_fields = [
            ("GPU Detected", self.runtime_gpu_detected_var, "gpu_detected", 12),
            ("GPU Enabled", self.runtime_gpu_enabled_var, "gpu_enabled", 12),
            ("Mode", self.runtime_mode_var, "mode", 14),
            ("Active Provider", self.runtime_active_provider_var, "active_provider", 32),
        ]
        for idx, (label, var, key, width) in enumerate(summary_fields):
            col = idx * 2
            ttk.Label(summary_frame, text=label).grid(row=0, column=col, sticky="w", padx=(0, 6), pady=2)
            value_label = tk.Label(
                summary_frame,
                textvariable=var,
                width=width,
                anchor="center",
                relief=tk.GROOVE,
                borderwidth=1,
                padx=5,
                pady=2,
            )
            value_label.grid(row=0, column=col + 1, sticky="w", padx=(0, 14), pady=2)
            if key == "gpu_detected":
                self.runtime_gpu_detected_label = value_label
            elif key == "gpu_enabled":
                self.runtime_gpu_enabled_label = value_label

        for col_idx in range(len(summary_fields) * 2):
            summary_frame.grid_columnconfigure(col_idx, weight=1 if col_idx % 2 == 1 else 0)

        detail_frame = ttk.Frame(runtime_frame)
        detail_frame.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.runtime_table = ttk.Treeview(detail_frame, columns=("field", "value"), show="headings", height=4)
        self.runtime_table.heading("field", text="Field")
        self.runtime_table.heading("value", text="Value")
        self.runtime_table.column("field", width=160, minwidth=120, anchor="w", stretch=False)
        self.runtime_table.column("value", width=880, minwidth=400, anchor="w", stretch=True)
        runtime_xscroll = ttk.Scrollbar(detail_frame, orient=tk.HORIZONTAL, command=self.runtime_table.xview)
        self.runtime_table.configure(xscrollcommand=runtime_xscroll.set)
        self.runtime_table.grid(row=0, column=0, sticky="nsew")
        runtime_xscroll.grid(row=1, column=0, sticky="ew")
        detail_frame.grid_columnconfigure(0, weight=1)

        perf_frame = ttk.LabelFrame(root_frame, text="Performance")
        perf_frame.pack(fill=tk.X, padx=2, pady=4)
        self.perf_table = ttk.Treeview(perf_frame, columns=("stage", "value"), show="headings", height=8)
        self.perf_table.heading("stage", text="Stage")
        self.perf_table.heading("value", text="Duration / Info")
        self.perf_table.column("stage", width=220, minwidth=180, anchor="w", stretch=False)
        self.perf_table.column("value", width=860, minwidth=420, anchor="w", stretch=True)
        self.perf_table.pack(fill=tk.X, expand=True, padx=6, pady=6)

        result_frame = ttk.LabelFrame(root_frame, text="Result")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=4)
        columns = (
            "round",
            "target",
            "status",
            "attempt",
            "source",
            "match",
            "point",
            "match_score",
            "ocr_score",
            "circles",
        )
        self.result_table = ttk.Treeview(result_frame, columns=columns, show="headings", height=10)
        for col, width in [
            ("round", 60),
            ("target", 140),
            ("status", 120),
            ("attempt", 70),
            ("source", 70),
            ("match", 240),
            ("point", 110),
            ("match_score", 100),
            ("ocr_score", 90),
            ("circles", 70),
        ]:
            self.result_table.heading(col, text=col)
            self.result_table.column(col, width=width, anchor="w")
        self.result_table.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        log_frame = ttk.LabelFrame(root_frame, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=4)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=13, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        config_frame.grid_columnconfigure(1, weight=1)
        config_frame.grid_columnconfigure(2, weight=0)
        config_frame.grid_columnconfigure(3, weight=0)
        config_frame.grid_columnconfigure(4, weight=0)
        config_frame.grid_columnconfigure(5, weight=0)
        config_frame.grid_columnconfigure(6, weight=0)

    def _browse_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Select screenshot",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All Files", "*.*")],
        )
        if path:
            self.image_var.set(path)
            self._log("UI", f"Selected image: {path}")

    def _capture_screen(self) -> None:
        output = Path("captures") / f"gui_capture_{int(time.time() * 1000)}.png"
        try:
            capture = self.ocr_tool.capture_fullscreen(output)
        except Exception as exc:
            messagebox.showerror("Capture failed", str(exc))
            return
        self.image_var.set(capture.image_path)
        self.screen_left_var.set(str(capture.left))
        self.screen_top_var.set(str(capture.top))
        self._log(
            "CAPTURE",
            (
                f"Captured screen to {capture.image_path} "
                f"(w={capture.width}, h={capture.height}, left={capture.left}, top={capture.top})"
            ),
        )

    def _parse_targets(self) -> list[str]:
        raw = self.targets_text.get("1.0", tk.END).strip()
        if not raw:
            return []
        chunks: list[str] = []
        for line in raw.splitlines():
            parts = re.split(r"[;,]", line)
            for part in parts:
                token = part.strip()
                if token:
                    chunks.append(token)
        return chunks

    def _read_numeric_config(self) -> dict[str, Any]:
        cfg = {
            "screen_left": int(self.screen_left_var.get().strip()),
            "screen_top": int(self.screen_top_var.get().strip()),
            "min_score": float(self.min_score_var.get().strip()),
            "threshold": float(self.threshold_var.get().strip()),
            "topk": int(self.topk_var.get().strip()),
            "speed": float(self.speed_var.get().strip()),
            "circle_min": int(self.circle_min_var.get().strip()),
            "circle_max": int(self.circle_max_var.get().strip()),
            "rounds": int(self.rounds_var.get().strip()),
            "max_retries": int(self.max_retries_var.get().strip()),
            "dry_run": bool(self.dry_run_var.get()),
            "strict_mode": bool(self.strict_mode_var.get()),
            "use_gpu": bool(self.use_gpu_var.get()),
        }
        if cfg["circle_min"] < 1 or cfg["circle_max"] < cfg["circle_min"]:
            raise ValueError("Circle range invalid. Require: 1 <= min <= max.")
        if cfg["rounds"] < 1:
            raise ValueError("Rounds must be >= 1.")
        if cfg["max_retries"] < 0:
            raise ValueError("Max retries must be >= 0.")
        return cfg

    def _save_config(self) -> None:
        try:
            numeric_cfg = self._read_numeric_config()
        except ValueError as exc:
            messagebox.showwarning("Validation", f"Invalid config value: {exc}")
            return

        raw_targets = self.targets_text.get("1.0", tk.END).strip()
        targets = self._parse_targets()
        payload = {
            "schema": "ocr_mouse_tester_gui",
            "version": 1,
            "saved_at": int(time.time()),
            "image_path": self.image_var.get().strip(),
            "targets_raw": raw_targets,
            "targets": targets,
            "params": numeric_cfg,
        }

        Path("configs").mkdir(parents=True, exist_ok=True)
        out_path = filedialog.asksaveasfilename(
            title="Save config",
            defaultextension=".json",
            initialdir=str(Path("configs").resolve()),
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not out_path:
            return

        try:
            Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Save config failed", str(exc))
            return
        self._log("CONFIG", f"Saved config: {Path(out_path).resolve()}")

    def _load_config(self) -> None:
        in_path = filedialog.askopenfilename(
            title="Load config",
            initialdir=str(Path("configs").resolve()) if Path("configs").exists() else str(Path(".").resolve()),
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not in_path:
            return

        try:
            data = json.loads(Path(in_path).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Load config failed", f"Cannot read JSON: {exc}")
            return

        params = data.get("params", {})
        self.image_var.set(str(data.get("image_path", "")).strip())
        self.screen_left_var.set(str(params.get("screen_left", self.screen_left_var.get())))
        self.screen_top_var.set(str(params.get("screen_top", self.screen_top_var.get())))
        self.min_score_var.set(str(params.get("min_score", self.min_score_var.get())))
        self.threshold_var.set(str(params.get("threshold", self.threshold_var.get())))
        self.topk_var.set(str(params.get("topk", self.topk_var.get())))
        self.speed_var.set(str(params.get("speed", self.speed_var.get())))
        self.circle_min_var.set(str(params.get("circle_min", self.circle_min_var.get())))
        self.circle_max_var.set(str(params.get("circle_max", self.circle_max_var.get())))
        self.rounds_var.set(str(params.get("rounds", self.rounds_var.get())))
        self.max_retries_var.set(str(params.get("max_retries", self.max_retries_var.get())))
        self.dry_run_var.set(bool(params.get("dry_run", self.dry_run_var.get())))
        self.strict_mode_var.set(bool(params.get("strict_mode", self.strict_mode_var.get())))

        raw = data.get("targets_raw")
        targets = data.get("targets", [])
        if isinstance(raw, str) and raw.strip():
            target_text = raw.strip()
        elif isinstance(targets, list):
            target_text = "\n".join(str(t).strip() for t in targets if str(t).strip())
        else:
            target_text = ""

        self.targets_text.delete("1.0", tk.END)
        if target_text:
            self.targets_text.insert(tk.END, target_text + "\n")

        self.use_gpu_var.set(bool(params.get("use_gpu", self.use_gpu_var.get())))
        self._ensure_runtime_preference(log_event=False)
        self._refresh_runtime_status(log_event=False, reinit_if_needed=False)
        self._log("CONFIG", f"Loaded config: {Path(in_path).resolve()}")

    def _clear_ocr_cache(self) -> None:
        with self.ocr_cache_lock:
            self.ocr_cache.clear()

    def _ensure_runtime_preference(self, *, log_event: bool = True) -> bool:
        desired_use_gpu = bool(self.use_gpu_var.get())
        current_use_gpu = bool(getattr(self.ocr_tool, "use_gpu_requested", True))
        if desired_use_gpu == current_use_gpu:
            return False
        if self.running:
            if log_event:
                self._log("RUNTIME", "Use GPU changed while running; new setting will apply on next run.")
            return False

        self.ocr_tool = DesktopOCRTool(use_gpu=desired_use_gpu)
        self._clear_ocr_cache()
        if log_event:
            self._log("RUNTIME", f"OCR engine reloaded with use_gpu={'YES' if desired_use_gpu else 'NO'}.")
        return True

    def _on_use_gpu_toggled(self) -> None:
        self._refresh_runtime_status(log_event=True, reinit_if_needed=True)

    @staticmethod
    def _format_timing_cell(seconds: float, total: float) -> str:
        if seconds < 0:
            return "-"
        if total > 1e-9:
            return f"{seconds:.3f}s ({seconds / total * 100:.1f}%)"
        return f"{seconds:.3f}s"

    def _reset_performance_panel(self) -> None:
        if self.perf_table is None:
            return
        for row_id in self.perf_table.get_children():
            self.perf_table.delete(row_id)
        for stage, value in [
            ("Total", "-"),
            ("OCR", "-"),
            ("Image Load", "-"),
            ("Search / Match", "-"),
            ("Mouse Actions", "-"),
            ("Other", "-"),
            ("Runtime Mode", "-"),
            ("Use GPU Requested", "-"),
            ("GPU Enabled", "-"),
            ("OCR Cache Hit", "-"),
        ]:
            self.perf_table.insert("", tk.END, values=(stage, value))

    def _render_performance_panel(self, timings: dict[str, Any]) -> None:
        if self.perf_table is None:
            return
        total = float(timings.get("total_sec", 0.0))
        ocr_sec = float(timings.get("ocr_sec", 0.0))
        image_sec = float(timings.get("image_load_sec", 0.0))
        search_sec = float(timings.get("search_sec", 0.0))
        mouse_sec = float(timings.get("mouse_action_sec", 0.0))
        other_sec = float(timings.get("other_sec", max(0.0, total - (ocr_sec + image_sec + search_sec + mouse_sec))))
        runtime_mode = str(timings.get("runtime_mode", "-"))
        use_gpu_requested = "YES" if bool(timings.get("use_gpu_requested", False)) else "NO"
        gpu_enabled = "YES" if bool(timings.get("gpu_enabled", False)) else "NO"
        cache_hit = "YES" if bool(timings.get("ocr_cache_hit", False)) else "NO"

        rows = [
            ("Total", f"{total:.3f}s"),
            ("OCR", self._format_timing_cell(ocr_sec, total)),
            ("Image Load", self._format_timing_cell(image_sec, total)),
            ("Search / Match", self._format_timing_cell(search_sec, total)),
            ("Mouse Actions", self._format_timing_cell(mouse_sec, total)),
            ("Other", self._format_timing_cell(other_sec, total)),
            ("Runtime Mode", runtime_mode),
            ("Use GPU Requested", use_gpu_requested),
            ("GPU Enabled", gpu_enabled),
            ("OCR Cache Hit", cache_hit),
        ]

        for row_id in self.perf_table.get_children():
            self.perf_table.delete(row_id)
        for stage, value in rows:
            self.perf_table.insert("", tk.END, values=(stage, value))

    def _extract_runtime_view(self, runtime: dict[str, Any]) -> dict[str, str]:
        gpu_detected = "YES" if runtime.get("gpu_detected") else "NO"
        gpu_enabled = "YES" if runtime.get("gpu_enabled") else "NO"
        gpu_provider = runtime.get("gpu_provider") or "CPUExecutionProvider"
        mode = runtime.get("acceleration_mode", "cpu")
        use_gpu_requested = "YES" if runtime.get("use_gpu_requested", False) else "NO"

        available = ", ".join(runtime.get("available_providers", [])) or "-"
        component = runtime.get("component_providers", {})
        det = ", ".join(component.get("det", [])) or "-"
        cls = ", ".join(component.get("cls", [])) or "-"
        rec = ", ".join(component.get("rec", [])) or "-"
        return {
            "gpu_detected": gpu_detected,
            "gpu_enabled": gpu_enabled,
            "mode": mode,
            "active_provider": gpu_provider,
            "use_gpu_requested": use_gpu_requested,
            "available": available,
            "det": det,
            "cls": cls,
            "rec": rec,
        }

    @staticmethod
    def _format_runtime_summary(view: dict[str, str]) -> str:
        return (
            f"use_gpu_requested={view['use_gpu_requested']}, "
            f"GPU detected={view['gpu_detected']}, GPU enabled={view['gpu_enabled']}, "
            f"mode={view['mode']}, active_provider={view['active_provider']}"
        )

    @staticmethod
    def _status_color(value: str) -> str:
        upper = value.strip().upper()
        if upper == "YES":
            return "#1f7a1f"
        if upper == "NO":
            return "#c62828"
        return "#424242"

    def _update_runtime_status_colors(self) -> None:
        if self.runtime_gpu_detected_label is not None:
            value = self.runtime_gpu_detected_var.get()
            self.runtime_gpu_detected_label.config(fg=self._status_color(value))
        if self.runtime_gpu_enabled_label is not None:
            value = self.runtime_gpu_enabled_var.get()
            self.runtime_gpu_enabled_label.config(fg=self._status_color(value))

    def _refresh_runtime_status(self, log_event: bool = True, reinit_if_needed: bool = True) -> None:
        if reinit_if_needed:
            self._ensure_runtime_preference(log_event=log_event)
        runtime = self.ocr_tool.get_runtime_info()
        view = self._extract_runtime_view(runtime)
        self.runtime_gpu_detected_var.set(view["gpu_detected"])
        self.runtime_gpu_enabled_var.set(view["gpu_enabled"])
        self.runtime_mode_var.set(view["mode"])
        self.runtime_active_provider_var.set(view["active_provider"])
        self._update_runtime_status_colors()

        for row_id in self.runtime_table.get_children():
            self.runtime_table.delete(row_id)
        for field, value in [
            ("Use GPU Requested", view["use_gpu_requested"]),
            ("Available Providers", view["available"]),
            ("DET Providers", view["det"]),
            ("CLS Providers", view["cls"]),
            ("REC Providers", view["rec"]),
        ]:
            self.runtime_table.insert("", tk.END, values=(field, value))

        summary = self._format_runtime_summary(view)
        if log_event:
            self._log("RUNTIME", summary)

    def _start(self) -> None:
        if self.running:
            return
        image_path = self.image_var.get().strip()
        if not image_path:
            messagebox.showwarning("Validation", "Please choose a screenshot first.")
            return
        if not Path(image_path).exists():
            messagebox.showwarning("Validation", f"Screenshot not found: {image_path}")
            return

        targets = self._parse_targets()
        if not targets:
            messagebox.showwarning("Validation", "Please provide at least one target text.")
            return

        try:
            numeric_cfg = self._read_numeric_config()
        except ValueError as exc:
            messagebox.showwarning("Validation", f"Invalid numeric value: {exc}")
            return
        config = {
            "image_path": Path(image_path),
            "targets": targets,
            **numeric_cfg,
        }

        for row_id in self.result_table.get_children():
            self.result_table.delete(row_id)
        self._clear_log()
        self._reset_performance_panel()
        self._ensure_runtime_preference(log_event=True)
        self._refresh_runtime_status(log_event=False, reinit_if_needed=False)

        self.running = True
        self.stop_event.clear()
        self.status_var.set("Running")
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        self.worker_thread = threading.Thread(target=self._run_worker, args=(config,), daemon=True)
        self.worker_thread.start()
        runtime = self.ocr_tool.get_runtime_info()
        self._refresh_runtime_status(log_event=False, reinit_if_needed=False)
        runtime_summary = self._format_runtime_summary(self._extract_runtime_view(runtime))
        self._log(
            "INIT",
            (
                f"Started with {len(targets)} targets, rounds={config['rounds']}, "
                f"max_retries={config['max_retries']}. "
                f"{runtime_summary}, strict_mode={config['strict_mode']}"
            ),
        )

    def _stop(self) -> None:
        if not self.running:
            return
        self.stop_event.set()
        self._log("STOP", "Stop requested, waiting for current motion loop to stop.")

    def _run_worker(self, config: dict[str, Any]) -> None:
        results: list[TargetResult] = []
        total_expected = int(config.get("rounds", 1)) * len(config.get("targets", []))
        run_started = time.perf_counter()
        timings: dict[str, Any] = {
            "ocr_sec": 0.0,
            "image_load_sec": 0.0,
            "search_sec": 0.0,
            "mouse_action_sec": 0.0,
            "other_sec": 0.0,
            "total_sec": 0.0,
            "ocr_cache_hit": False,
            "runtime_mode": "cpu",
            "use_gpu_requested": bool(config.get("use_gpu", True)),
            "gpu_enabled": False,
        }

        def _emit_done(state: str) -> None:
            total_sec = max(0.0, time.perf_counter() - run_started)
            timings["total_sec"] = total_sec
            known_sec = (
                float(timings.get("ocr_sec", 0.0))
                + float(timings.get("image_load_sec", 0.0))
                + float(timings.get("search_sec", 0.0))
                + float(timings.get("mouse_action_sec", 0.0))
            )
            timings["other_sec"] = max(0.0, total_sec - known_sec)
            self.event_queue.put(
                (
                    "done",
                    {
                        "state": state,
                        "results": results,
                        "total_expected": total_expected,
                        "timings": dict(timings),
                    },
                )
            )

        try:
            tool = self.ocr_tool
            runtime = tool.get_runtime_info()
            runtime_view = self._extract_runtime_view(runtime)
            runtime_summary = self._format_runtime_summary(runtime_view)
            runtime_detail = (
                f"available={runtime_view['available']} | det={runtime_view['det']} | "
                f"cls={runtime_view['cls']} | rec={runtime_view['rec']}"
            )
            self.event_queue.put(
                (
                    "log",
                    (
                        "OCR",
                        runtime_summary,
                    ),
                )
            )
            self.event_queue.put(("log", ("OCR", runtime_detail)))
            timings["runtime_mode"] = str(runtime.get("acceleration_mode", "cpu"))
            timings["use_gpu_requested"] = bool(runtime.get("use_gpu_requested", config.get("use_gpu", True)))
            timings["gpu_enabled"] = bool(runtime.get("gpu_enabled", False))

            targets: list[str] = config["targets"]
            cache_key = self._build_ocr_cache_key(config)
            total_expected = config["rounds"] * len(targets)

            ocr_stage_started = time.perf_counter()
            items = self._get_cached_ocr(cache_key)
            if items is not None:
                timings["ocr_cache_hit"] = True
                self.event_queue.put(("log", ("OCR", f"Cache hit: reuse {len(items)} OCR items.")))
            else:
                self.event_queue.put(("log", ("OCR", "Running OCR (target-driven)...")))
                items = tool.run_ocr(
                    config["image_path"],
                    screen_left=config["screen_left"],
                    screen_top=config["screen_top"],
                    min_score=config["min_score"],
                    expected_targets=targets,
                    early_stop_threshold=max(0.45, float(config["threshold"]) - 0.02),
                    priority_tile_limit=2,
                )
                self._put_cached_ocr(cache_key, items)
                self.event_queue.put(("log", ("OCR", f"OCR completed: {len(items)} text items.")))
            timings["ocr_sec"] += max(0.0, time.perf_counter() - ocr_stage_started)

            image_load_started = time.perf_counter()
            image_bgr = cv2.imread(str(config["image_path"]))
            timings["image_load_sec"] += max(0.0, time.perf_counter() - image_load_started)
            if image_bgr is None:
                raise FileNotFoundError(f"Cannot read screenshot: {config['image_path']}")

            mouse = HumanMouse(speed=config["speed"], stop_event=self.stop_event)
            rounds = config["rounds"]
            max_retries = config["max_retries"]

            for round_index in range(1, rounds + 1):
                if self.stop_event.is_set():
                    raise StoppedError("Stopped before next round.")
                self.event_queue.put(
                    (
                        "log",
                        ("ROUND", f"Starting round {round_index}/{rounds} with {len(targets)} targets."),
                    )
                )

                for idx, target in enumerate(targets, start=1):
                    if self.stop_event.is_set():
                        raise StoppedError("Stopped before locating next target.")

                    max_attempts = 1 + max_retries
                    best_matches: list[dict[str, Any]] = []
                    attempt_used = max_attempts

                    for attempt in range(1, max_attempts + 1):
                        if self.stop_event.is_set():
                            raise StoppedError("Stopped during target retry loop.")
                        search_started = time.perf_counter()
                        effective_threshold = max(0.30, config["threshold"] - 0.05 * (attempt - 1))
                        self.event_queue.put(
                            (
                                "log",
                                (
                                    "SEARCH",
                                    (
                                        f"[round {round_index}/{rounds}] "
                                        f"[target {idx}/{len(targets)}] '{target}', "
                                        f"attempt {attempt}/{max_attempts}, "
                                        f"threshold={effective_threshold:.2f}"
                                    ),
                                ),
                            )
                        )
                        if config["strict_mode"]:
                            plain_matches = locate_candidate_matches(
                                tool=tool,
                                items=items,
                                target=target,
                                threshold=effective_threshold,
                                topk=config["topk"],
                            )
                            if plain_matches:
                                need_strict, strict_reason = should_use_strict_verification(
                                    plain_matches,
                                    threshold=effective_threshold,
                                    attempt=attempt,
                                )
                                if need_strict:
                                    strict_matches = verify_candidate_matches(
                                        tool=tool,
                                        image_bgr=image_bgr,
                                        target=target,
                                        candidates=plain_matches,
                                        screen_left=config["screen_left"],
                                        screen_top=config["screen_top"],
                                        min_score=config["min_score"],
                                        threshold=effective_threshold,
                                        topk=config["topk"],
                                        verify_topk=max(2, min(4, int(config["topk"]))),
                                    )
                                    if strict_matches:
                                        best_matches = strict_matches
                                        attempt_used = attempt
                                        self.event_queue.put(
                                            (
                                                "log",
                                                (
                                                    "VERIFY",
                                                    (
                                                        f"strict applied ({strict_reason}), "
                                                        f"kept {len(best_matches)} candidates"
                                                    ),
                                                ),
                                            )
                                        )
                                        timings["search_sec"] += max(0.0, time.perf_counter() - search_started)
                                        break
                                    self.event_queue.put(
                                        (
                                            "log",
                                            (
                                                "VERIFY",
                                                f"strict applied ({strict_reason}) but failed, retry...",
                                            ),
                                        )
                                    )
                                else:
                                    best_matches = []
                                    for m in plain_matches:
                                        payload = dict(m)
                                        payload["source"] = "ocr-fast"
                                        payload["strict_reason"] = strict_reason
                                        best_matches.append(payload)
                                    attempt_used = attempt
                                    self.event_queue.put(
                                        (
                                            "log",
                                            (
                                                "VERIFY",
                                                (
                                                    f"strict skipped ({strict_reason}), "
                                                    f"use fast candidates={len(best_matches)}"
                                                ),
                                            ),
                                        )
                                    )
                                    timings["search_sec"] += max(0.0, time.perf_counter() - search_started)
                                    break
                            else:
                                self.event_queue.put(("log", ("VERIFY", "no candidate from fast match, retry...")))
                        else:
                            plain_matches = locate_candidate_matches(
                                tool=tool,
                                items=items,
                                target=target,
                                threshold=effective_threshold,
                                topk=config["topk"],
                            )
                            if plain_matches:
                                best_matches = []
                                for m in plain_matches:
                                    payload = dict(m)
                                    payload["source"] = "ocr"
                                    best_matches.append(payload)
                                attempt_used = attempt
                                timings["search_sec"] += max(0.0, time.perf_counter() - search_started)
                                break
                        if attempt < max_attempts:
                            self.event_queue.put(
                                ("log", ("RETRY", f"Target not found yet, retrying: '{target}'"))
                            )
                        timings["search_sec"] += max(0.0, time.perf_counter() - search_started)

                    if not best_matches:
                        result = TargetResult(
                            round_index=round_index,
                            target=target,
                            status="not_found",
                            attempt=max_attempts,
                            source="none",
                            match_text="",
                            x=-1,
                            y=-1,
                            match_score=0.0,
                            ocr_score=0.0,
                            circles=0,
                        )
                        results.append(result)
                        self.event_queue.put(("result", result))
                        self.event_queue.put(
                            (
                                "log",
                                (
                                    "MISS",
                                    (
                                        f"[round {round_index}] target not found after "
                                        f"{max_attempts} attempts: {target}"
                                    ),
                                ),
                            )
                        )
                        continue

                    total_hits = len(best_matches)
                    for hit_idx, best in enumerate(best_matches, start=1):
                        if self.stop_event.is_set():
                            raise StoppedError("Stopped during matched-target execution.")

                        x, y = best["center"]
                        match_source = str(best.get("source", "ocr"))
                        circles = random.randint(config["circle_min"], config["circle_max"])
                        self.event_queue.put(
                            (
                                "log",
                                (
                                    "FOUND",
                                    (
                                        f"[round {round_index}] {target} ({hit_idx}/{total_hits}) -> "
                                        f"'{best['match_text']}' at ({x},{y}), "
                                        f"match={best['match_score']:.3f}, ocr={best['ocr_score']:.3f}, "
                                        f"attempt={attempt_used}, source={match_source}"
                                    ),
                                ),
                            )
                        )

                        status = "located_only"
                        if not config["dry_run"]:
                            mouse_started = time.perf_counter()
                            self.event_queue.put(("log", ("MOVE", f"Moving to ({x},{y}) in human-like path...")))
                            mouse.move_to(x, y)
                            self.event_queue.put(("log", ("SPIN", f"Spinning at target: {circles} circles.")))
                            mouse.spin_at(x, y, circles=circles)
                            self.event_queue.put(("log", ("CLICK", f"Clicking at ({x},{y})")))
                            mouse.click_at(x, y)
                            timings["mouse_action_sec"] += max(0.0, time.perf_counter() - mouse_started)
                            status = "completed"
                            self.event_queue.put(("log", ("DONE", f"Completed target: {target} ({hit_idx}/{total_hits})")))
                        else:
                            self.event_queue.put(
                                ("log", ("DRYRUN", f"Dry-run mode, skip mouse actions ({circles} circles)."))
                            )

                        result = TargetResult(
                            round_index=round_index,
                            target=target,
                            status=status,
                            attempt=attempt_used,
                            source=match_source,
                            match_text=best["match_text"],
                            x=x,
                            y=y,
                            match_score=float(best["match_score"]),
                            ocr_score=float(best["ocr_score"]),
                            circles=circles,
                        )
                        results.append(result)
                        self.event_queue.put(("result", result))

            _emit_done("completed")
        except StoppedError as exc:
            self.event_queue.put(("log", ("STOP", str(exc))))
            _emit_done("stopped")
        except pyautogui.FailSafeException:
            self.event_queue.put(("log", ("FAILSAFE", "PyAutoGUI failsafe triggered at top-left corner.")))
            _emit_done("stopped")
        except Exception as exc:
            self.event_queue.put(("log", ("ERROR", str(exc))))
            _emit_done("error")

    def _drain_events(self) -> None:
        while True:
            try:
                event, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                stage, msg = payload
                self._log(stage, msg)
            elif event == "result":
                result: TargetResult = payload
                self.result_table.insert(
                    "",
                    tk.END,
                    values=(
                        result.round_index,
                        result.target,
                        result.status,
                        result.attempt,
                        result.source,
                        result.match_text,
                        f"({result.x},{result.y})",
                        f"{result.match_score:.3f}",
                        f"{result.ocr_score:.3f}",
                        str(result.circles),
                    ),
                )
            elif event == "done":
                done_state = payload["state"]
                results = payload["results"]
                total_expected = int(payload["total_expected"])
                timings = payload.get("timings", {})
                total = len(results)
                hit_records = sum(1 for r in results if r.status in {"completed", "located_only"})
                hit_targets = len(
                    {(r.round_index, r.target) for r in results if r.status in {"completed", "located_only"}}
                )
                self._render_performance_panel(timings)
                total_sec = float(timings.get("total_sec", 0.0))
                ocr_sec = float(timings.get("ocr_sec", 0.0))
                search_sec = float(timings.get("search_sec", 0.0))
                mouse_sec = float(timings.get("mouse_action_sec", 0.0))
                self._log(
                    "SUMMARY",
                    (
                        f"Run finished: state={done_state}, "
                        f"matched_targets={hit_targets}/{total_expected}, matched_points={hit_records}, records={total}, "
                        f"total={total_sec:.3f}s, ocr={ocr_sec:.3f}s, search={search_sec:.3f}s, mouse={mouse_sec:.3f}s"
                    ),
                )
                self.running = False
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)
                if done_state == "completed":
                    self.status_var.set("Completed")
                elif done_state == "stopped":
                    self.status_var.set("Stopped")
                else:
                    self.status_var.set("Error")

        self.root.after(120, self._drain_events)

    def _build_ocr_cache_key(self, config: dict[str, Any]) -> tuple[Any, ...]:
        image_path = Path(config["image_path"]).resolve()
        stat = image_path.stat()
        normalized_targets = tuple(
            sorted(DesktopOCRTool._normalize_match_text(t) for t in config["targets"] if str(t).strip())
        )
        return (
            str(image_path).lower(),
            int(stat.st_mtime_ns),
            int(stat.st_size),
            int(config["screen_left"]),
            int(config["screen_top"]),
            round(float(config["min_score"]), 3),
            round(float(config["threshold"]), 3),
            int(bool(config.get("use_gpu", True))),
            normalized_targets,
        )

    def _get_cached_ocr(self, cache_key: tuple[Any, ...]) -> list[OCRItem] | None:
        with self.ocr_cache_lock:
            cached = self.ocr_cache.get(cache_key)
            if cached is None:
                return None
            # Return a shallow copy to avoid accidental mutation between runs.
            return list(cached)

    def _put_cached_ocr(self, cache_key: tuple[Any, ...], items: list[OCRItem]) -> None:
        with self.ocr_cache_lock:
            self.ocr_cache[cache_key] = list(items)
            # Keep memory bounded.
            while len(self.ocr_cache) > 8:
                first_key = next(iter(self.ocr_cache))
                del self.ocr_cache[first_key]

    def _log(self, stage: str, message: str) -> None:
        now = time.strftime("%H:%M:%S")
        line = f"[{now}] [{stage}] {message}\n"
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)


def main() -> None:
    set_process_dpi_awareness()
    root = tk.Tk()
    OCRMouseTesterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

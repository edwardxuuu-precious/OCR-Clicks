from __future__ import annotations

import argparse
import ctypes
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pyautogui

from desktop_ocr_tool import DesktopOCRTool, OCRItem
from project_version import PROJECT_VERSION_LABEL


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
    target: str
    status: str
    match_text: str
    x: int
    y: int
    match_score: float
    ocr_score: float
    circles: int


class StatusPrinter:
    @staticmethod
    def log(stage: str, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{stage}] {message}")


class HumanMouse:
    def __init__(self, speed: float = 1.0) -> None:
        self.speed = max(speed, 0.1)
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0

    def move_to(self, target_x: int, target_y: int) -> None:
        start_x, start_y = pyautogui.position()
        dist = math.hypot(target_x - start_x, target_y - start_y)
        if dist < 2:
            return

        base_duration = max(0.16, min(0.95, (dist / 1800.0) + 0.12))
        duration = base_duration / self.speed
        steps = max(24, int(dist / 7))

        # Cubic bezier path: smoother and less robotic than straight linear moves.
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
        direction = random.choice([1, -1])
        points_per_circle = 44
        for circle_index in range(circles):
            r = radius + random.randint(-5, 5)
            for j in range(points_per_circle):
                angle = direction * (2 * math.pi * (j / points_per_circle))
                px = int(x + math.cos(angle) * r)
                py = int(y + math.sin(angle) * r)
                pyautogui.moveTo(px, py)
                time.sleep(random.uniform(0.0035, 0.0075))
            # brief settle between circles, with tiny center drift
            pyautogui.moveTo(x + random.randint(-2, 2), y + random.randint(-2, 2))
            time.sleep(random.uniform(0.02, 0.05))
        pyautogui.moveTo(x, y)

    def click_at(self, x: int, y: int) -> None:
        pyautogui.click(x=x, y=y, button="left")


def locate_best_match(
    tool: DesktopOCRTool,
    items: Iterable[OCRItem],
    target: str,
    threshold: float,
    topk: int,
) -> dict | None:
    threshold_levels = [threshold, max(0.45, threshold - 0.1), 0.36]
    for th in threshold_levels:
        matches = tool.find_text(items, target, threshold=th, topk=topk, case_sensitive=False)
        if matches:
            return matches[0]
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Locate target texts from a screenshot and move mouse in a human-like way."
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {PROJECT_VERSION_LABEL}")
    p.add_argument("--image", required=True, help="Screenshot path to analyze.")
    p.add_argument(
        "--targets",
        nargs="+",
        required=True,
        help='Target text list, e.g. --targets "Settings" "Save" "Exit".',
    )
    p.add_argument("--screen-left", type=int, default=0, help="Absolute offset for X.")
    p.add_argument("--screen-top", type=int, default=0, help="Absolute offset for Y.")
    p.add_argument("--min-score", type=float, default=0.35, help="Minimum OCR confidence.")
    p.add_argument("--threshold", type=float, default=0.62, help="Text match threshold.")
    p.add_argument("--topk", type=int, default=5, help="Candidate count per target.")
    p.add_argument("--speed", type=float, default=1.85, help="Mouse move speed multiplier.")
    p.add_argument("--circle-min", type=int, default=3, help="Min circles at each point.")
    p.add_argument("--circle-max", type=int, default=5, help="Max circles at each point.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only locate and print status; do not move mouse.",
    )
    return p


def main() -> None:
    set_process_dpi_awareness()
    args = build_parser().parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    if args.circle_min < 1 or args.circle_max < args.circle_min:
        raise ValueError("circle range invalid: ensure 1 <= circle-min <= circle-max")

    StatusPrinter.log("INIT", f"加载截图: {image_path.resolve()}")
    StatusPrinter.log("OCR", "开始识别文本...")
    tool = DesktopOCRTool()
    items = tool.run_ocr(
        image_path,
        screen_left=args.screen_left,
        screen_top=args.screen_top,
        min_score=args.min_score,
        expected_targets=args.targets,
        early_stop_threshold=max(0.45, float(args.threshold) - 0.02),
        priority_tile_limit=2,
    )
    StatusPrinter.log("OCR", f"OCR完成，识别到 {len(items)} 条文本")

    mouse = HumanMouse(speed=args.speed)
    results: list[TargetResult] = []

    for idx, target in enumerate(args.targets, start=1):
        StatusPrinter.log("SEARCH", f"[{idx}/{len(args.targets)}] 定位目标: {target}")
        best = locate_best_match(tool, items, target, threshold=args.threshold, topk=args.topk)
        if not best:
            StatusPrinter.log("MISS", f"未找到: {target}")
            results.append(
                TargetResult(
                    target=target,
                    status="not_found",
                    match_text="",
                    x=-1,
                    y=-1,
                    match_score=0.0,
                    ocr_score=0.0,
                    circles=0,
                )
            )
            continue

        x, y = best["center"]
        circles = random.randint(args.circle_min, args.circle_max)
        StatusPrinter.log(
            "FOUND",
            f"{target} -> '{best['match_text']}' @ ({x}, {y}), score={best['match_score']:.3f}",
        )

        if args.dry_run:
            StatusPrinter.log("DRYRUN", f"跳过鼠标动作，预期转圈数: {circles}")
            status = "located_only"
        else:
            StatusPrinter.log("MOVE", f"拟人化移动到 ({x}, {y})")
            mouse.move_to(x, y)
            StatusPrinter.log("SPIN", f"开始转圈: {circles} 圈")
            mouse.spin_at(x, y, circles=circles)
            StatusPrinter.log("CLICK", f"点击坐标: ({x}, {y})")
            mouse.click_at(x, y)
            StatusPrinter.log("DONE", f"目标完成: {target}")
            status = "completed"

        results.append(
            TargetResult(
                target=target,
                status=status,
                match_text=best["match_text"],
                x=x,
                y=y,
                match_score=float(best["match_score"]),
                ocr_score=float(best["ocr_score"]),
                circles=circles,
            )
        )

    StatusPrinter.log("SUMMARY", "执行结果如下")
    for row in results:
        print(
            f"- target={row.target} status={row.status} "
            f"match='{row.match_text}' point=({row.x},{row.y}) "
            f"match_score={row.match_score:.3f} ocr_score={row.ocr_score:.3f} circles={row.circles}"
        )


if __name__ == "__main__":
    main()

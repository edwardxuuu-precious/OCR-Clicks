# OCR Desktop Automation Toolkit

Repository: https://github.com/edwardxuuu-precious/OCR-Clicks.git

本项目是一个本地运行的 OCR + 鼠标自动化工具，面向桌面 AI Agent 场景。

核心能力：

1. 全屏截图（支持多显示器虚拟桌面）
2. 本地 OCR 文本识别并返回绝对坐标
3. 基于目标文本的坐标定位、拟人化移动、转圈、点击
4. 提供 CLI 与本地 GUI（Tkinter）两种测试入口

## Features

- 本地推理：不依赖云 OCR 服务
- 自动加速：启动时自动选择 `CUDA` / `DirectML` / `CPU`
- 高精度匹配：
1. 多阶段 OCR（全图 + 局部增强）
2. 短中文目标的严格匹配策略（降低误点）
3. Strict Mode 二次 ROI 复核
- 高可用测试：
1. 支持重试与阈值逐步放宽
2. 支持每个目标匹配多个坐标（`topk`）
3. 支持多轮执行（`rounds`）
- 可观测性：
1. 实时日志
2. 结果表（轮次、尝试次数、坐标、分数、来源）
3. 配置保存/加载

## Project Structure

```text
.
├─ src
│  ├─ desktop_ocr_tool.py      # OCR 核心：截图/识别/匹配
│  ├─ ocr_mouse_tester.py      # CLI 测试器
│  └─ ocr_mouse_tester_gui.py  # 本地 GUI 测试器
├─ start_gui.ps1            # PowerShell 启动脚本（强制 .venv）
├─ start_gui.bat            # 双击启动脚本（强制 .venv）
├─ requirements.txt
└─ README.md
```

## Requirements

- Windows（当前脚本主要按 Windows 环境调优）
- Python `3.11`（建议与启动脚本保持一致）
- 可选 GPU 环境：
1. NVIDIA CUDA（`onnxruntime-gpu`）
2. DirectML（`onnxruntime-directml`）

## Installation

```powershell
cd C:\Users\edwar\Desktop\OCR
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

## Quick Start

### 1. 全屏截图

```powershell
python .\src\desktop_ocr_tool.py capture --out .\captures\latest.png
```

输出包含 `left/top`（虚拟桌面原点偏移），多屏场景务必使用该偏移。

### 2. OCR 识别所有文本与坐标

```powershell
python .\src\desktop_ocr_tool.py ocr --image .\captures\latest.png --screen-left 0 --screen-top 0
```

单条 OCR 结果包含：

- `text`
- `score`
- `box`（四点坐标，绝对桌面坐标）
- `center`（推荐点击点）
- `left/top/right/bottom`

### 3. 定位目标文本

```powershell
python .\src\desktop_ocr_tool.py find --image .\captures\latest.png --text "Settings" --threshold 0.62 --topk 5
```

返回按匹配分数排序的候选坐标列表。

## CLI Tester

`src/ocr_mouse_tester.py` 支持输入截图与多个目标词，执行：

1. OCR 定位
2. 拟人化移动
3. 转圈
4. 点击

仅定位不移动：

```powershell
python .\src\ocr_mouse_tester.py --image .\captures\latest.png --targets "Edward" "大" "Fandi" --dry-run
```

真实执行：

```powershell
python .\src\ocr_mouse_tester.py --image .\captures\latest.png --targets "Edward" "大" "Fandi"
```

## GUI Tester

启动 GUI：

```powershell
python .\src\ocr_mouse_tester_gui.py
```

若直接运行闪退，使用：

```powershell
.\start_gui.ps1
```

或双击：

```text
start_gui.bat
```

GUI 支持：

- `Capture Screen` 一键截图
- 多目标输入（按行，或 `,` / `;` 分隔）
- `Strict Mode` 复核匹配结果
- `rounds` 多轮执行
- `max_retries` 重试次数
- `topk` 每个目标最多执行的坐标数
- `Save Config` / `Load Config`

## Key Parameters

- `screen_left`, `screen_top`：虚拟桌面偏移，多屏必填正确
- `min_score`：OCR 置信度下限
- `threshold`：文本匹配阈值
- `topk`：每个目标的最大命中坐标数
- `speed`：鼠标移动速度倍率
- `circle_min`, `circle_max`：每次命中的转圈范围
- `rounds`：完整目标序列执行轮数
- `max_retries`：单目标失败后的重试次数

## Runtime Backend

程序自动检测 ONNX Runtime Provider：

1. `CUDAExecutionProvider` -> `cuda`
2. `DmlExecutionProvider` -> `dml`
3. 否则 -> `cpu`

查看方式：

- GUI 日志启动时会输出 `runtime mode` 与 `providers`

## GPU Optional Setup

默认 `requirements.txt` 使用 CPU 版运行时。若需 GPU：

CUDA:

```powershell
pip uninstall -y onnxruntime
pip install onnxruntime-gpu
```

DirectML:

```powershell
pip uninstall -y onnxruntime
pip install onnxruntime-directml
```

安装后重启程序即可自动切换。

## Performance Notes

- 同一截图重复测试时，GUI 会命中 OCR 缓存
- 目标驱动 OCR 会优先做快速全图，再对未命中目标做局部增强
- Strict Mode 准确率更高，但速度会略降
- 大分辨率截图建议仅在必要时提高 `topk` 与 `max_retries`

## Troubleshooting

- GUI 启动即退出：
1. 使用 `start_gui.ps1` / `start_gui.bat`
2. 确认 `.venv` 已安装依赖
- 中文短词误匹配：
1. 开启 `Strict Mode`
2. 适当提高 `threshold`（如 `0.62 -> 0.68`）
- 多屏点击偏移：
1. 使用 `capture` 输出的 `left/top`
2. 对应填入 GUI 的 `screen_left/screen_top`

## Safety

- 实际模式会移动并点击鼠标。
- 调试阶段建议先开启 `Dry Run`。
- `pyautogui` 角落防护（FailSafe）触发时会中止执行。

## Exact Match Policy

Runtime lookup is exact-match only:

- no alias expansion
- no semantic containment
- no fuzzy similarity click

A candidate is accepted only when literal text matches after normalization:
- normalized exact equality, or
- normalized literal substring containment.

## Benchmark Sample Set

Current active benchmark sample set:

- `test/test_sample_img/sample_1.png`
- `test/test_sample_img/sample_2.png`
- `test/test_sample_img/sample_3.png`

Benchmark protocol and baseline:

- `test/TEST_PROTOCOL.md`
- `test/BASELINE.md`


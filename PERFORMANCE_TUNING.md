# OCR 性能优化指南

## 当前基准性能 (RTX 4060 + DirectML)

| 场景 | GPU 时间 | CPU 时间 | GPU 加速 |
|-----|---------|---------|---------|
| **Sample 1** (3440x1440) | **1.7s** | 10.0s | **5.9x** 🚀 |
| **Sample 2** (4480x1440) | **22.6s** | 98.0s | **4.3x** 🚀 |

---

## 智能优化模式 (Smart Optimize)

### 启用方法

在 GUI 中勾选 **"Smart Optimize"** 选项，系统会根据截图尺寸自动选择最佳参数。

### 优化策略

智能优化会根据以下条件自动调整：

| 图片尺寸 | scan_max_side | priority_tile_limit | 适用场景 |
|---------|---------------|---------------------|---------|
| > 4000px (4K+) | 3200 | 2 (有目标) / 3 (无目标) | 超大截图 |
| 3000-4000px | 2880 | 1 (有目标) / 2 (无目标) | 大截图 |
| 2000-3000px | 2560 | 1 (有目标) / 2 (无目标) | 中等截图 |
| < 2000px | 2048 | 1 (有目标) / 2 (无目标) | 小截图 |

### 效果对比

| 模式 | Sample 1 | Sample 2 | 特点 |
|-----|---------|---------|------|
| **默认模式** | 1.7s | 22.6s | 100% 准确率 |
| **Smart + Targets** | 0.95s | 0.75s | **1-3x 加速** |

> ⚠️ **注意**: Smart Optimize 在 Target-Driven 模式下效果最佳（有明确的 `expected_targets`）

---

## 使用方式对比

### 方式 1: 默认模式（推荐，最高准确率）

```python
tool = DesktopOCRTool(use_gpu=True)
items = tool.run_ocr(image_path, min_score=0.35)
```

### 方式 2: 智能优化模式（GUI 推荐）

```python
tool = DesktopOCRTool(use_gpu=True)
items = tool.run_ocr_smart(image_path, min_score=0.35, expected_targets=["设置", "登录"])
```

### 方式 3: Target-Driven 模式（最快）

```python
tool = DesktopOCRTool(use_gpu=True)
items = tool.run_ocr(
    image_path,
    min_score=0.35,
    expected_targets=["设置", "登录"],  # 只找这些文本
    early_stop_threshold=0.58,
    priority_tile_limit=2,
)
```

---

## GUI 使用建议

### 场景 A：实时交互（速度优先）

1. 勾选 **"Smart Optimize"**
2. 在 Targets 中输入明确的查找目标
3. 点击 Start

**预期效果**: 1-3 秒完成 OCR + 点击

### 场景 B：全面扫描（准确率优先）

1. 取消勾选 **"Smart Optimize"**（使用默认模式）
2. Targets 可以为空（扫描全部文本）
3. 点击 Start

**预期效果**: 100% 准确率，速度取决于截图尺寸

### 场景 C：混合模式（平衡）

1. 勾选 **"Smart Optimize"**
2. 输入关键目标
3. 如需全面扫描，Targets 留空

---

## 代码使用示例

### 示例 1: 快速查找特定按钮

```python
from desktop_ocr_tool import DesktopOCRTool

tool = DesktopOCRTool(use_gpu=True)

# 智能优化 + 目标驱动
items = tool.run_ocr_smart(
    "screenshot.png",
    expected_targets=["确定", "取消"],
    min_score=0.35,
)

# 查找匹配结果
matches = tool.find_text(items, "确定", exact_only=True)
if matches:
    x, y = matches[0]["center"]
    print(f"找到按钮位置: ({x}, {y})")
```

### 示例 2: 全面扫描所有文本

```python
tool = DesktopOCRTool(use_gpu=True)

# 默认模式，扫描全部
items = tool.run_ocr("screenshot.png", min_score=0.35)

# 遍历所有识别到的文本
for item in items:
    print(f"{item.text}: {item.center}")
```

---

## 进一步优化建议

如果以上优化仍不能满足需求：

1. **区域裁剪** - 只 OCR 屏幕的特定区域
   ```python
   import cv2
   img = cv2.imread("screenshot.png")
   roi = img[y1:y2, x1:x2]  # 只取感兴趣区域
   cv2.imwrite("roi.png", roi)
   items = tool.run_ocr("roi.png")
   ```

2. **结果缓存** - 避免重复 OCR 同一张截图

3. **异步处理** - 在后台线程运行 OCR，不阻塞主线程

4. **降低 min_score** - 如需更快但接受较低质量结果
   ```python
   items = tool.run_ocr(image_path, min_score=0.50)
   ```

---

## 故障排查

### GPU 未启用
- 检查 Runtime 区域是否显示 "GPU Enabled: YES"
- 如显示 "NO"，尝试重新安装 DirectML:
  ```powershell
  pip uninstall -y onnxruntime onnxruntime-gpu
  pip install onnxruntime-directml
  ```

### OCR 速度慢
- 确认 GPU 模式已启用（应比 CPU 快 4-5 倍）
- 尝试勾选 "Smart Optimize"
- 输入明确的 Targets 减少扫描范围

### 识别准确率低
- 取消 "Smart Optimize" 使用默认模式
- 降低 min_score（如从 0.50 改为 0.30）
- 使用更高质量的截图

# 版本回滚指南

## 当前稳定版本

| 标签 | 版本 | 说明 |
|-----|------|------|
| `v20260303.011-stable` | v20260303.011 | 最满意的稳定版本 |

---

## 如何查看历史版本

```bash
# 查看所有标签
git tag -l

# 查看标签详情
git show v20260303.011-stable

# 查看提交历史
git log --oneline --all
```

---

## 回滚方法

### 方法 1: 临时查看稳定版本（不修改当前代码）

```bash
# 查看稳定版本的代码（ detached HEAD 状态）
git checkout v20260303.011-stable

# 查看完后，回到最新版本
git checkout main
```

---

### 方法 2: 回滚到稳定版本（丢弃之后的所有修改）

⚠️ **警告**: 这会丢失稳定版本之后的所有提交！

```bash
# 1. 确保工作区干净（没有未提交的修改）
git status

# 2. 回滚到稳定版本
# 方式 A: 软回滚（保留修改作为 staged）
git reset --soft v20260303.011-stable

# 方式 B: 混合回滚（保留修改作为 unstaged）
git reset --mixed v20260303.011-stable

# 方式 C: 硬回滚（完全丢弃之后的修改）⚠️ 危险！
git reset --hard v20260303.011-stable

# 3. 强制推送到远程（如果已推送到 GitHub）
git push origin main --force
```

---

### 方法 3: 从稳定版本创建新分支开发

推荐做法：保留 main 分支，从稳定版本开新分支

```bash
# 从稳定版本创建新分支
git checkout -b feature-from-stable v20260303.011-stable

# 在新分支上开发...
git add .
git commit -m "feat: new feature based on stable version"

# 开发完成后合并回 main
git checkout main
git merge feature-from-stable
```

---

### 方法 4: 使用 GitHub 创建 Release（推荐用于发布）

1. 打开 GitHub 仓库页面
2. 点击右侧 "Releases"
3. 点击 "Create a new release"
4. 选择标签: `v20260303.011-stable`
5. 填写发布说明
6. 点击 "Publish release"

---

## 对比当前版本和稳定版本

```bash
# 查看差异
git diff v20260303.011-stable HEAD

# 查看文件差异统计
git diff --stat v20260303.011-stable HEAD

# 查看哪些文件被修改了
git log v20260303.011-stable..HEAD --oneline
```

---

## 紧急回滚脚本

如果开发中出现严重问题，一键回滚到稳定版本：

```bash
#!/bin/bash
# rollback_to_stable.sh

echo "⚠️  警告: 这将回滚到稳定版本 v20260303.011-stable"
echo "⚠️  之后的所有提交将被丢弃！"
read -p "确定要继续吗? (yes/no): " confirm

if [ "$confirm" = "yes" ]; then
    git checkout main
    git reset --hard v20260303.011-stable
    git push origin main --force
    echo "✅ 已回滚到稳定版本 v20260303.011-stable"
else
    echo "❌ 已取消"
fi
```

---

## 标记新版本为稳定

如果后续开发了更好的版本，可以创建新的稳定标签：

```bash
# 1. 确保在 main 分支且代码已提交
git checkout main
git status

# 2. 创建新的稳定标签
git tag -a v20260303.012-stable -m "New stable release v20260303.012"

# 3. 推送到 GitHub
git push origin v20260303.012-stable
```

---

## GitHub 上的标签

- 标签页面: https://github.com/edwardxuuu-precious/OCR-Clicks/tags
- 可以下载任意标签的 ZIP 压缩包
- 可以在 Releases 页面查看带说明的版本

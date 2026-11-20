# 发布流程（RELEASING）

两条 GitHub Actions 工作流：

| 工作流 | 触发 | 做什么 |
|---|---|---|
| [CI](../.github/workflows/ci.yml) | push 到 `main`、PR、手动 | 安装依赖 → `python main.py --check`（16 项）→ 打印版本号 |
| [Release](../.github/workflows/release.yml) | 推送 `v*` 标签、手动 | 自检 → PyInstaller `--onedir` 打包 → 补 `_stdlib.zip` → 组装外置目录 → zip → **草稿** Release |

CI 徽章（把 `USER/REPO` 换成实际地址后启用）：

```markdown
[![CI](https://github.com/USER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/ci.yml)
```

---

## 发一个版本

### 1. 改版本号（两处，必须同步）

- `rate_warden/__init__.py` 里的 `__version__ = "1.0.0"`
- `manifest.json` 里的 `"version": "1.0.0"`

```powershell
# 确认两处一致
Select-String -Path rate_warden\__init__.py, manifest.json -Pattern '\d+\.\d+\.\d+'
```

### 2. 本地先过一遍

```powershell
python main.py --check
```

必须 16/16 全绿，否则不要打标签。

### 3. 提交并推送

```powershell
git add -A
git commit -m "chore: bump to v1.0.1"
git push
```

CI 会自动在 `main` 上跑一遍自检，确认绿灯再继续。

### 4. 打标签并推送

```powershell
git tag v1.0.1
git push origin v1.0.1
```

标签推上去后，Release 工作流开始构建，约 3–6 分钟。

### 5. 审草稿并发布

打开仓库的 **Releases** 页面，会看到一条 `v1.0.1` 草稿（因为工作流里 `draft: true`）。
检查：

- 附件是 `RateWarden-v1.0.1-windows-x64.zip`
- 生成的 release notes 合理（可以手动补一句「本次变更」）
- 体感上把 `安装`、`使用前提`、`安全提示` 三块留在正文里

确认无误后点 **Publish release**。

### 6. 下载包自检（推荐每次做）

```powershell
# 在一个干净目录里
Expand-Archive RateWarden-v1.0.1-windows-x64.zip -DestinationPath .\rw
.\rw\RateWarden.exe --version
.\rw\RateWarden.exe            # 应该能看到界面
```

解压后应当包含：

```
RateWarden/
├─ RateWarden.exe
├─ _internal/          PyInstaller 运行时（Qt DLL 等）
├─ rules_user/         放你自己的规则
├─ waves/library.json  波形库
├─ logs/               运行日志
├─ config.example.json
├─ README.md
└─ LICENSE
```

---

## 出问题怎么查

| 现象 | 原因 / 处理 |
|---|---|
| CI 在 `pip install` 失败 | PySide6 没有对应 Python 版本的 wheel。把 `python-version` 改成 `'3.11'` 重试 |
| `pyinstaller` 步骤报 `Unable to find "dghub_sdk"` | 正常，是 `--hidden-import` 找不到可选包，只是警告。真要消除就删掉那一行 |
| 打包成功但 exe 闪退 | 用 `RateWarden.exe` 的控制台版排查：临时把 `--windowed` 去掉再构建一次 |
| 目标机报 `platform plugin not found` | 用了 `--onefile` 或漏了 Qt 插件。本项目固定 `--onedir`，且 `_internal/` 必须和 exe 同级 |
| 波形库/规则改了不生效 | `rules_user/`、`waves/` 必须在 exe **外面**；被压进 exe 里就无法热加载 |
| 想起草但 Release 没出现 | 标签格式必须是 `v开头`（`v1.0.1`），不是 `1.0.1` |
| 打包版自检报「缺少内置规则」 | 漏了 `--add-data "rate_warden/rules/*.py;rate_warden/rules"`。规则是运行期按文件路径加载的，不能只靠 PyInstaller 的模块收集 |
| 打包版自检报 `ModuleNotFoundError: difflib` 等 | 漏了 `python scripts/make_stdlib_zip.py dist/RateWarden/_internal`。动态加载的规则 import 什么，PyInstaller 静态分析看不到 |

### 为什么需要 `_stdlib.zip`

规则插件在运行期由 `loader.py` 从磁盘动态 `exec_module`。PyInstaller 只做静态分析，
看不到规则文件里的 `import difflib` / `import textwrap`，于是这些纯 Python 标准库不会被收进包。
`scripts/make_stdlib_zip.py` 把解释器标准库顶层 `*.py` 打成一个 zip 放进 `_internal/`，
`config.py` 在 `sys.frozen` 时把它追加到 `sys.path` —— zipimport 可直接从 zip 内导入。

---

## 手动触发构建

不想打标签、只想验证打包链路时，在 **Actions → Release → Run workflow** 手动触发。
注意这种情况下 `github.ref_name` 是分支名（如 `main`），zip 名会变成 `RateWarden-main-windows-x64.zip`，
且草稿 Release 会以该名字创建 —— 验证完记得把草稿删掉。

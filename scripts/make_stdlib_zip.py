"""把 Python 纯标准库（*.py）打成 _internal/_stdlib.zip。

为什么需要：Rate Warden 的规则是**运行期从磁盘动态加载**的用户代码
（rules_user/*.py），PyInstaller 的静态分析看不到它们 import 了什么，
导致 `difflib`、`textwrap` 这类纯 Python 标准库在打包版里缺失。

做法：构建时把解释器标准库里的顶层 *.py 收进一个 zip，放到 _internal/，
由 config.py 在冻结时追加到 sys.path（zipimport 可直接从 zip 中导入）。

被排除的：C 扩展（已由 PyInstaller 按需打包）、site-packages、
          与桌面程序无关的大块头（idlelib / tkinter / test / unittest 等）。

用法：
    python scripts/make_stdlib_zip.py <目标目录>
"""

from __future__ import annotations

import sys
import sysconfig
import zipfile
from pathlib import Path

# 与运行无关的模块，排除后会显著减小体积
EXCLUDE_NAMES = {
    "antigravity",
    "__phello__",
    "pydoc",
    "this",
}
EXCLUDE_PREFIXES = (
    "idlelib",
    "tkinter",
    "turtledemo",
    "_tkinter",
    "lib2to3",
    "ensurepip",
    "venv",
    "distutils",
    "pydoc_data",
    "unittest",
    "sqlite3",
    "curses",
    "test_",
    "tests",
    "site-packages",
)


def collect() -> list[Path]:
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    files = []
    for path in sorted(stdlib.glob("*.py")):
        stem = path.stem
        if stem in EXCLUDE_NAMES:
            continue
        if any(stem == p or stem.startswith(p) for p in EXCLUDE_PREFIXES):
            continue
        files.append(path)
    return files


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    target = Path(argv[1]).resolve()
    target.mkdir(parents=True, exist_ok=True)
    out = target / "_stdlib.zip"

    files = collect()
    if not files:
        print("没有收集到标准库源文件，检查 sysconfig path", file=sys.stderr)
        return 1

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            zf.write(path, arcname=path.name)

    size_kb = out.stat().st_size / 1024
    print(f"已生成 {out}（{len(files)} 个模块，{size_kb:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

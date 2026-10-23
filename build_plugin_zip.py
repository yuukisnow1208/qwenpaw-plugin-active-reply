# -*- coding: utf-8 -*-
"""把插件目录打成可直接在 WebUI「安装插件」里上传的 ZIP。

ZIP 结构（官方推荐，安装器认「唯一的顶层目录」）：
    <plugin-id>/
      plugin.json
      plugin.py
      ...

用法：
    python build_plugin_zip.py              # 默认打包 splitter
    python build_plugin_zip.py active-reply # 打包指定目录
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

#: 运行期产物 / 缓存，不打包
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git"}
EXCLUDE_FILES = {"config.json", ".DS_Store", "Thumbs.db"}


def build(name: str) -> Path:
    src = ROOT / name
    if not (src / "plugin.json").exists():
        raise SystemExit(f"找不到 {src}/plugin.json")

    manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
    plugin_id = manifest["id"]
    version = manifest["version"]
    out = ROOT / f"{plugin_id}-{version}.zip"

    files = []
    for path in sorted(src.rglob("*")):
        if path.is_dir():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix == ".pyc" or path.name in EXCLUDE_FILES:
            continue
        files.append(path)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = Path(plugin_id) / path.relative_to(src)
            zf.write(path, arcname.as_posix())

    print(f"已生成: {out}  ({out.stat().st_size} bytes)")
    print("压缩包内容:")
    with zipfile.ZipFile(out) as zf:
        for info in zf.infolist():
            print(f"  {info.file_size:>7}  {info.filename}")
        bad = zf.testzip()
        print("完整性校验:", "OK" if bad is None else f"损坏 {bad}")

        roots = {n.split("/")[0] for n in zf.namelist()}
        print(
            "顶层条目:",
            roots,
            "->",
            "结构正确" if roots == {plugin_id} else "结构异常",
        )
    return out


def main() -> int:
    targets = sys.argv[1:] or ["splitter"]
    for name in targets:
        build(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

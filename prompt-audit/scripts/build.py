#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建脚本：分片 + manifest → 完整版产物。

用法：
    build.py                # 路径取部署配置（~/.config/prompt-audit/config.yaml）
    build.py --src ... --manifest ... --dist ...   # 参数覆盖配置
无配置时用中性默认值：./src、./manifest.yaml、./dist。

分片排序规则（已定案）：按 manifest `src:` 段的键序拼接。
YAML 映射在 Python 3.7+ 保插入序，yaml.safe_load 返回的 dict 即文件书写序，
不依赖文件名排序，也不需要给 manifest 加 order 字段。

产物：
    <dist_dir>/AGENTS.full.md    完整版：全部 src 分片 + 头部「规则索引」
退出码：0=正常；1=出错。
"""

import argparse
import os
import re
import sys

try:
    import yaml
except ImportError:
    raise SystemExit(
        "错误：需要 PyYAML。安装：pip3 install --user pyyaml"
    )

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, path_of

CFG, _ = load_config()
DEFAULT_SRC = path_of(CFG, "src_dir", "./src")
DEFAULT_MANIFEST = path_of(CFG, "manifest", "./manifest.yaml")
DEFAULT_DIST = path_of(CFG, "dist_dir", "./dist")
# 规则索引里展示的规则目录（原样 ~/ 路径，便于 agent 直接读）
RULES_DIR_DISPLAY = str(CFG.get("rules_dir") or "rules").rstrip("/")



def read_file(path):
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        return fh.read().rstrip()


def build_route_table(manifest):
    """规则索引：从 manifest rules 段生成两列表（文档 + 描述）。

    描述合并内容与适用场景；manifest 仍带 route 时自动并进描述（兼容旧格式）。"""
    rules = manifest.get("rules") or {}
    rows = []
    for name, meta in rules.items():
        desc = str(meta.get("desc", "")).strip()
        route = str(meta.get("route", "")).strip()
        if route:
            desc = (desc + "。" + route).rstrip("。") if desc else route
        location = "`%s/%s.md`" % (RULES_DIR_DISPLAY, name)
        rows.append((location, desc))
    if not rows:
        return ""
    lines = [
        "## 规则索引",
        "",
        "| 文档 | 描述 |",
        "|---|---|",
    ]
    for location, desc in rows:
        lines.append(f"| {location} | {desc} |")
    return "\n".join(lines)


def build_full(src_dir, manifest):
    """完整版：规则索引 + 全部 src 分片（按 manifest src 段键序）。"""
    parts = ["# 全局 Agent 规范"]
    table = build_route_table(manifest)
    if table:
        parts.append(table)
    for name in manifest.get("src", {}):
        path = os.path.join(src_dir, name + ".md")
        if not os.path.isfile(path):
            raise SystemExit(f"错误：manifest 列出的分片不存在 {path}")
        parts.append(read_file(path))
    return "\n\n".join(p for p in parts if p.strip()) + "\n", 0



def main():
    parser = argparse.ArgumentParser(
        description="构建：src 分片 + manifest → dist/AGENTS.full.md。"
                    "退出码 0=正常 1=出错。"
    )
    parser.add_argument("--src", default=DEFAULT_SRC, help="分片目录（默认取部署配置 src_dir，无配置时 ./src）")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST,
                        help="manifest 路径（默认取部署配置 manifest，无配置时 ./manifest.yaml）")
    parser.add_argument("--dist", default=DEFAULT_DIST, help="产物目录（默认取部署配置 dist_dir，无配置时 ./dist）")
    args = parser.parse_args()

    src_dir = os.path.expanduser(args.src)
    manifest_path = os.path.expanduser(args.manifest)
    dist_dir = os.path.expanduser(args.dist)

    with open(manifest_path, encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)
    if not manifest or not manifest.get("src"):
        raise SystemExit(f"错误：manifest 无 src 段或为空 {manifest_path}")

    os.makedirs(dist_dir, exist_ok=True)

    full_text, _ = build_full(src_dir, manifest)
    full_path = os.path.join(dist_dir, "AGENTS.full.md")
    with open(full_path, "w", encoding="utf-8") as fh:
        fh.write(full_text)
    print(f"已产出完整版：{full_path}（{len(full_text)} 字符，"
          f"{len(manifest['src'])} 个分片，排序=manifest src 段键序）")



if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建脚本：分片 + manifest → 完整版产物。

用法：
    prompt-audit/scripts/build.py                     # 全部用默认路径
    build.py --src ~/.agent/src --manifest ~/prompt-workspace/manifest.yaml --dist ~/prompt-workspace/dist

分片排序规则（已定案）：按 manifest `src:` 段的键序拼接。
YAML 映射在 Python 3.7+ 保插入序，yaml.safe_load 返回的 dict 即文件书写序，
不依赖文件名排序，也不需要给 manifest 加 order 字段。

产物：
    dist/AGENTS.full.md    完整版：全部 src 分片 + 头部「按需规则路由表」
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

DEFAULT_SRC = "~/.agent/src"
DEFAULT_MANIFEST = "~/prompt-workspace/manifest.yaml"
DEFAULT_DIST = "~/prompt-workspace/dist"



def read_file(path):
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        return fh.read().rstrip()


def build_route_table(manifest):
    """规则索引：从 manifest rules 段生成。
    面向 agent 的表格只说「在什么情况下必读什么」——
    不写治理者元话语（按需/路由/不读的后果）。"""
    rules = manifest.get("rules") or {}
    rows = []
    for name, meta in rules.items():
        route = str(meta.get("route", "")).strip()
        location = "`~/.agent/rules/%s.md`" % name
        rows.append((route, location))
    if not rows:
        return ""
    lines = [
        "## 规则索引",
        "",
        "| 在如下情况下必读 | 文档路径 |",
        "|---|---|",
    ]
    for route, location in rows:
        lines.append(f"| {route} | {location} |")
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
    parser.add_argument("--src", default=DEFAULT_SRC, help="分片目录（默认 ~/.agent/src）")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST,
                        help="manifest 路径（默认 ~/prompt-workspace/manifest.yaml）")
    parser.add_argument("--dist", default=DEFAULT_DIST, help="产物目录（默认 ~/prompt-workspace/dist）")
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步脚本：把构建产物写回真身（真身路径由部署配置 true_file 决定，各 runtime 软链于真身）。

安全设计：
1. 只写真身这一个文件，软链自动生效。
2. 写前强制备份到部署配置 backup_dir。
3. 外来托管块（定义在部署配置 external_blocks）从现有真身原样搬运、逐字节保留，
   由对应工具自行升级，本脚本不改其内容。块定义可含：
   - doc_governance：标题界定的节（doc-init/doc-compact 按版本号整块替换管理）
   - mcp：begin/end 标记块（同步工具按固定模板 upsert）
4. 相邻外来块之间放隔断标题（配置 external_blocks.doc_governance.separator）：
   块升级时删除边界常是「下一个 `## ` 标题」，没有隔断会把紧随其后的相邻块一起吞掉。
   隔断标题属于本脚本的受管内容，外来块本身一字不改。
5. 原子写入：先写同目录临时文件再 mv（os.replace），避免半写状态被其他工具读到。
6. 写后校验：重读真身，逐字节比对预期内容，并确认外来块原样保留。
7. 本脚本绝不主动运行外部块的升级脚本，绝不修改外来块内容。

用法：
    sync.py --dry-run        # 预览变更 diff，不写文件
    sync.py --confirm        # 真正写入（前提：已看过 --dry-run 预览）
    sync.py                  # 不加参数会报错，强制 dry-run 先行
退出码：0=成功；1=校验失败；2=用法错误。
"""

import argparse
import difflib
import hashlib
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, path_of

CFG, CFG_PATH = load_config()
_EXT = CFG.get("external_blocks") or {}
_DOC = _EXT.get("doc_governance") or {}
_MARKER_BLOCKS = [
    {"begin": str(b.get("begin", "")).strip(), "end": str(b.get("end", "")).strip()}
    for b in (_EXT.get("marker_blocks") or [])
    if b.get("begin") and b.get("end")
]

TRUE_FILE = path_of(CFG, "true_file")
BACKUP_DIR = path_of(CFG, "backup_dir")
_dist = path_of(CFG, "dist_dir")
DEFAULT_SOURCE = os.path.join(_dist, "AGENTS.full.md") if _dist else "./dist/AGENTS.full.md"

DOC_GOV_HEADING = str(_DOC.get("heading", "")).strip()
# 隔断标题：见文件头注释第 4 条，防外来块升级越界吞掉相邻块。
SEPARATOR_HEADING = str(_DOC.get("separator", "## 附：外部托管区块")).strip()


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def extract_marker_blocks(text):
    """提取全部标记块（每块 begin..end 标记行，含标记，逐字节原样）。

    返回 (块文本列表, 剩余文本)。块的拼接顺序按配置 marker_blocks 的书写序。
    """
    lines = text.splitlines(keepends=True)
    pairs = [(b["begin"], b["end"]) for b in _MARKER_BLOCKS]
    blocks, remainder = [], []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        pair = next(((bg, ed) for bg, ed in pairs if line == bg), None)
        if pair:
            bg, ed = pair
            j = i
            while j < n and lines[j].strip() != ed:
                j += 1
            if j < n:
                blocks.append("".join(lines[i : j + 1]))
                i = j + 1
                continue
        remainder.append(lines[i])
        i += 1
    return blocks, "".join(remainder)


def extract_doc_gov_section(text):
    """提取「项目文档管理」节：标题行到下一个 `## ` 标题行前（或文件末尾）。

    输入应是已移除 mcp 块后的文本，防止把 begin 标记误并入本节。
    未配置标题时跳过。
    """
    if not DOC_GOV_HEADING:
        return None
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == DOC_GOV_HEADING:
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "".join(lines[start:end]).rstrip()


def check_no_at_lines(text):
    """doc-governance 升级时的插入锚点是首个 `@` 开头行，产物里不应出现（INJECTION_MECHANISM 约束 4）。"""
    return [ln for ln in text.splitlines() if ln.startswith("@")]


def assemble(product, doc_gov, marker_blocks):
    """组装新文件：产物 + 外来块（隔断标题隔开，标记块按配置顺序）。"""
    parts = [product.rstrip()]
    if doc_gov:
        parts.append(doc_gov.rstrip())
    if doc_gov and marker_blocks:
        parts.append(SEPARATOR_HEADING)
    for block in marker_blocks:
        parts.append(block.rstrip())
    return "\n\n".join(parts) + "\n"


def build_expected(source_text, true_text):
    """返回 (预期新内容, 搬运信息 dict)。"""
    blocks, remainder = extract_marker_blocks(true_text)
    doc_gov = extract_doc_gov_section(remainder)
    expected = assemble(source_text, doc_gov, blocks)
    info = {
        "doc_gov": doc_gov,
        "blocks": blocks,
        "doc_gov_lines": len(doc_gov.splitlines()) if doc_gov else 0,
        "blocks_lines": [len(b.splitlines()) for b in blocks],
    }
    return expected, info


def verify(true_text, expected, info):
    """写后校验：外来块逐字节保留 + 全文与预期一致。"""
    problems = []
    if true_text != expected:
        problems.append("写回内容与预期组装结果不一致")
    for block in info["blocks"]:
        if block.rstrip() not in true_text:
            problems.append("标记块未逐字节保留")
    if info["doc_gov"] is not None and info["doc_gov"] not in true_text:
        problems.append(f"外部块未逐字节保留：{DOC_GOV_HEADING}")
    for b in _MARKER_BLOCKS:
        if b["begin"] not in true_text or b["end"] not in true_text:
            problems.append(f"标记缺失：{b['begin']}（对应工具下次运行会把块追加到文件末尾造成重复）")
    if DOC_GOV_HEADING and DOC_GOV_HEADING not in true_text:
        problems.append(f"外部块标题缺失：{DOC_GOV_HEADING}")
    return problems


def main():
    parser = argparse.ArgumentParser(
        description="同步：把完整版产物写回真身（路径取部署配置），"
                    "原样保留外部托管块。默认 dry-run 先行，--confirm 才真写。"
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="完整版产物路径（默认取部署配置 dist_dir/AGENTS.full.md）")
    parser.add_argument("--dry-run", action="store_true", help="只预览变更，不写文件")
    parser.add_argument("--confirm", action="store_true",
                        help="真正写入（前提：已运行过 --dry-run 并确认 diff）")
    args = parser.parse_args()

    if not args.dry_run and not args.confirm:
        print("错误：本脚本强制 dry-run 先行。请先运行：")
        print(f"  {sys.argv[0]} --dry-run")
        print("确认 diff 无误后再加 --confirm 执行写入。")
        sys.exit(2)
    if args.dry_run and args.confirm:
        print("提示：--dry-run 与 --confirm 同时给出，按 dry-run 处理，不写文件。")
        args.confirm = False

    if not TRUE_FILE:
        raise SystemExit(
            "错误：未找到部署配置（查找路径 " + CFG_PATH + "）。\n"
            "从本 skill 目录复制 config.example.yaml 到上述路径，按本机情况修改后再运行。")
    source_path = os.path.expanduser(args.source)
    if not os.path.isfile(source_path):
        raise SystemExit(f"错误：产物不存在 {source_path}，请先运行 build.py")
    if not os.path.isfile(TRUE_FILE):
        raise SystemExit(f"错误：真身不存在 {TRUE_FILE}")

    with open(source_path, encoding="utf-8") as fh:
        source_text = fh.read()
    with open(TRUE_FILE, encoding="utf-8") as fh:
        true_text = fh.read()

    at_lines = check_no_at_lines(source_text)
    if at_lines:
        print("警告：产物中存在以 @ 开头的行（doc-governance 升级时会插到它之前）：")
        for ln in at_lines[:5]:
            print(f"    {ln[:60]}")

    expected, info = build_expected(source_text, true_text)

    print("=" * 60)
    print("同步预览")
    print("=" * 60)
    print(f"产物：{source_path}（{len(source_text)} 字符，sha1 {sha1(source_text)}）")
    print(f"真身：{TRUE_FILE}（{len(true_text)} 字符，sha1 {sha1(true_text)}）")
    blocks_desc = "、".join(f"标记块{i+1} {n} 行" for i, n in enumerate(info["blocks_lines"]))
    print(f"外来块搬运：{DOC_GOV_HEADING or 'doc-governance'} 节 {info['doc_gov_lines']} 行"
          f"（原样保留）；{blocks_desc or '无标记块'}（原样保留）")
    if info["doc_gov"] and info["blocks"]:
        print(f"隔断标题：`{SEPARATOR_HEADING}`（防外部块升级越界吞相邻块）")
    if info["doc_gov"] is None:
        print(f"警告：真身中未找到 {DOC_GOV_HEADING} 节，本次不搬运该块"
              "（对应管理工具下次运行会补注入）")
    found_begins = {b.splitlines()[0].strip() for b in info["blocks"]}
    for b in _MARKER_BLOCKS:
        if b["begin"] not in found_begins:
            print(f"警告：真身中未找到标记块 {b['begin']}，本次不搬运"
                  "（对应工具下次运行会追加到文件末尾）")
    print(f"预期新内容：{len(expected)} 字符，sha1 {sha1(expected)}")

    # diff 预览
    diff = list(difflib.unified_diff(
        true_text.splitlines(), expected.splitlines(),
        fromfile="当前真身", tofile="同步后", lineterm=""))
    print("\n----- diff 预览（前 200 行）-----")
    for line in diff[:200]:
        print(line)
    if len(diff) > 200:
        print(f"…（共 {len(diff)} 行 diff，已截断）")
    print("----- diff 预览结束 -----")

    if not args.confirm:
        print("\n[dry-run] 未写入任何文件。确认无误后运行 --confirm 执行写入。")
        sys.exit(0)

    # --- 真写：备份 → 原子写入 → 校验 ---
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_path = os.path.join(
        BACKUP_DIR, "AGENTS.md." + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(TRUE_FILE, backup_path)
    print(f"\n已备份真身 → {backup_path}")

    tmp_path = TRUE_FILE + ".tmp-prompt-audit"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(expected)
    os.replace(tmp_path, TRUE_FILE)  # 原子替换

    with open(TRUE_FILE, encoding="utf-8") as fh:
        written = fh.read()
    problems = verify(written, expected, info)
    if problems:
        print("写后校验【失败】：")
        for p in problems:
            print(f"    - {p}")
        print(f"原真身已备份在 {backup_path}，可手动恢复。")
        sys.exit(1)
    print("写后校验【通过】：")
    print(f"    - 全文与预期组装结果逐字节一致（sha1 {sha1(written)}）")
    print(f"    - {DOC_GOV_HEADING} 节 {info['doc_gov_lines']} 行逐字节保留")
    for n in info["blocks_lines"]:
        print(f"    - 标记块 {n} 行逐字节保留")
    print("提示：本脚本不升级外部托管块；如需升级（如 doc-governance 版本），"
          "另行运行对应管理工具。")
    print("完成：真身已更新，各 runtime 软链自动生效。退出码 0。")


if __name__ == "__main__":
    main()

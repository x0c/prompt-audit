#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步脚本：把构建产物写回真身 ~/.config/agentsync/AGENTS.md（各 runtime 软链于此）。

安全设计（依据 prompt-workspace/analysis/INJECTION_MECHANISM.md 第 4 节）：
1. 只写真身这一个文件，软链自动生效。
2. 写前强制备份到 ~/.config/agentsync/backups/。
3. 两个外来块从现有真身原样搬运、逐字节保留：
   - 「项目文档管理」节（doc-governance，含版本注释，由 doc-init/doc-compact 的
     insert_doc_governance.py 版本化替换管理）
   - `<!-- agentsync:begin mcp -->` 到 `<!-- agentsync:end mcp -->` 块
     （由 agentsync 工具按固定模板 upsert）
4. 两个外来块之间放隔断标题 `## 附：外部托管区块`：
   doc-governance 升级时 _remove_section 会删到下一个 `## ` 标题为止，
   没有隔断会把紧随其后的 agentsync begin 标记一起吞掉（INJECTION_MECHANISM 坑 2）。
   隔断标题属于本脚本的受管内容，外来块本身一字不改。
5. 原子写入：先写同目录临时文件再 mv（os.replace），避免半写状态被 agentsync --watch 读到。
6. 写后校验：重读真身，逐字节比对预期内容，并确认两个外来块原样保留。
7. 本脚本绝不主动执行 insert_doc_governance.py，绝不修改外来块内容。

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

TRUE_FILE = os.path.expanduser("~/.config/agentsync/AGENTS.md")
BACKUP_DIR = os.path.expanduser("~/.config/agentsync/backups")
DEFAULT_SOURCE = os.path.expanduser("~/prompt-workspace/dist/AGENTS.full.md")

MCP_BEGIN = "<!-- agentsync:begin mcp -->"
MCP_END = "<!-- agentsync:end mcp -->"
DOC_GOV_HEADING = "## 项目文档管理"
# 隔断标题：见文件头注释第 4 条，防 doc-governance 升级越界吞掉 agentsync 块。
SEPARATOR_HEADING = "## 附：外部托管区块"


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def extract_mcp_block(text):
    """提取 agentsync mcp 块（begin..end 标记行，含标记，逐字节原样）。"""
    lines = text.splitlines(keepends=True)
    begin_idx = end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == MCP_BEGIN and begin_idx is None:
            begin_idx = i
        elif line.strip() == MCP_END and begin_idx is not None:
            end_idx = i
            break
    if begin_idx is None or end_idx is None:
        return None, text
    block = "".join(lines[begin_idx : end_idx + 1])
    remainder = "".join(lines[:begin_idx]) + "".join(lines[end_idx + 1 :])
    return block, remainder


def extract_doc_gov_section(text):
    """提取「项目文档管理」节：标题行到下一个 `## ` 标题行前（或文件末尾）。

    输入应是已移除 mcp 块后的文本，防止把 begin 标记误并入本节。
    """
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


def assemble(product, doc_gov, mcp_block):
    """组装新文件：产物 + 外来块（隔断标题隔开）。"""
    parts = [product.rstrip()]
    if doc_gov:
        parts.append(doc_gov.rstrip())
    if doc_gov and mcp_block:
        parts.append(SEPARATOR_HEADING)
    elif mcp_block and not doc_gov:
        # 真身里没有 doc-governance 节时，隔断标题无存在必要，但保留也无害；此处不加以简化输出。
        pass
    if mcp_block:
        parts.append(mcp_block.rstrip())
    return "\n\n".join(parts) + "\n"


def build_expected(source_text, true_text):
    """返回 (预期新内容, 搬运信息 dict)。"""
    mcp_block, remainder = extract_mcp_block(true_text)
    doc_gov = extract_doc_gov_section(remainder)
    expected = assemble(source_text, doc_gov, mcp_block)
    info = {
        "doc_gov": doc_gov,
        "mcp_block": mcp_block,
        "doc_gov_lines": len(doc_gov.splitlines()) if doc_gov else 0,
        "mcp_lines": len(mcp_block.splitlines()) if mcp_block else 0,
    }
    return expected, info


def verify(true_text, expected, info):
    """写后校验：外来块逐字节保留 + 全文与预期一致。"""
    problems = []
    if true_text != expected:
        problems.append("写回内容与预期组装结果不一致")
    if info["mcp_block"] is not None and info["mcp_block"].rstrip() not in true_text:
        problems.append("agentsync mcp 块未逐字节保留")
    if info["doc_gov"] is not None and info["doc_gov"] not in true_text:
        problems.append("「项目文档管理」节未逐字节保留")
    if MCP_BEGIN not in true_text or MCP_END not in true_text:
        problems.append("agentsync begin/end 标记缺失（下次 agentsync 运行会把块追加到 EOF 造成重复）")
    if DOC_GOV_HEADING not in true_text:
        problems.append("「项目文档管理」标题缺失")
    return problems


def main():
    parser = argparse.ArgumentParser(
        description="同步：把 dist/AGENTS.full.md 写回真身 ~/.config/agentsync/AGENTS.md，"
                    "原样保留两个外来块。默认 dry-run 先行，--confirm 才真写。"
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="完整版产物路径（默认 ~/prompt-workspace/dist/AGENTS.full.md）")
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
    print(f"外来块搬运：「项目文档管理」节 {info['doc_gov_lines']} 行"
          f"（原样保留）；agentsync mcp 块 {info['mcp_lines']} 行（原样保留）")
    if info["doc_gov"] and info["mcp_block"]:
        print(f"隔断标题：`{SEPARATOR_HEADING}`（防 doc-governance 升级越界吞块）")
    if info["doc_gov"] is None:
        print("警告：真身中未找到「项目文档管理」节，本次不搬运该块"
              "（doc-init skill 下次运行会补注入）")
    if info["mcp_block"] is None:
        print("警告：真身中未找到 agentsync mcp 标记块，本次不搬运"
              "（agentsync 下次运行会追加到文件末尾）")
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
    print(f"    - 「项目文档管理」节 {info['doc_gov_lines']} 行逐字节保留")
    print(f"    - agentsync mcp 块 {info['mcp_lines']} 行逐字节保留")
    print("提示：本脚本不执行 insert_doc_governance.py；如需把 doc-governance 节"
          "升级到最新版本，另行运行 doc-init / doc-compact skill。")
    print("完成：真身已更新，各 runtime 软链自动生效。退出码 0。")


if __name__ == "__main__":
    main()

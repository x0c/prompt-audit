#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词体检（lint）：对目标提示词文件做纯确定性检查，零 LLM、零网络。

用法：
    lint.py [目标]        # 目标默认取部署配置 true_file；无配置时必须传参
    lint.py <目录>/       # 传目录则按文件名序拼接后体检（适合分片目录）
路径与隐私词表位置由部署配置提供（~/.config/prompt-audit/config.yaml），
不依赖任何写死的本机路径。

输出：中文体检报告（stdout）。退出码 0=健康，1=有告警。

阈值依据：
- token 阈值 3000：prompt bloat 研究（Goldber et al.，Agentic AI Foundation 引述），
  远低于上下文窗口上限时推理即开始退化。属经验阈值。
- 规则条数 50：IFScale（arXiv:2507.11538）指令密度退化研究。属经验阈值。
- 强调词密度 1 次/百字：社区轶事级反模式（叠加约束掉性能），无论文支撑，经验规则。
- 中段埋雷：Lost in the Middle（arXiv:2307.03172），关键信息居中性能下降。属经验规则。
"""

import argparse
import os
import re
import sys
import unicodedata

# ---------------------------------------------------------------------------
# 可配置项
# ---------------------------------------------------------------------------

# 隐私词表：命中即报告出现位置（私有版本属正常，仅提示；公开版命中必须处理）。
# 优先读部署配置 privacy_words 指向的文件（每行一个词，可含 # 注释）——
# 真实词表放个人目录，不随 skill 分发；缺省同内置示例表，大小写不敏感。
_PRIVACY_WORDS_FALLBACK = [
    "my-company",
    "my-username",
]


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, path_of

CFG, _CFG_PATH = load_config()

def _load_privacy_words() -> list[str]:
    """优先从部署配置 privacy_words 指向的词表文件加载，缺失时退回内置示例表。"""
    path = path_of(CFG, "privacy_words")
    if path and os.path.isfile(path):
        words = [
            line.strip()
            for line in open(path, encoding="utf-8")
            if line.strip() and not line.strip().startswith("#")
        ]
        if words:
            return words
    return _PRIVACY_WORDS_FALLBACK


PRIVACY_WORDS = _load_privacy_words()

# 强调词：用于强调通胀检测。
EMPHASIS_WORDS = ["必须", "一律", "禁止", "务必", "不得"]

# 估算 token 的告警阈值（经验值，依据 prompt bloat 研究）。
TOKEN_WARN_THRESHOLD = 3000

# 规则条数告警阈值（经验值，依据 IFScale 指令密度研究）。
RULE_COUNT_WARN_THRESHOLD = 50

# 强调词密度告警阈值：次/千字（等价 1 次/百字）。
EMPHASIS_DENSITY_WARN = 10.0  # 次/千字

# 重复检测的最小长度（字符）。
DUP_MIN_CHARS = 10

# ---------------------------------------------------------------------------
# 加载与基础度量
# ---------------------------------------------------------------------------


def load_text(target):
    """目标是文件则读单个文件；是目录则按文件名序拼接其中全部 .md。"""
    target = os.path.expanduser(target)
    if os.path.isdir(target):
        files = sorted(
            os.path.join(target, f)
            for f in os.listdir(target)
            if f.endswith(".md")
        )
        if not files:
            raise SystemExit(f"错误：目录 {target} 中没有 .md 文件")
        parts = []
        for fp in files:
            with open(fp, encoding="utf-8") as fh:
                parts.append(fh.read().rstrip())
        return "\n\n".join(parts) + "\n", files
    if not os.path.isfile(target):
        raise SystemExit(f"错误：目标不存在 {target}")
    with open(target, encoding="utf-8") as fh:
        return fh.read(), [target]


def count_cjk(text):
    """统计 CJK 字符数。"""
    return sum(1 for ch in text if "CJK" in unicodedata.name(ch, ""))


def estimate_tokens(text):
    """粗估 token 数：中文字符 × 0.7 + ASCII 单词 × 1.3（经验粗估，非精确分词）。"""
    cjk = count_cjk(text)
    ascii_words = len(re.findall(r"[A-Za-z0-9_\-./]+", text))
    return int(cjk * 0.7 + ascii_words * 1.3)


def count_rules(text):
    """规则条数：`- `/`* ` 列表项 + `1. ` 数字列表项。"""
    n = 0
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^[-*]\s+\S", stripped) or re.match(r"^\d+[.、]\s+\S", stripped):
            n += 1
    return n


def count_emphasis(text):
    """各强调词出现次数及总数。"""
    detail = {}
    total = 0
    for word in EMPHASIS_WORDS:
        n = text.count(word)
        detail[word] = n
        total += n
    return total, detail


# ---------------------------------------------------------------------------
# 重复检测
# ---------------------------------------------------------------------------


def is_table_line(stripped):
    """Markdown 表格行（含表头与分隔行）。表头/分隔行重复属排版而非规则重复，不进重复检测。"""
    return stripped.startswith("|")


def find_duplicate_lines(text):
    """行级重复：≥DUP_MIN_CHARS 的非空非表格行出现 ≥2 次。"""
    counts = {}
    for line in text.splitlines():
        s = line.strip()
        if is_table_line(s):
            continue
        if len(s) >= DUP_MIN_CHARS and not set(s) <= set("#-*|> "):
            counts[s] = counts.get(s, 0) + 1
    return {s: c for s, c in counts.items() if c >= 2}


def find_duplicate_phrases(text):
    """跨节重复短语：按标点切出 ≥DUP_MIN_CHARS 的短语，在全文出现 ≥2 次；表格行不参与。"""
    counts = {}
    for line in text.splitlines():
        if is_table_line(line.strip()):
            continue
        for p in re.split(r"[，。；：、！？\n\r\t（）()\[\]【】]", line):
            s = p.strip()
            if len(s) >= DUP_MIN_CHARS:
                counts[s] = counts.get(s, 0) + 1
    return {s: c for s, c in counts.items() if c >= 2}


# ---------------------------------------------------------------------------
# 中段埋雷检测
# ---------------------------------------------------------------------------


def find_middle_trap(text):
    """文件三等分，找「必须/禁止」密度最高的段；落在中段则告警。"""
    lines = text.splitlines()
    if len(lines) < 9:
        return None  # 文件太短，三等分无意义
    third = (len(lines) + 2) // 3
    parts = [lines[:third], lines[third : 2 * third], lines[2 * third :]]
    densities = []
    for part in parts:
        seg = "\n".join(part)
        hits = seg.count("必须") + seg.count("禁止")
        cjk = max(count_cjk(seg), 1)
        densities.append(hits / cjk * 1000)  # 次/千字
    peak = densities.index(max(densities))
    if peak == 1 and max(densities) > 0:
        return {"densities": densities, "peak": peak}
    return None


# ---------------------------------------------------------------------------
# 隐私词扫描
# ---------------------------------------------------------------------------


def scan_privacy(text):
    """扫描隐私词出现位置，返回 {词: [行号...]}。"""
    hits = {}
    lines = text.splitlines()
    lowered_lines = [(i + 1, ln.lower()) for i, ln in enumerate(lines)]
    for word in PRIVACY_WORDS:
        positions = [
            no
            for no, ln in lowered_lines
            if word.lower() in ln
        ]
        if positions:
            hits[word] = positions
    return hits


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def fmt_result(ok, warn_text):
    """单项结果标记。"""
    return warn_text if not ok else "未超"


def main():
    parser = argparse.ArgumentParser(
        description="提示词体检：确定性 lint，零 LLM、零网络。退出码 0=健康 1=有告警。"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="目标文件或目录（默认取部署配置 true_file；传分片目录可体检拼接结果）",
    )
    args = parser.parse_args()

    target = args.target or path_of(CFG, "true_file")
    if not target:
        parser.error("缺少目标文件：请传参，或在部署配置（~/.config/prompt-audit/config.yaml，"
                     "模板见 skill 目录 config.example.yaml）里设 true_file")

    text, sources = load_text(target)
    warnings = 0
    print("=" * 60)
    print("提示词体检报告")
    print("=" * 60)
    print(f"目标：{os.path.expanduser(target)}"
          + (f"（{len(sources)} 个文件按文件名序拼接）" if len(sources) > 1 else ""))

    # 1. 长度与 token
    chars = len(text)
    tokens = estimate_tokens(text)
    over_token = tokens > TOKEN_WARN_THRESHOLD
    print(f"\n[1] 长度：{chars} 字符，估算 ~{tokens} token"
          f"（阈值 {TOKEN_WARN_THRESHOLD}，依据 prompt bloat 研究，经验阈值）"
          f"{'【超阈值】' if over_token else '【未超】'}")
    if over_token:
        warnings += 1
        print("    建议：压缩冗余表述、把低频规则移出常驻上下文（按需路由），"
              "目标降到数千 token 级而非上下文窗口级。")

    # 2. 规则条数
    rules = count_rules(text)
    over_rules = rules > RULE_COUNT_WARN_THRESHOLD
    print(f"\n[2] 规则条数：{rules} 条（阈值 {RULE_COUNT_WARN_THRESHOLD}，"
          f"依据 IFScale 指令密度研究，经验阈值）"
          f"{'【超阈值】' if over_rules else '【未超】'}")
    if over_rules:
        warnings += 1
        print("    建议：合并同义规则、删除死规则、低频规则改为按需加载，降低指令密度。")

    # 3. 重复检测
    dup_lines = find_duplicate_lines(text)
    dup_phrases = find_duplicate_phrases(text)
    dup_total = len(dup_lines) + len(dup_phrases)
    print(f"\n[3] 重复检测：行级重复 {len(dup_lines)} 处，跨节重复短语 {len(dup_phrases)} 处"
          f"{'【有重复】' if dup_total else '【干净】'}")
    if dup_total:
        warnings += 1
        for s, c in sorted(dup_lines.items(), key=lambda x: -x[1])[:10]:
            print(f"    重复 {c} 次（行）：{s[:60]}{'…' if len(s) > 60 else ''}")
        for s, c in sorted(dup_phrases.items(), key=lambda x: -x[1])[:10]:
            print(f"    重复 {c} 次（短语）：{s[:60]}{'…' if len(s) > 60 else ''}")
        print("    建议：同一要求只在一处维护，其余位置删除或改为一句话引用。")

    # 4. 强调词密度
    total, detail = count_emphasis(text)
    cjk = max(count_cjk(text), 1)
    density = total / cjk * 1000
    over_density = density > EMPHASIS_DENSITY_WARN
    detail_str = "、".join(f"{w}×{n}" for w, n in detail.items() if n)
    print(f"\n[4] 强调词密度：共 {total} 次（{detail_str}），"
          f"{density:.1f} 次/千字（阈值 {EMPHASIS_DENSITY_WARN:.0f} 次/千字即 1 次/百字；"
          f"经验规则，非实证）{'【超阈值】' if over_density else '【未超】'}")
    if over_density:
        warnings += 1
        print("    建议：强调通胀会让真约束被稀释，保留硬约束的强调词，"
              "其余改陈述句。")

    # 5. 中段埋雷
    trap = find_middle_trap(text)
    if trap:
        warnings += 1
        ds = "、".join(f"{d:.1f}" for d in trap["densities"])
        print(f"\n[5] 中段埋雷：「必须/禁止」密度最高段落在中段"
              f"（三段密度：{ds} 次/千字）【告警】")
        print("    依据 Lost in the Middle（注意力 U 形曲线），属经验规则。")
        print("    建议：把高优先级硬约束移到文件头部或尾部，中段放低频/参考性内容。")
    else:
        print("\n[5] 中段埋雷：未检出（「必须/禁止」密度最高段不在中段）【通过】")

    # 6. 隐私词扫描
    privacy = scan_privacy(text)
    print(f"\n[6] 隐私词扫描：命中 {len(privacy)} 个词（仅提示位置；私有版属正常，公开版必须处理）"
          f"{'【有命中】' if privacy else '【干净】'}")
    for word, positions in privacy.items():
        shown = positions[:8]
        more = f" 等 {len(positions)} 处" if len(positions) > 8 else ""
        print(f"    {word}：第 {', '.join(map(str, shown))} 行{more}")

    # 总结
    print("\n" + "=" * 60)
    if warnings:
        print(f"总结：{warnings} 项告警（隐私词命中不计入告警数）。退出码 1。")
        sys.exit(1)
    print("总结：全部通过。退出码 0。")


if __name__ == "__main__":
    main()

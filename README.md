# prompt-audit

**English** | [中文](#中文)

A metacognition skill for AI coding agents: audit, lint, build, and safely sync your **global agent instructions** (`AGENTS.md` / `CLAUDE.md` / `instructions.md` — the file every CLI agent reads on every session).

Global instruction files grow by accretion. Rules pile up, emphasis inflates, private bookmarks leak into behavioral specs, and instruction-following quietly degrades. This skill turns "clean up my prompt" from a vibes-based rewrite into a measurable engineering discipline — it was built by applying it to its author's own 122-rule global file (−49% tokens, 122 → 57 rules, emphasis words −79%, zero semantic loss, verified by a blind controlled experiment).

## What's in the box

```
prompt-audit/            the skill (drop into your skills directory)
  SKILL.md               methodology: audit flow, rewrite discipline, safety constraints
  scripts/lint.py        6-metric health check (standalone, works on any prompt file)
  scripts/build.py       assemble shards → single AGENTS.md
  scripts/sync.py        safe write-back: mandatory dry-run, auto-backup, byte-exact verification
example/AGENTS.public.md a sanitized real-world example: the author's global spec after governance
```

## The lint metrics

| # | Metric | Why |
|---|---|---|
| 1 | Length / est. tokens (> 3000 warns) | Prompt-bloat research: reasoning degrades long before the context window fills |
| 2 | Rule count (> 50 warns) | IFScale: more instructions → lower per-instruction compliance, early rules favored |
| 3 | Duplication (line-level + cross-section) | Duplicated rules drift apart and contradict |
| 4 | Emphasis density (> 1 per 100 chars warns) | Emphasis inflation dilutes real constraints |
| 5 | Middle-positioned hard constraints | "Lost in the Middle": center of the prompt gets least attention |
| 6 | Private-word scan | Catches identity/company leaks before you publish |

`lint.py` is standalone — point it at any prompt file, exit code 0/1 makes it CI-friendly.

## The audit methodology

1. **Split to single rules** — every bullet/sentence gets its own ID
2. **Classify** into keep / merge / delete / needs-user-decision, each with a one-line reason
3. **Three-question delete test** (validated against a manual audit in a blind experiment — it caught every misjudgment the human made, with zero false deletions):
   - *Behavior*: does this rule change what the agent actually does?
   - *Trigger*: is there an identifiable situation where it fires?
   - *Distortion*: if deleted, does some observable behavior regress — and is the covering rule durably stable?
   All three "no" → deletable. Any "yes" → keep. It only rules delete-vs-keep; *resident vs. on-demand routing* is decided separately by trigger frequency.
4. **User decides the judgment calls** — the skill outputs a numbered decision list, never silently resolves ambiguity
5. **Rewrite discipline** — one behavior constraint per line; explanatory clauses stripped; the output contains zero noise (no self-explanation, no signatures, no TODOs — every character is an instruction for the model)

## The architecture it manages

```
~/.agent/src/       resident shards (always in context)
~/.agent/rules/     on-demand rules (routed by a lookup table, not resident)
manifest.yaml       shard metadata + routing table source
dist/AGENTS.full.md built artifact
~/.config/agentsync/AGENTS.md   the real file; every CLI's AGENTS.md symlinks here
```

Sharding + routing is half the win: low-frequency rules leave the resident context entirely.

Safety: `sync.py` refuses to run without `--dry-run` first, backs up before writing, carries third-party managed blocks byte-for-byte (doc-governance sections, tool-managed markers), and verifies the result hash after writing.

No paths are hardcoded anywhere: a per-machine deployment config (`~/.config/prompt-audit/config.yaml`, template included) declares your shard directories, manifest, dist output, true-file target, backup dir, privacy wordlist, and **external managed blocks** — third-party sections (doc-governance templates, tool-managed marker blocks) that sync carries byte-for-byte. Anything the config doesn't know about gets flagged before it's lost.

## The example

[`example/AGENTS.public.md`](example/AGENTS.public.md) is a real governed global spec, sanitized for publication. Note the shape: a routing table up top pointing to external `example/rules/*.md` files — on-demand rules stay out of the AGENTS.md file entirely, because the runtime loads it in full on every session; they are only read when the routing table fires. Emphasis words are spent only where they carry weight.

---

## 中文

管理 AI Agent 全局提示词（`AGENTS.md` 等，各 CLI 每次会话都读的那份文件）的元认知 skill：审计、体检、构建、安全同步。

全局指令文件靠堆积生长：规则越攒越多、强调词通胀、私人书签混进行为规范，指令遵循率悄悄退化。本 skill 把「整理提示词」从凭感觉重写变成可度量的工程——作者先在自己的 122 条规则全局文件上用了一遍（token −49%、规则 122→57、强调词 −79%、语义零丢失，经盲测对照实验验证）。

- **lint 六指标**：长度/规则条数/重复/强调密度/中段埋雷/隐私词，各有研究依据；`lint.py` 独立可用，退出码可进 CI
- **审计方法论**：拆条 → 四分类 → 三问删留判据（行为/触发/失真，对照实验验证零误删）→ 用户拍板存疑项 → 改写纪律
- **分片 + 路由架构**：常驻分片与按需规则分离，低频规则彻底移出常驻上下文
- **手术级同步**：强制 dry-run 先行、写前备份、外来托管块逐字节保留、写后哈希校验

`example/AGENTS.public.md` 是治理后的真实全局规范（脱敏公开版）：顶部路由表指向外部 `example/rules/*.md` 独立文件——按需规则完全不进 AGENTS.md 主文件（runtime 每次会话全量加载它），仅在路由命中时才读取。脚本不写死任何路径：每机一份部署配置（`~/.config/prompt-audit/config.yaml`，含模板）声明分片目录、manifest、产物目录、真身、备份、隐私词表与外来托管块定义（第三方管理的节/标记块，sync 逐字节搬运）。配置没登记的真身内容，同步前会被标记出来防止丢失。

# AGENTS.md

本仓库是 prompt-audit skill 的源码与发布仓。在本仓库工作时遵守以下约定。

## 仓库结构

- `prompt-audit/`：skill 本体（SKILL.md 方法论 + scripts/ 三脚本 + config.example.yaml 配置模板）。本地开发权威源在 `~/.config/agentsync/skills/prompt-audit/`，改动先落权威源，再同步到本仓库——不要只改本仓库副本。
- `example/`：治理后的真实全局规范脱敏示例（AGENTS.public.md + rules/ 按需规则独立文件）。示例必须忠实部署形态：按需规则绝不内联进主文件。

## 硬约束

* 脚本零硬编码路径：路径与外来块定义一律走部署配置（scripts/config.py 加载，模板 config.example.yaml），新增功能不得引入本机专属路径。
* 产物零噪音：面向 agent 的文本（SKILL.md、模板、示例）不写元话语与「不读的后果」，导航用两级强度（内容描述 + 关键场景「必读」）。
* 改脚本后必跑验证：`build.py` 产物须与改前逐字节一致（行为不变时）、`sync.py --dry-run` 预览、`lint.py` 退出码。不做运行时验证不得报「完成」。
* 公开产物发布前必跑隐私词扫描（`lint.py` 目标文件），必须零命中；个人隐私词表永不进本仓库。
* commit 身份双字段均为 x0c（`GIT_COMMITTER_NAME`/`GIT_COMMITTER_EMAIL` + `--author`，x0c@users.noreply.github.com），不得出现真实姓名邮箱。
* 代码注释、日志输出、错误信息一律中文。

## 文档导航

- `README.md`：仓库门面（中英双语），对外介绍工具与指标——发布前更新 release notes 时同步检查其准确性。
- `prompt-audit/SKILL.md`：方法论唯一权威源（审计流程、删留判据、改写纪律、安全约束）。改方法论只改这里，别处引用不复制。
- `prompt-audit/config.example.yaml`：部署配置模板。脚本行为与配置键变更时同步更新其注释。

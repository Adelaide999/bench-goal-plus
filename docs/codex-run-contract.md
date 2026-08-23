# Codex run contract

所有 benchmark 共用同一个执行层，差异只留在 task materializer 和 verifier adapter。

## 控制流

```text
branch-tracked benchmark source + pinned task/data revision
  -> isolated git workspace
  -> benchmark-specific prompt and public tools
  -> codex exec --json --sandbox workspace-write
  -> candidate artifact + Codex event stream/usage
  -> controller-owned official evaluator
  -> canonical evaluator payload + native metric
  -> archive manifest / candidate / lineage edge
```

Goal Plus 位于 controller 层：选择父候选、创建独立 workspace、启动/续接 Codex、调用 evaluator、晋升 best-seen。它不替换 benchmark verifier，也不把自己的状态复制进候选 artifact。

## Codex 调用约束

本机 Codex CLI 已确认支持以下非交互能力：

- `codex exec --json` 输出 JSONL 事件，`turn.completed` 含 token usage。
- `--sandbox workspace-write` 允许在任务 workspace 内修改文件。
- `--cd` 固定工作根目录；默认要求它是 Git 仓库。
- `--output-last-message` 单独保存最终消息。
- `codex exec resume <thread-id>` 可续接既有 session。
- Plain Codex 使用 `--ignore-user-config`，避免个人 `config.toml` 影响可复现实验；项目 `AGENTS.md` 仍用于任务约束。
- Goal Plus + Codex 使用 run 内独立的 `CODEX_HOME`，不继承个人配置；prepare 从最新 Muyuan 的 `.codex/config.example.toml` 和 `.codex/hooks.example.json` 物化项目 `.codex/config.toml` 与 `.codex/hooks.json`（并兼容旧版 `hooks.json`）。`--ignore-user-config` 会连项目 Hook 一起跳过，因此该模式不得使用。

中央 runner 的初始命令形态：

```bash
codex exec \
  --json \
  --sandbox workspace-write \
  --cd <workspace> \
  --ignore-user-config \
  --output-last-message <run-dir>/final-message.txt \
  -
```

prompt 通过 stdin 传入。不得使用 `danger-full-access`，除非 Codex 本身位于已隔离的 benchmark container/VM，且该例外写入 manifest。

参考：Codex 官方手册的 [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) 与本机 `codex exec --help`。

## 证据文件

每次调用至少生成：

```text
run-dir/
  events.jsonl
  stderr.log
  final-message.txt
  run-manifest.json
```

`run-manifest.json` 至少包含：

- start/end/duration、exit code、Codex version、thread id
- sandbox、model（若显式设置）、prompt SHA-256
- input/output/cached/reasoning token usage
- workspace 路径和当前 task commit（由 adapter 扩展）

不得写入 API key、auth token 或环境变量值。

## 公平性边界

- plain Codex 和 Goal Plus + Codex 必须使用同一 Codex model/provider 身份。
- 系统级主预算是相同 wall deadline `T` 和 live concurrency `K`，不是 Codex turns、Goal Plus rounds 或 OpenEvolve iterations；evaluator calls 全量记录。显式 hard call cap 只属于另行标注的机制消融。
- Codex host 与 Pi/直接 LLM API 的结果不能混合归因；跨 host 只能做 portability slice。
- private/held-out evaluator 不暴露给 Codex；正式提交后才运行。
- upstream 自带的 API agent smoke 只证明环境和 evaluator，不是 Codex baseline。

# EdgeBench runner

EdgeBench 保留 native SForge lifecycle。控制面负责选择 profile/preset、部署依赖、启动和
监控 campaign；SForge 继续拥有 Work container、hidden Judge、任务隔离和最终归档。

## 执行前

1. 阅读
   [Host 与鉴权矩阵](../../../benchmark-setup/references/host-auth.md)。
2. 用 `catalog` 确认 `edgebench-native` 的 method 和 capability。
3. 用 preset 或 profile 冻结 task、method、model、reasoning 和 `T/K/C/R`。
4. 运行 `plan`，检查 native `provision → doctor → prepare → run --detach` 命令链。
5. 检查 doctor 中 `network:api-only-policy` 和 `network:offline-task-isolation` 均通过，
   endpoint 清单覆盖 main、Goal Plus worker 和 evidence annotation；检查 prepare 产物只有
   `--disable-internet`。任一缺失时不得 launch，也不得用开放公网 smoke 替代。

## 已登记方法

| Method | SForge agent | `K` 的含义 |
| --- | --- | --- |
| `plain-codex` | `codex` | 固定 `K=1`，一条 outer trajectory |
| `goal-plus-codex` | `codex-goal-plus` | 一个 outer run 内 `K` 个 Goal Plus workers |
| `plain-claude` | `claude-code` | 固定 `K=1`，一条 outer trajectory |
| `plain-pi` | `pi` | 固定 `K=1`，一条 outer trajectory |
| `plain-pi-provider` | `pi-provider` | 固定 `K=1`，一条使用显式 `PROVIDER/MODEL` 的 outer trajectory |
| `goal-plus-pi` | `pi-goal-plus` | 一个 outer run 内 `K` 个 Goal Plus workers |
| `goal-plus-pi-provider` | `pi-goal-plus-provider` | 与上一行拓扑相同，但 outer/worker 都使用显式 `PROVIDER/MODEL` API 路径 |

不要使用未登记的别名。method 必须在 plan 阶段通过 runner
`supported_methods` 校验。`goal-plus-pi` 专指 `openai-codex` OAuth；Z.AI 或
自定义 Anthropic/OpenAI-compatible endpoint 使用 `goal-plus-pi-provider`，且 model
必须写成精确的 `PROVIDER/MODEL`。
provider 的 wire API 由 Pi registry 决定：`anthropic-messages` 和
`openai-completions`/`openai-responses` 使用同一个 method。macOS 与 Linux
也使用同一 adapter；host 只提供 registry/credential，实际 agent 始终运行在
EdgeBench Linux Work container 中。

一个 Goal Plus cell 可为 main、worker、annotation 选择不同 provider。controller 必须把
所有角色 base URL 传给 SForge；SForge 只将这些 URL 与 Judge 解析成精确 `IP:port`
allowlist。缺失 built-in endpoint、custom `baseUrl`、loopback bridge 或 iptables 权限时失败
关闭；不得因为 provider 多样而设置 `internet=true`。

`goal-plus-pi-provider` 在开始计时前必须完成 provider runtime gate：使用 Work
container 的实际运行用户和实际 `PI_CODING_AGENT_DIR` 执行
`pi --list-models <provider>`，并核对精确 `PROVIDER/MODEL`。随后用短 JSON session
取得 `thinking_start`/`thinking_delta` 或非零 reasoning usage，才可把 provider wiring
记为通过。只在 host 上读取 registry、只通过 controller doctor，或只看到普通 assistant
文本都不够。

不要把 `openai-completions` 与 `openai-responses` 合并成一个模糊的“OpenAI 接口”：前者
必须验证 `/chat/completions`，后者必须验证 `/responses`。`/responses` 返回 404 时，
即使 Chat Completions 正常，也必须明确记录 Responses 不受支持并选择
`openai-completions`。

协议选择采用 Responses-first：`/responses` 最小请求成功后，还必须用 campaign 将采用的
Pi 版本完成 streaming、tool call、tool result 和 final answer；通过后才选择
`openai-responses`。只有这条链路失败时才验证并回退 `openai-completions`。DeepSeek
V4 Flash 的 built-in `deepseek` provider 当前仍走 Chat；Responses 路径使用
`deepseek-responses/deepseek-v4-flash` 自定义 registry。GLM-5.2 的 Z.AI 路径当前走
`zai/glm-5.2` Chat Completions。DeepSeek 官方当前只声明 V4 Flash 支持 Responses；
V4 Pro 不得复用该配置，除非后续官方能力和当次 live probe 都确认支持。

EdgeBench Work container 不再精确锁死旧 Pi：默认
`SFORGE_PI_PACKAGE_VERSION=latest`，安装输出必须记录解析后的 `pi --version`。短 capability
smoke 可以跟随 latest；一小时等正式 campaign 必须在 profile 的
`pi_package_version` 字段冻结刚通过 smoke 的精确版本，避免同一 campaign 中 npm tag
漂移。

一小时 VLIW Z.AI built-in provider preset：

```bash
python3 scripts/bench.py plan \
  --preset edgebench-vliw-goal-plus-pi-zai-glm-5-2-1h
```

它固定 `T=3600,K=2,C=1,R=1`，使用 Pi built-in `zai/glm-5.2`，只要求
`ZAI_API_KEY`。`edgebench-vliw-goal-plus-pi-glm-provider-1h` 保留为自定义
`models.json` endpoint 路径；实际 launch 前仍需按 K/C 门禁展示并确认解析结果。

profile 中的 `protocol_source=edgebench-official-codex` 只表示资源、网络、评测周期等
协议默认值来自 EdgeBench 官方 `experiment-codex.yaml`。实际 agent/provider 仍由
method 和 model 决定；该字段不把 Pi campaign 变成 Codex campaign。

## Judge 资产完整性

profiled `check` 会把精确 task revision、Work/Judge tag、image ID 与
`experiments/edgebench/references/known-asset-issues.json` 核对。命中 blocking issue 时，即使
镜像存在也必须失败关闭，不得 launch、不得把失败的 harness pass rate 当作 0–100 分，也
不得把修补后的镜像重新标成原 tag。

`order_addition_permutation_optimization` 的 Judge tag `f6f385925889` 已确认存在发布时的
score-helper SHA 自检不一致。恢复正式测评需要上游发布新的 Judge tag，并由新的 task dataset
revision 引用它；只修改本地 test 常量最多是诊断验证，不构成 official evaluator 修复。当前两个
已知坏 dataset revision 已将该题标为 `excluded_from_campaigns`，profile 加载阶段即拒绝调度。

## 可运行公开集 Codex campaign

```bash
python3 scripts/bench.py plan --preset edgebench-codex-2h
python3 scripts/bench.py launch --preset edgebench-codex-2h
```

该 preset 固定 50 个当前可运行的公开任务（官方集合仍为 51 题）、Plain Codex、`gpt-5.6-sol`、`medium`、
`T=7200,K=1,C=2,R=1`。`C=2` 表示两个 task cells 并发，不是两个 candidate。

## Controller 日志边界

对所有 detached EdgeBench cell，在 `run` 子命令前传入 SForge 全局参数
`--silent`。把 cell 的 `controller.log` 只作为 SForge 子进程的启动、结束和错误控制台日志；
完整 agent trajectory 以 SForge 的 `agent_output.txt` 为准。

单 task、单 outer replica 在没有 `--silent` 时会触发 SForge verbose 模式，把容器内 agent
stdout 原样复制到 `controller.log`。Pi JSON delta 尤其会绕过 `agent_output.txt` 的兼容过滤，
重新产生数百 MiB 的重复快照。不得用压缩、轮转或另一层 JSON 过滤掩盖这条重复落盘路径；
检查生成的 `command.json`，确认 `--silent` 位于 `run` 之前。

## 监控和停止

```bash
python3 scripts/bench.py status --campaign runs/edgebench/<campaign-id>
python3 scripts/bench.py stop --campaign runs/edgebench/<campaign-id>
```

status 必须保留 native campaign/cell/PID/trajectory 状态。Goal Plus cell 还应展示
candidate、worker session/handle、verifier ledger、剩余时间和最新 Judge submission。
stop 是保留 partial evidence 的 controller closeout；partial trajectory 不能被删除，
也不能被伪装成原 trajectory 的无损 resume。

仅做 provider/thinking smoke 时，观察到所需思考证据后立即 stop，并在同一轮执行
`finish` 归档 partial evidence。报告必须标注这是 wiring smoke，不得作为 EdgeBench
score 或完整 T 预算结果。

## Goal Plus completion evidence

Goal Plus + Codex 的 session allocation 本身不是 worker launch：

- 至少记录 `K` 个不同的 spawned worker thread，或 `K` 个不同的 Codex host handle；
- 至少 `K` 个 candidate-bound verifier records；
- 必须有 promotion 和 official Judge trajectory。

Goal Plus + Pi 不使用 Codex collaboration events，必须持久化至少 `K` 个 candidate-bound
Pi sessions 和 verifier records，并同样保留 promotion 与 official trajectory。
缺失任何 required evidence 时 cell/campaign 为 `partial`。

## Finalize

```bash
python3 scripts/bench.py finish --campaign runs/edgebench/<campaign-id>
```

native finalizer 生成 `comparison.json` 和 native workbook；统一 report exporter 再生成
`report.md` 与 `<campaign-id>.xlsx`。不要直接修改 native artifacts 来改变结论。

只有调试 EdgeBench controller 本身时才直接运行
`experiments/edgebench/experiment.py --help`；正常用户流程始终使用 `scripts/bench.py`。

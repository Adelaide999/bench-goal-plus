# EdgeBench 官方协议对齐 TODO

## 2026-07-27 实现状态

控制面映射已完成，适用于新建 campaign：

- `prepare` 安全读取官方 Codex YAML，验证 51-task coverage，只保留 allowlisted
  protocol 字段并记录 source SHA256；
- 每题继承官方 defaults/override 与 task JSON 自有的 `internet`，不再使用全局
  `internet=true`；
- CPU/memory、cooldown（包括 `0`）、lifecycle 和 network flag 已映射到 SForge
  命令；
- cell manifest 记录 official/effective protocol、逐字段 diff、reason 和
  `official_edgebench_comparable`；
- `doctor` 用 disposable Work container 验证 Docker CPU/memory HostConfig，并调用
  SForge `check_iptables_permission()` 验证离线任务的网络隔离前提；
- model-free 51-task dry-run 已验证 50 个 `--disable-internet`、1 个
  `--enable-internet`，以及 D-ABIC/Schemathesis/game/graph/Lean/SMT override。

当前主机尚不能执行协议对齐 run：rootless Docker 报告
`CpuCfsQuota=false`，且 `sudo -n iptables` 需要密码。剩余工作是修复主机能力后执行
本文末尾的真实 lifecycle smoke；旧 campaign 不回写、不重标。

## 背景

当前开发 campaign
`edgebench-51-codex-gpt-5-6-sol-medium-2h-k1-c2-20260724-1811` 证明了 51-task
准备、两 cell 并发、Codex API bridge、共享 Judge、timeout closeout 和最终归档可以
连续工作。但它使用了本仓自定义 `full-codex-2h.json`，没有完整继承 EdgeBench
官方 `examples/all-tasks-k8s/experiment-codex.yaml`。

开发实验真正希望修改的只有：

- model/reasoning：`gpt-5.6-sol/medium`；
- 每题预算：从 12 小时缩短为 2 小时；
- 跨题调度：同一 campaign 最多同时运行 2 个不同 task；
- 开发阶段每题只运行 1 条 trajectory，而不是官方统计所需的 3 条独立 trajectory；
- 本机开发可使用 Docker backend，但必须保留与官方相同的任务资源和网络语义。

CPU、memory、submission cooldown、task internet policy 和 task-specific overrides
不属于预期修改。任何无法在目标主机实现的官方字段都必须让 preflight 失败，或作为
显式 allowlisted deviation 写入 manifest；不能静默丢弃。

当前 campaign 保留为 exploratory development evidence，不回写、不重启、不转换为
官方结果。已有审计见
[`evidence/runs/2026-07-25-edgebench-gpt-5-6-sol-development-audit.md`](../evidence/runs/2026-07-25-edgebench-gpt-5-6-sol-development-audit.md)。

## 权威配置源

实现时从 managed EdgeBench checkout 结构化读取：

```text
third_party/edgebench/examples/all-tasks-k8s/experiment-codex.yaml
third_party/edgebench/tasks/<task_id>.json
```

不要在 `bench-goal-plus` 里手工复制一套官方 defaults/task overrides。campaign
manifest 已记录 resolved EdgeBench commit，因此配置来源和内容可追溯。

只允许从官方 YAML 读取经过白名单确认的非敏感字段。不得读取、展开、复制或持久化
`model.api_key`、`env` 中的 credential，或任何用户认证文件。YAML 必须使用安全解析
API；若引入新的解析依赖，需要加入可复现 lock。

## 目标合并顺序

每个 cell 的 effective config 按以下顺序构造：

1. 官方 experiment `defaults`；
2. 官方 experiment `tasks.<task_id>` override；
3. task JSON 自身的 `internet`、image、prompt、judge 和 metric contract；
4. 开发 profile 的显式 allowlisted overrides；
5. controller-only 字段，例如 `cell_concurrency`、Judge bridge URL 和 run ID。

profile 不得用一个全局 `internet=true` 覆盖 task JSON。若 profile 确实需要改官方字段，
必须使用显式 `protocol_overrides`，写清 reason，并自动令
`official_edgebench_comparable=false`。

## 必须继承的官方字段

### Defaults

- `agent=codex`；
- `eval_interval=1800`；
- `submission_cooldown=120`；
- `work_cpu_limit=4`；
- `work_mem_limit=16g`；
- `judge_cpu_limit=4`；
- `judge_mem_limit=8g`；
- stop hook、auto-eval 和 auto-resume 保持启用；
- `max_submissions` 未设置时保持未设置。

### Task overrides

至少验证以下代表项，实际实现必须覆盖官方 YAML 中的全部 override：

- `dabic_gravity_inversion`: `submission_cooldown=2160`；
- `graph_node_classification`: `judge_mem_limit=16g`；
- 三个 Schemathesis task: `submission_cooldown=216`；
- Lean/Coq tasks: Work/Judge 8 CPU、16 GiB；
- `smt_solver`: Work/Judge 16 CPU、16 GiB；
- game task 中官方设为 0 的 cooldown 必须保留为 0，不能被 truthiness 判断丢掉。

### Per-task internet

当前 public task definitions 中：

- 50 个 task 为 `internet=false`；
- 仅 `college_english_exam_bank` 为 `internet=true`。

`internet=false` 时，Work container 仍需通过 SForge 的受控网络路径访问 agent API
和 Judge，但必须阻断普通外网。不能为了访问 `127.0.0.1:3788` bridge 而把整个
container 改成 `--enable-internet`。

## 控制面代码改动

### 1. 官方协议加载器

在 `experiments/edgebench/experiment.py` 增加安全、可测试的官方 Codex protocol
loader：

- 验证 YAML schema 和 task set；
- 只返回 allowlisted non-secret fields；
- 记录 source path、EdgeBench commit 和文件 SHA256；
- 对未知字段、缺少 defaults、缺少 task 或类型错误 fail closed；
- 不修改 managed EdgeBench checkout。

profile 建议只保存：

```json
{
  "protocol_source": "edgebench-official-codex",
  "model": "gpt-5.6-sol",
  "reasoning_effort": "medium",
  "wall_time_seconds": 7200,
  "concurrency": 1,
  "cell_concurrency": 2,
  "attempts_per_task": 1
}
```

不要保留当前全局 `internet=true`。

### 2. Cell manifest 字段

为每个 cell 持久化以下 effective values：

- `work_cpu_limit` / `work_mem_limit`；
- `judge_cpu_limit` / `judge_mem_limit`；
- `submission_cooldown`；
- `max_submissions`；
- `internet` 及其来源；
- stop hook、auto-eval、auto-resume；
- `official_defaults`、`official_task_overrides`、`intentional_overrides`；
- `protocol_diff` 和 `official_edgebench_comparable`。

数值 0 是有效配置。合并和命令生成不得使用会把 0 当成缺失的 truthiness 判断。

### 3. SForge command 映射

扩展 `build_sforge_command()`，按 effective config 传递现有 SForge CLI 参数：

```text
--work-cpu-limit
--work-mem-limit
--judge-cpu-limit
--judge-mem-limit
--submission-cooldown
--max-submissions
--enable-internet / --disable-internet
```

同时审计 `judge_concurrency=1`。官方 YAML 没有该限制；若开发 controller 仍需要它，
必须成为显式 deviation 并解释对异步 Judge feedback 的影响，不能作为隐藏默认值。

### 4. Protocol diff gate

`prepare` 和 `doctor` 都应生成机器可读的 protocol diff。开发 profile 的允许差异
应精确限制为：

```text
model
reasoning_effort
wall_time_seconds
cell_concurrency
attempts_per_task
backend (仅本机开发模式)
```

其余差异默认报错。不要只比较 profile 顶层字段；必须比较全部 51 个 effective cell
configs。diff 输出不得包含 key、token、provider header 或 auth path 内容。

### 5. Resource capability preflight

官方资源限制不能通过“删除参数”绕开：

- 用一次 disposable Docker probe 实际验证 CPU quota 和 memory limit；
- 检查 Docker backend 是否接受 `--cpus 4` 和 `--memory 16g` 的等价设置；
- rootless daemon 缺少 cpu/cpuset delegation 时，official mode 必须失败并给出明确
  修复提示；
- 目标环境可选择修复 systemd cgroup delegation、使用 rootful Docker，或使用官方
  K8s backend；
- 只有显式 non-comparable development mode 才能取消限制，且 manifest 必须记录。

### 6. Network preflight

至少用一个 `internet=false` task image 验证：

- agent API bridge 可达；
- Judge bridge 可达；
- public Internet URL 不可达；
- DNS/代理环境变量不能绕开限制。

再用 `college_english_exam_bank` 验证其 `internet=true` 路径与 LLM Judge 配置。

## Reporter 修复

`third_party/edgebench/scripts/report_edgebench_scores.py` 当前对没有
`judge.rescale` 的任务抛错。Borden 和 D-ABIC 的 native Judge score 已是 0--100。

在 EdgeBench fork 中修复：

- 明确定义 no-rescale score task 的 identity 0--100 语义；
- 只对确定属于 native bounded score 的任务使用 identity，不能把未知 raw metric
  一概当成 0--100；
- Borden/D-ABIC 的 final result 和 run history 均可生成 valid observation；
- campaign finalization 不得把它们静默降为 error；
- 保留 raw score，不用 normalized score 覆盖 raw metric。

这是 benchmark-specific reporting change，应提交到 EdgeBench fork；本仓只消费并
记录 resolved fork commit。

## 测试要求

### Unit tests

- official YAML defaults 和全部 per-task overrides 正确解析；
- profile 只覆盖 allowlisted development fields；
- 50/51 task 生成 `--disable-internet`，college-English 生成
  `--enable-internet`；
- D-ABIC/Schemathesis/game cooldown 分别为 2160/216/0；
- graph/Lean/SMT 的 CPU 和 memory overrides 正确；
- SForge command 含 CPU、memory、cooldown 和 internet flags；
- 0 值不丢失；
- unexpected protocol diff 令 prepare/doctor 失败；
- manifest 和 command record 不含 credential；
- Borden/D-ABIC reporter 产生 identity-normalized valid result；
- 两 cell scheduler 的并发、失败隔离和 stop 行为继续通过。

### Real lifecycle smoke

使用新的 campaign ID，至少包含：

1. 两个不同 `internet=false` task 同时运行；
2. `docker inspect` 或 backend evidence 证明 CPU/memory limit 生效；
3. API/Judge 可达、普通外网不可达；
4. cooldown 被 Judge server 实际执行；
5. 两个 cell 都产生 valid `final_result.json` 和 archive；
6. Judge、bridges 和 Work containers 在 closeout 后全部退出；
7. credential persistence scan 为零。

不要复用当前 development campaign 或其 run IDs。

## 文档与证据

更新：

- `experiments/edgebench/README.md`；
- `docs/benchmarks/edgebench.md`；
- 新的 profile 示例；
- doctor/protocol-diff evidence；
- real two-cell official-semantics smoke evidence。

必须明确区分：

- `functional_development_run`；
- `official_protocol_with_intentional_time/model_override`；
- `official_leaderboard_comparable`。

2 小时单次开发 run 即使资源和网络完全对齐，也不是论文的 3-run、12-hour
leaderboard cell，只能与官方 `@2h` 做带标签的参考比较。

## 验收命令

提交前至少运行：

```bash
python3 scripts/status.py --check
python3 -m unittest discover -s tests -v
.bench-env/venv/bin/python -m pytest third_party/edgebench/tests -q
git diff --check
```

若修改 EdgeBench fork，先在 fork 中提交并 push tracking branch，再更新本仓所需的
文档/测试；不要在 `bench-goal-plus` vendor fork source。

## Definition of Done

- 51 个 cell 的 effective protocol diff 只包含明确允许的开发差异；
- CPU、memory、cooldown、internet 和全部 task overrides 与官方 source 一致；
- unsupported resource semantics 在启动模型前 fail closed；
- reporter 能完整汇总 51 题而不丢 raw metric；
- real two-cell smoke 有命令、manifest、result、archive 和 cleanup evidence；
- 没有 credential 落盘；
- 当前 development campaign 保持原样并永久标为 non-comparable。

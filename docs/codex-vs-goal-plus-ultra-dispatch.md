# Codex Direct Ultra 与 Goal Plus Ultra 同题下发对照

日期：2026-08-19 至 2026-08-20

## 结论

本项目把 **Codex Direct Ultra** 定义为：`gpt-5.6-sol`、Main
`reasoning_effort=max`，且 Main 主动调用 Codex 协作工具编排 subagent。现有运行符合这个
定义，因此计入正式协议对照。

本次用同一个 `parse_size` 开发题真实运行了三条路径：

1. **Codex Direct Ultra**：Main 直接调用 `spawn_agent`，再接收并集成 subagent 结果。
2. **Goal Plus Ultra + Codex**：`/goal-plus` Main 先建立持久工作项 DAG，再把其中一个
   工作项映射到 Codex 原生 `spawn_agent`。
3. **Goal Plus Ultra + Pi**：同一 Goal Plus DAG/attempt 协议把普通工作项映射为
   `pi_goal_plus_run_work_item`，由隔离的 Pi RPC worker 执行并返回 Main 验收。

三条路径都从同一初始提交 `cc0b4407a43ab59f6fb36cb7141e235a90ea9747` 开始，使用
`gpt-5.6-sol` 和一个题内 subagent。逻辑 Main reasoning 均为 `max`；Pi adapter 请求原生
`xhigh`，但 provider 对 Main 和 worker 的实际记录均为 `high`。这是正式的下发协议对照；
由于没有重复运行和统一外层计时器，它仍不是用来断言质量、速度或成本优劣的统计 benchmark。

## 同一个题

三条路径都实现 `parse_size`：

```text
- 支持 B、KB、MB，大小写不敏感；
- 支持一个或多个由空白分隔的正整数/单位 token；
- 使用十进制倍率 1、1000、1000000 求和；
- 允许首尾空白；
- 空输入、零、负数、小数、未知单位和未匹配文本抛 ValueError；
- 返回精确 int。
```

Main 负责 `size_parser.py` 和最终集成；一个普通 subagent 只负责独立边界审查并修改
`test_size_parser.py`。这是确定性实现题，没有优化 metric，三条路径都不进入 Search。

原始输入：

- [Codex Direct Ultra 输入](../runs/ultra-direct-codex-live-20260819/direct_prompt.md)
- [Goal Plus Ultra + Codex 输入](../runs/ultra-attempt-smoke-codex-live-20260819/smoke_prompt.md)
- [Goal Plus Ultra + Pi 输入](../runs/ultra-attempt-smoke-pi-live-20260820/pi_prompt.md)

## 下发内容

### Codex Direct Ultra

Main 的实际运行配置是：

```json
{
  "model": "gpt-5.6-sol",
  "reasoning_effort": "max",
  "orchestration": "main_calls_native_collaboration_tools",
  "subagents": 1
}
```

Main 实际调用：

```json
{
  "tool": "spawn_agent",
  "task_name": "size_parser_edge_review",
  "fork_turns": "none"
}
```

`message` 在原始 transcript 中经过加密，不能逐字还原；可核对的任务语义是：独立审查 parser
合同边界，只编辑 `test_size_parser.py`，增加高信号测试并运行 focused tests。随后 Main 实际调用
了一次 `wait_agent(timeout_ms=60000)`；这次 wait 结束时 worker 仍在运行，最终结果稍后由宿主送达。

实际链路：

```text
Codex Main(model=gpt-5.6-sol, effort=max)
  -> spawn_agent(size_parser_edge_review, fork_turns=none)
  -> child handle /root/size_parser_edge_review
  -> Main 实现 size_parser.py
  -> wait_agent(60s)，worker 尚未终止
  -> subagent 只修改 test_size_parser.py，返回 18 passed
  -> Main 审查 diff，运行完整 pytest
  -> 最终回复
```

Direct 路径没有 Goal ID、工作项 DAG、attempt、generation、launch TTL 或持久验收状态。

### Goal Plus Ultra + Codex

Goal Plus Main 先持久化工作包：

```json
{
  "work_item_id": "edge_case_tests",
  "title": "Review edge cases and add tests",
  "objective": "Independently review parser edge cases and add focused tests that exercise uncovered contract boundaries without editing production code.",
  "route": "subagent",
  "scope": ["test_size_parser.py"],
  "acceptance": [
    "Only test_size_parser.py is edited.",
    "Tests cover meaningful valid and invalid boundary cases not already covered.",
    "Focused parser tests pass against the completed Main implementation."
  ]
}
```

随后记录 fenced attempt 并执行 Codex 原生调用：

```text
dispatch:
  work_item_id = edge_case_tests
  attempt_id   = attempt_f7f3ebd4f3a247dc9ca066af60177fc1
  generation   = 1

spawn_agent:
  agent_type   = worker
  task_name    = edge_case_review
  fork_turns   = none

bind:
  agent_id     = /root/edge_case_review
```

实际链路：

```text
/goal-plus hook 创建 gp_0001
  -> triage: Goal Mode，不进入 Search
  -> 持久化 main_parse_size、edge_case_tests、final_verification DAG
  -> dispatch(attempt, generation=1)
  -> spawn_agent(edge_case_review)
  -> bind(agent_id=/root/edge_case_review)
  -> subagent 返回测试 diff
  -> Main record result -> accepted
  -> Main 完成实现与最终验证
  -> set_status(complete, pytest evidence)
  -> stop gate allow
  -> 最终回复
```

本次 Goal Plus transcript 没有真实 `wait_agent` 调用；subagent 结果由宿主自动送达。事件中的
`result.metadata.native_operation=wait_agent` 是记录标签，不是原生调用证据。

### Goal Plus Ultra + Pi

Pi Main 建立了与 Codex host 同构的三个工作项：`main-implement`、`edge-tests` 和
`main-verify`。其中实际下发给 worker 的工作包是：

```json
{
  "work_item_id": "edge-tests",
  "title": "Independent edge-case review and focused tests",
  "objective": "Independently review the parse_size contract and add focused edge-case tests. Modify only test_size_parser.py and run pytest using /data/l00939996/bench-goal-plus/.bench-env/venv/bin/python.",
  "route": "subagent",
  "scope": ["test_size_parser.py"],
  "acceptance": [
    "Only test_size_parser.py is modified.",
    "Focused tests cover meaningful valid and invalid edge cases from the contract.",
    "The subagent reports the exact pytest command and result."
  ]
}
```

Main 的实际宿主调用不是 `spawn_agent`，而是：

```json
{
  "tool": "pi_goal_plus_run_work_item",
  "goal_plus_id": "gp_0001",
  "work_item_id": "edge-tests",
  "max_runtime_seconds": 300
}
```

该工具先生成 fenced attempt，再启动 `goal-plus-pi-worker run --launch-json ...`；wrapper
内部启动隔离的 `pi --mode rpc` 子进程。Goal Plus 根据工作包生成并真正发送给 worker 的
用户任务内容是：

```text
You are an implementation subagent. Work only on the assigned item.

Title: Independent edge-case review and focused tests

Objective: Independently review the parse_size contract and add focused
edge-case tests. Modify only test_size_parser.py and run pytest using
/data/l00939996/bench-goal-plus/.bench-env/venv/bin/python.

Scope: test_size_parser.py

Acceptance:
- Only test_size_parser.py is modified.
- Focused tests cover meaningful valid and invalid edge cases from the contract.
- The subagent reports the exact pytest command and result.

Do not coordinate other agents or use Goal Plus/Search tools. Return a concise
result and verification evidence.
```

实际 attempt 与绑定信息：

```text
dispatch:
  work_item_id = edge-tests
  attempt_id   = attempt_53d859195d2047dabc495b3b187225bf
  generation   = 1

bind:
  agent_id     = gp_0001_edge-tests_1787211852002
  host         = pi
```

worker 只修改了 `test_size_parser.py`，在 Main 尚未实现生产代码时运行测试并如实返回
`17 failed in 0.10s`，失败均来自原始 `NotImplementedError` stub。Main 随后检查 diff，
把 `edge-tests` 从 `result_ready` 验收为 `accepted`，实现 `size_parser.py`，再完成最终验证。

实际链路：

```text
/goal-plus 创建 gp_0001
  -> triage: Goal Mode，Search=false
  -> 持久化三个 work items
  -> pi_goal_plus_run_work_item(edge-tests, 300s)
  -> dispatch(attempt, generation=1)
  -> goal-plus-pi-worker 启动隔离 Pi RPC child
  -> bind(agent_id=gp_0001_edge-tests_1787211852002)
  -> worker 修改测试并返回 result
  -> Main 审查 diff -> accepted
  -> Main 实现生产代码并验收 main-implement
  -> Main 运行完整 pytest 并验收 main-verify
  -> set_status(complete, test_count=17)
  -> stop gate allow
  -> 最终回复
```

本次只有 `generation=1`，`stale_result` 事件数为 0。Pi 请求 Main/worker `xhigh`，provider
实际记录为 `high`；因此可称逻辑 Ultra `max`，但不能声称 Pi 原生执行到了 `xhigh`。

## 最终返回

### Codex Direct Ultra

```text
Implemented parse_size with strict full-input validation, case-insensitive units,
decimal multipliers, multi-token summation, and exact integer arithmetic.

- Changed: size_parser.py
- Changed: test_size_parser.py
- Subagent: /root/size_parser_edge_review
- Complete suite: 18 passed in 0.01s
```

### Goal Plus Ultra + Codex

```text
Goal Plus gp_0001 is complete.

Implemented parse_size in size_parser.py and added delegated edge-case coverage in
test_size_parser.py. The subagent followed dispatch -> bind -> result -> accepted.

Full suite: 19 passed in 0.01s.
```

### Goal Plus Ultra + Pi

```text
Goal Plus gp_0001 已完成。

Main 在 size_parser.py 实现了严格的 parse_size。普通子代理仅在
test_size_parser.py 补充边界测试，变更已由 Main 检查并验收。

完整验证：17 passed in 0.03s。所有必需工作项已接受，未使用 Search，
Goal Plus 状态为 complete。
```

## 对比表

| 项目 | Codex Direct Ultra | Goal Plus Ultra + Codex | Goal Plus Ultra + Pi |
| --- | --- | --- | --- |
| 模型 | `gpt-5.6-sol` | `gpt-5.6-sol` | `bench-openai/gpt-5.6-sol` |
| Main 逻辑 reasoning | `max` | `max` | `max` |
| 宿主原生 reasoning | `max` | `max` | 请求 `xhigh`，观测 `high` |
| 题内 subagent | 1 个 Codex worker | 1 个 Codex worker | 1 个 Pi RPC worker |
| 实际 worker handle | `/root/size_parser_edge_review` | `/root/edge_case_review` | `gp_0001_edge-tests_1787211852002` |
| Main 实际下发调用 | `spawn_agent` | `spawn_agent` | `pi_goal_plus_run_work_item` |
| 下发协议 | 直接宿主调用 | DAG `dispatch -> spawn -> bind` | DAG `dispatch -> RPC spawn -> bind` |
| Search | 未使用 | triage 后明确未使用 | triage 后明确未使用 |
| 完整测试 | `18 passed` | `19 passed` | `17 passed` |
| Unicode `1KB` | `KeyError`，违反合同 | `ValueError` | `KeyError`，违反合同 |
| Goal 状态 | 无 | `gp_0001`, `complete` | `gp_0001`, `complete` |
| 持久 DAG | 无 | 3/3 work items `accepted` | 3/3 work items `accepted` |
| attempt fencing | 无 | attempt + generation + launch TTL | attempt + generation + launch TTL |
| stale result | 无 | 本次未触发 | 0 条 |
| Main 墙钟 | 148.685 秒 | 545.907 秒 | 484 秒 |
| Main token | input 236,442；output 5,462 | input 1,183,755；output 17,320 | input 71,430；cache-read 743,424；output 5,548 |
| Main + subagent token | input 400,712；output 8,593 | input 1,304,556；output 20,618 | input 109,608；cache-read 773,632；output 7,590 |

`18/19/17 passed` 来自三个 agent 各自扩展后的不同测试集，不能当作质量分数。token 是各宿主
transcript 的 usage，Pi 还把 cache-read 单独计数；它们不等同于价格，单次墙钟也不能推导稳定
速度差异。Unicode Kelvin sign 是统一的额外探针：Direct Codex 与 Goal Plus + Pi 都把 `K`
匹配进忽略大小写的 `K`，随后触发 `KeyError`；Goal Plus + Codex 运行中发现并修为合同要求的
`ValueError`。因此 `pytest passed` 只证明各自生成的测试集通过，不证明完整合同已覆盖。

## 证据路径

Codex Direct Ultra：

- [Main transcript](../runs/ultra-direct-codex-live-20260819/.direct-ultra/host-logs/codex-main-01a017ec-5dbb-7752-92b5-80849d30ef37.jsonl)
- [Subagent transcript](../runs/ultra-direct-codex-live-20260819/.direct-ultra/host-logs/codex-subagent-01a017ec-b95b-7c30-a91b-c9ffde352dc4.jsonl)
- [最终实现](../runs/ultra-direct-codex-live-20260819/size_parser.py)
- [最终测试](../runs/ultra-direct-codex-live-20260819/test_size_parser.py)

Goal Plus Ultra + Codex：

- [Goal 状态](../runs/ultra-attempt-smoke-codex-live-20260819/.gp/goal-plus/gp_0001/goal.json)
- [完整编排事件](../runs/ultra-attempt-smoke-codex-live-20260819/.gp/goal-plus/gp_0001/events.jsonl)
- [Main transcript](../runs/ultra-attempt-smoke-codex-live-20260819/.gp/host-logs/codex-main-01a017cc-b9bc-7141-b332-f0d54e8011f6.jsonl)
- [Subagent transcript](../runs/ultra-attempt-smoke-codex-live-20260819/.gp/host-logs/codex-subagent-01a017ce-68fb-7a92-bbe3-50f36334ec99.jsonl)

Goal Plus Ultra + Pi：

- [运行配置](../runs/ultra-attempt-smoke-pi-live-20260820/run-manifest.json)
- [Goal 状态](../runs/ultra-attempt-smoke-pi-live-20260820/.gp/goal-plus/gp_0001/goal.json)
- [完整编排事件](../runs/ultra-attempt-smoke-pi-live-20260820/.gp/goal-plus/gp_0001/events.jsonl)
- [Main transcript](../runs/ultra-attempt-smoke-pi-live-20260820/.gp/host-logs/pi-main.jsonl)
- [Subagent transcript](../runs/ultra-attempt-smoke-pi-live-20260820/.gp/host-sessions/pi/2026-08-20T07-44-14-037Z_gp_0001_edge-tests_1787211852002.jsonl)
- [最终实现](../runs/ultra-attempt-smoke-pi-live-20260820/size_parser.py)
- [最终测试](../runs/ultra-attempt-smoke-pi-live-20260820/test_size_parser.py)

## 如何理解差异

Direct Ultra 的链路最短：Codex Main 直接委派、接收结果、集成。Goal Plus 没有要求不同
宿主伪装成同一条原生命令；它统一的是控制协议。Codex host 把普通工作项映射到
`spawn_agent`，Pi host 映射到 `pi_goal_plus_run_work_item -> goal-plus-pi-worker -> pi --mode rpc`，
两者都向 Goal Plus 回报 `dispatch -> bind -> result -> accepted`，且只有所有必需工作项被 Main
验收后，Goal 才能进入 `complete`。

因此现有证据支持：**三条路径都完成了同题和真实 subagent 下发；Goal Plus 在 Codex 与 Pi
两种 host 上提供了同构的持久 DAG、attempt fencing 与终态门禁，而实际 spawn 命令保持宿主
原生。** 本次没有演练重启 reconciliation、TTL 重发或 stale-result rejection，不能把协议存在
写成故障恢复已经经过实测。Pi provider 的 reasoning clamp 和两条路径遗漏的 Unicode 边界也说明，
控制面证据不能代替模型能力与测试覆盖率证据。

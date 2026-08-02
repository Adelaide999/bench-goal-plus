# SWE-bench Verified

## 30 秒理解

SWE-bench Verified 测试 Agent 能否根据真实 GitHub issue 修改一个真实代码仓库，并让
官方隐藏回归测试通过。当前接入面是一个 Linux/amd64 单题 smoke，用来验证容器隔离、
patch 导出和官方 harness 接线，不代表 500 题完整 campaign 已 ready。

当前固定 case 是 `sympy__sympy-16886`。数据集 revision、仓库 base commit 和官方任务镜像
均写入 profile；最终原始指标是官方 `resolved` 布尔值，方向为 maximize。

## 代表 case：`sympy__sympy-16886`

### 输入是什么

Agent 只看到 issue problem statement、仓库名、base commit 和任务镜像标识。完整数据行只
保存在 host campaign 的 evaluator 目录；gold patch、test patch、`FAIL_TO_PASS` 和
`PASS_TO_PASS` 不会进入 Agent task 文件或 prompt。

### Agent 要做什么

Plain Codex 或 Plain Pi 在精确的 SWE-bench task image 内修改 `/testbed`，检查代码并运行
可见测试。初始路径固定一条隔离 outer trajectory，即 `K=1`。

### 期待输出是什么

controller 在 Agent 结束后导出唯一的 `git diff --binary --full-index`。默认情况下 Agent
容器随后被确认删除；debug 模式则要求它被确认停止并保留。完成任一隔离状态后，patch 才能
交给独立的官方 evaluator。Agent 不直接给分，也不接触 evaluator 数据文件。

### Verifier 如何评分

官方 SWE-bench harness 在单独容器中应用 model patch，并执行该实例的官方测试脚本。
controller 保留 `resolved`、`patch_successfully_applied`、原始 `report.json` 和 evaluator
调用次数。同一 campaign 最多尝试一次官方 evaluator；未解决但报告完整仍是有效分数 0，
缺报告则是 partial/failed，不会静默写成 0。

## Docker 与空间

Docker 空间当前按本地精确 task image 的逻辑大小约 `2.56 GB` 记录；还要为 Agent 临时层、
官方 evaluator 容器和测试日志预留空间。无 Docker 环境只能读取 task/manifest，不能运行
Agent 容器，也不能产生官方 `resolved` 分数。

task image 始终保留：controller 固定使用官方 harness 的 `cache_level=instance`、
`clean=false` 和 `force_rebuild=false`，不会调用 `docker rmi`。需要检查 Agent 修改后的
`/testbed` 时，在 `plan` 和 `launch` 中同时增加 `--retain-containers`。runner 会停止而不是
删除 Agent 容器，并将 name/ID 写入 status 和最终报告；`finish` 不会自动清理它。当前开关
只保留 Agent 容器；官方 harness 仍清理独立 evaluator 容器，但其报告和日志会完整保留。

## 实验怎么用

当前提供两个冻结 preset：

| Preset | Method | Model | T/K/C/R |
| --- | --- | --- | --- |
| `swe-bench-verified-sympy-16886-codex-smoke` | Plain Codex | `gpt-5.6-sol`, medium | `1800/1/1/1` |
| `swe-bench-verified-sympy-16886-pi-smoke` | Plain Pi | `zai/glm-5.2`, medium | `1800/1/1/1` |

两个 campaign 顺序运行。runner 暂不支持 Goal Plus、provision、detach、stop、resume、
`K>1` 或 `C>1`。真实 launch 前仍必须展示并确认解析后的 T/K/C/R。

Codex preset 另外冻结 `auth_mode=openai-compatible`、`OPENAI_BASE_URL`、
`OPENAI_API_KEY` 和 Responses wire API。Linux 上的 loopback endpoint 使用与 EdgeBench
相同的 `systemd-socket-proxyd` bridge；doctor 会分别验证 host 和实际 task container 的
`POST /responses`。该路径不读取 OAuth auth file；日志里出现 `chatgpt.com` 应视为路由错误。

## 可复用对比数据

报告保留 task、method、model、reasoning、dataset revision、SWE-bench commit、base commit、
image、raw metric/direction、Agent 与 evaluator 墙钟时间、finalization grace、token coverage、
evaluator calls 和 patch apply 状态。缺失 token 数据保持 unavailable，不补零。

单题 smoke 可以证明方法接线与官方评分边界，但不能用于声称整个 Verified split 的通过率，
也不能与不同 T/K/C/R 的结果做 matched comparison。

## 代码与证据

- Runner/target/preset：[`benchmarks/runners.json`](../../benchmarks/runners.json)
- Dataset revision：[`benchmarks/datasets.json`](../../benchmarks/datasets.json)
- Native controller：[`experiments/swe_bench_verified/README.md`](../../experiments/swe_bench_verified/README.md)
- Readiness：[`benchmarks/registry.json`](../../benchmarks/registry.json)

下载源只允许加速传输。国内 PyPI 或 Hugging Face mirror 不得替换锁定 revision、精确 Docker
tag、image ID 或官方 evaluator；目标镜像已存在时不会主动 pull。

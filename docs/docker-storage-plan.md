# Benchmark 镜像空间与本机 smoke 计划

## 结论

当前这台 Intel Mac 适合做“每个 benchmark 一个 case、串行运行”的接线验收，不适合做完整 campaign。2026-07-25 实测为 16 GiB 物理内存、Docker VM 8.40 GB、12 个逻辑 CPU；完成 SkyDiscover 非 Torch evaluator pack 后，数据盘仍有约 110 GiB 可用。

Docker 当前总量是 33.83 GB images、9.61 GB build cache、1.50 GB stopped containers。这些数字包含 EdgeBench 和其他项目，不能全部算到本项目，也没有自动清理；其中标成 reclaimable 的内容仍可能是用户保留的实验资产。

## 已测的单 case 与 task pack 占用

下表的“镜像逻辑大小”是 `docker image inspect` 的可移植口径。实际新增占用会因 Ubuntu、Python 等共享层更小；多 tag task pack 同时给出 `docker system df` 的实际增量，两个口径不能相加。

| Benchmark | 代表 case | 镜像逻辑大小 | 当前 checkout | 本机结果 |
|---|---|---:|---:|---|
| ALE-Bench Lite | `ahc027`，C++ 路径 | 4.03 GB（C++ 2.73 + Rust judge 1.30） | 0.91 GB | public/private evaluator 已通 |
| HeuriGym | `operator_scheduling` | 不用 Docker | 0.37 GB | `valid=true, cost=7` |
| Frontier-Engineering v1-lite | `ComputerSystems/MallocLab` | v1-lite 不用 Docker | 0.034 GB sparse checkout | 官方 verifier 返回 28/100，6/11 cases |
| AutoLab | `toy_isa_opt` | 0.277 GB | 0.75 GB | `cycles=9220, verify=ok` |
| SwarmResearch | `math/circle_packing` | 0.196 GB（host agent + evaluator-only）或 2.10 GB（论文式 agent CLI task image） | 1.25 GB | evaluator 成功，score 0.9597642169962064 |
| SkyDiscover task pack | Math/ADRS 非 Torch 19 tags | 8.57 GB logical；共享层后 images 实际新增约 2.49 GB | 0.013 GB | 19/19 构建完成，`pip check` 全通过，0 个镜像含 Torch |
| Frontier-CS | `algorithmic/problem-0` | 1.27 GB | 0.023 GB sparse checkout | judge 完整执行，raw score 93.089935 |
| EdgeBench | `vliw_kernel_optimization` | 2.23 GB logical（work 1.12 + judge 1.12，共享层使实际增量更小） | 0.024 GB（含 51 个 task definitions） | Plain / Goal Plus 两条真实 lifecycle E2E 均完成 |
| PERFOPT-Bench | — | 无可用公开镜像 | — | 可执行 artifact 仍不可用 |

ALE 如果还要接受 Rust candidate，再增加 `ale-bench:rust-202301` 2.29 GB；C++ + Rust 两条路径合计 6.32 GB。ALE Lite 的 10 个 task 复用这些语言/judge 镜像，并不是 10 × 6.32 GB。

Frontier-CS 的参考程序得到部分优化分数，但上游把任何 `scoreRatio != 1.0` 都标成 `Wrong Answer`。这不是容器失败：checker 已完成合法性检查并发出 `Ratio: 0.930899350`；后续 adapter 必须读 raw score，而不能把 `passed` 布尔值当唯一有效性信号。

## 完整 benchmark 要预留多少

公开仓库没有提供一份可直接相加的全镜像 manifest，因此完整集只能区分“已测下限”和“规划预留”，不能伪造精确值。

| Benchmark | 完整范围的空间判断 | Linux 规划值 |
|---|---|---:|
| ALE-Bench Lite 10 | 主要共享 3 个固定镜像；加 checkout 后约 7.3 GB | 10 GB |
| HeuriGym 9 | 无 Docker；当前 venv + 已下载数据仅 0.37 GB，重任务可能再拉系统/数据依赖 | 5 GB |
| Frontier-Engineering v1-lite 10 | 无统一 Docker；10 个 task 使用多个 Python runtime、task-local 依赖和外部资产 | 10–20 GB，跑 setup 后再冻结实测 |
| AutoLab 36 | 36 个 Dockerfile，其中 11 个基于 CUDA 12.4/12.8；模型、编译链和数据层会主导空间 | 至少 50–100 GB；只选 6–10 题时逐题构建 |
| SwarmResearch 15 | 论文式共享 base 已测 2.03 GB；各 evaluator 增量共享，但 ADRS/ALE worker 构建上下文目前不完整 | 10–20 GB；修复上游布局后生成精确 manifest |
| SkyDiscover Math/ADRS 非 Torch pack | 15 个 Math + 4 个 ADRS evaluator tags；逻辑总和 8.57 GB，当前 Docker store 实际增量约 2.49 GB | **10 GB**；明确不含 `eplb`、`second_autocorr_ineq`、GPU Mode 和 KernelBench |
| Frontier-CS Algorithmic | 188 题共用 1.27 GB judge；题数增加不会复制这张镜像 | **2 GB**；2.0 systems/GPU 不在当前范围 |
| EdgeBench open-source 51 | 每题可有独立 work/judge tag；VLIW 两张镜像逻辑合计 2.23 GB，但跨题共享层和任务差异未知 | 先为 8–12 gradient subset 预留 20–60 GB，provision 后按 image digest 冻结实测 |
| PERFOPT-Bench | artifact 未恢复，无法估算 | 暂不预留到 campaign 配额 |

当前用户选择的 no-GPU 环境里，SkyDiscover 非 Torch pack 与 Frontier-CS
judge 的逻辑大小合计约 `9.84 GB`。由于 19 个 evaluator tags 共享 Python 和
科学计算依赖层，本机实际只新增约 `2.49 GB` images，主机空闲空间粗粒度下降
约 `3 GiB`。考虑 build cache、临时容器和日志，给这组环境预留 `10 GB` 即可；
当前约 `110 GiB` 空闲空间完全够用。

## 当前 Mac 的运行边界

- ALE、HeuriGym、Frontier-Engineering、AutoLab CPU case、Swarm math、
  SkyDiscover 非 Torch Math/ADRS evaluator 和 EdgeBench VLIW 可以串行跑。
- Frontier-CS 已在 Docker VM 中用 `--privileged --shm-size=4g`、1 worker、1 go-judge parallelism 跑通；不要在 8.4 GB VM 上并发多个 judge。
- AutoLab CUDA、Frontier-CS GPU/systems，以及多 seed × 多 method campaign 不应放在本机。
- 本机只承担 materialize、agent 接线、official evaluator、evidence schema 和恢复机制 smoke；论文结果统一到 Linux 重跑。

## Linux 统一实验建议

1. 先准备 CPU controller 节点：`linux/amd64`、32–64 GB RAM、16–32 cores、至少 250 GB 可用 NVMe。它覆盖 Core、AutoLab CPU subset、Swarm math/ADRS 和 Frontier-CS algorithmic。
2. GPU/system 任务单独放到 64–128 GB RAM、500 GB 以上 NVMe、匹配 CUDA/H100 条件的 worker；不要让 GPU 镜像挤占 controller 的 Core campaign。
3. 每个 case 的 manifest 固定 benchmark commit、Dockerfile hash、image digest、架构、数据版本和 evaluator 命令。Mac 当前也是 amd64，镜像可直接验证，但正式服务器应重新 build/pull 并按 digest 锁定，不以手工 `docker save` 作为主流程。
4. 先完成“一题一镜像/环境一条确定性 baseline”，再扩 subset。共享 base 只构建一次；不同方法（plain Codex、Goal Plus、EvoX/OpenEvolve）复用同一个只读 evaluator image。

代表 case 的机器和镜像数据保存在
[`evidence/environment/2026-07-21-mac-representative-smokes.json`](../evidence/environment/2026-07-21-mac-representative-smokes.json)；
SkyDiscover 19-tag 审计保存在
[`evidence/environment/2026-07-25-skydiscover-cpu-docker-images.json`](../evidence/environment/2026-07-25-skydiscover-cpu-docker-images.json)。

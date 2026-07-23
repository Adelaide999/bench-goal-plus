# EdgeBench open-source subset

## 30 秒理解

EdgeBench 测的是 agent 能否在真实工程/研究 artifact 上持续改进，并由隔离的
hidden judge 给出 correctness 与连续分数。公开子集当前有 51 题，跨系统软件、
算法优化、形式化、仿真和交互环境；并非每题都适合当前 Mac。

对 Goal Plus 最有价值的是其中的 gradient cases：合法候选不只得到 pass/fail，
还得到可连续优化的 raw score。这样能区分共享证据、跨 lineage transfer 和
best-seen 搜索能力，而不只是 Pass@K。

| 项目 | 内容 |
|---|---|
| 公开范围 | 51 题；本项目先冻结 8–12 个 gradient cases |
| Docker | **必需**；SForge 为每题启动 work container 与独立 hidden judge |
| 无 Docker 环境 | 可以 bootstrap 源码和阅读 task JSON，但不能运行或评分 EdgeBench |
| 当前门禁 | VLIW 的环境、Plain/Goal Plus lifecycle 与 usage 回收已通 |
| 固定源码 | `ByteDance-Seed/EdgeBench@b27bf1b` |

## 代表 case：VLIW Kernel Optimization

### 输入是什么

任务 workspace 提供自定义 VLIW/SIMD simulator、kernel generator、
`solution.py`、public tests 与说明。agent 的自然任务正文来自 pinned task JSON：
实现并优化 `KernelBuilder.build_kernel`，只允许修改 `solution.py`。

### Agent 要做什么

生成正确的 instruction program，运行公开 verifier，分析 cycle bottleneck，并
迭代降低 simulator cycles。Plain Codex 的 K 条 replica 相互独立；Goal Plus 的
K 个 workers 共享 Search Evidence/Schema，但各自在隔离 candidate workspace
工作，只有 main session 能 promotion 后提交 hidden judge。

### 期待输出是什么

最终 artifact 是一个可执行且未修改测试/runner 的 `solution.py`。SForge 保存
`final_archive.tar.gz`、每轮 submission report、`final_result.json` 和完整 agent
输出；Goal Plus 额外保存 state archive。

### Verifier 如何评分

hidden runner 先检查所有 hidden cases correctness，再以 cycles 为 raw score，
方向是 minimize。SForge 使用 task JSON 中固定的 `log_min` rescale 把 raw
cycles 转成 EdgeBench 0–100；无效候选没有合法 cycle score。

## 实验怎么用

先使用 `vliw-smoke` profile 验证一题：

```bash
python3 scripts/repro_env.py bootstrap --only edgebench
.bench-env/venv/bin/python experiments/edgebench/experiment.py provision \
  --profile vliw-smoke
.bench-env/venv/bin/python experiments/edgebench/experiment.py doctor \
  --profile vliw-smoke
.bench-env/venv/bin/python experiments/edgebench/experiment.py prepare \
  --profile vliw-smoke --campaign-id vliw-matched-01
.bench-env/venv/bin/python experiments/edgebench/experiment.py run \
  --campaign vliw-matched-01 --detach
```

正式对比固定 task/data revision、model/reasoning、总时间 `T` 和 live concurrency
`K`。Plain Codex 用 K 个 SForge replicas；Goal Plus 用一个 outer SForge run
与 K 个 internal workers。cells 在一台机器上默认串行，避免资源超卖。

## 可复用对比数据

EdgeBench README 提供 open-source 51-task 的 model reference curves，fork 的
score reporter 会按任务和最近 checkpoint 保留官方参考。当前本地两条真实
VLIW smoke 为：

- Plain Codex `gpt-5.5`，`T=180s,K=1`：4941 cycles；
- Goal Plus + Codex `gpt-5.6-terra/high`，`T=3600s,K=3`：1878 cycles，
  EdgeBench score 57.9476。

它们的模型、T、K 不同，只能证明接线，不是方法效果对比。正式数据必须由同一
campaign profile 生成，并同时报告 evaluator calls、wall time、tokens/cost
coverage 和 Goal Plus lineage 统计。

统一 controller 另有一轮同模型、同 `T=120s,K=1` 的真实 lifecycle E2E：
Plain / Goal Plus 均完成 work container、owned judge、timeout closeout 和
finalize；两者 raw 都是 seed `147734`。Goal Plus 在短预算内创建了 Goal、
frozen spec 和 Search run，但尚未 dispatch worker，因此这轮只证明控制面与
telemetry，不用于方法排名。正式短 pilot 应至少使用 `T>=300s,K>=2`。

## 代码与证据

- [EdgeBench campaign controller](../../experiments/edgebench/README.md)
- [固定 profile](../../experiments/edgebench/profiles/vliw-smoke.json)
- [环境 doctor](../../evidence/environment/2026-07-23-edgebench-vliw-doctor.json)
- [真实接线 smoke](../../evidence/runs/2026-07-23-edgebench-codex-goal-plus-smokes.md)
- [fork](https://github.com/ck0123/EdgeBench)
- [官方数据集](https://huggingface.co/datasets/ByteDance-Seed/EdgeBench)

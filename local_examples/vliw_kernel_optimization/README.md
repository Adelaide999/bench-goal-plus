# Local VLIW Kernel Optimization

这是从 EdgeBench VLIW Kernel Optimization 的固定 work/judge images 中提取的
host-only task replica。它只使用 Python 标准库，不需要 Docker、GPU、NPU、
数据下载或系统编译器。

## 快速验证

从 `bench-goal-plus` 根目录运行：

```bash
python3 local_examples/vliw_kernel_optimization/evaluate.py --cases both
```

starter solution 应在 public 和 held-out case 上都通过，主 workload 为
`147734 cycles`。

## 标准 Plain Codex / Goal Plus 入口

先按根目录 `AGENTS.md` 建立 `.bench-env` 和受管
`third_party/muyuan/plugins/goal-plus` source，然后：

```bash
.bench-env/venv/bin/python experiments/benchmark_compare/experiment.py prepare \
  --benchmark local-vliw --method plain-codex \
  --wall-time-seconds 360 --soft-closeout-seconds 60 \
  --worker-runtime-seconds 120 --concurrency 2 --model gpt-5.6-sol

.bench-env/venv/bin/python experiments/benchmark_compare/experiment.py prepare \
  --benchmark local-vliw --method goal-plus-codex \
  --wall-time-seconds 360 --soft-closeout-seconds 60 \
  --worker-runtime-seconds 120 --concurrency 2 --model gpt-5.6-sol
```

两条路径都从 `task/starter_solution.py` materialize 全新 Git workspace，并使用
相同任务正文和 evaluator。Plain Codex 的 `K` 表示独立 lane；Goal Plus 的
`K` 表示内部并行 lineage。

## 边界

- `task/` 是 agent workspace 的来源，只含 public cases。
- `controller/` 保存 held-out local cases 和冻结 simulator，用于最终评估。
- 这些 held-out cases 在仓库内，因此只能防止正常 workspace agent 偶然看到，
  不能对拥有宿主全盘读取权限的 agent 提供安全隔离。
- EdgeBench 的正式可比分数仍必须通过 SForge 的独立 work container 与 hidden
  judge container 获得。这里的结果统一标记为 `local_example` 和
  `official_edgebench_comparable=false`。

来源与镜像信息见 [PROVENANCE.md](PROVENANCE.md)。

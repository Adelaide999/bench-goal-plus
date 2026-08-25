# TorchBench adapter

这个 adapter 通过一个 common target 接入多个 TorchBench model。受管 upstream 位于
`third_party/torchbench`，始终保持 clean；每个 Agent workspace 包含该 commit 的 tracked
files，但 verifier 只把目标 model 目录投影到临时的 clean evaluation tree。

第一版支持 CUDA eval：

- `alexnet`，batch size 128，final 额外检查 batch size 64；
- `BERT_pytorch`，batch size 16，final 额外检查 batch size 8；
- `resnet18`、`mobilenet_v2`、`squeezenet1_1`，batch size 128，final 额外检查
  batch size 64。

TorchBench 的 GPU 依赖不安装进仓库公共 `.bench-env`。运行前指定一个已经安装好相应
model 依赖的 Python，以及 candidate 使用的 GPU pool：

```bash
export BENCH_GOAL_PLUS_TORCHBENCH_PYTHON=/path/to/torchbench-env/bin/python
export BENCH_GOAL_PLUS_TORCHBENCH_GPUS=0,1
export BENCH_GOAL_PLUS_TORCH_HOME=/path/to/preloaded/torch-cache

python3 scripts/bench.py setup --benchmark torchbench
python3 scripts/bench.py plan \
  --benchmark torchbench \
  --task-id BERT_pytorch \
  --method goal-plus-pi \
  --model gpt-5.6-sol \
  --reasoning-effort high \
  --wall-time-seconds 3600 \
  --live-search-concurrency 2
```

Pi 直接使用 host CUDA。Codex 的 `workspace-write` sandbox 不暴露 host GPU，因此此
adapter 显式使用 `danger-full-access`，并把选择写入 run manifest；Codex 路径只应在
隔离的 benchmark host 或 VM 上运行。candidate workspace 和 final evaluator 仍只接收
目标 model 目录。

确认 plan 后，把 `plan` 换成 `launch`。新增普通 eval model 时只扩展 `models.json` 的
batch size、correctness tolerance 和 timing policy；需要数据下载、特殊输出语义或其他
execution mode 的 model 仍应先做单独 preflight，不能默认宣称兼容。

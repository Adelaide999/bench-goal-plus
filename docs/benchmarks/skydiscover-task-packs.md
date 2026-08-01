# SkyDiscover 自带 task packs：Docker 与空间

SkyDiscover 是搜索 runtime，不是一套独立 benchmark；本页只记录它仓库自带
Math、ADRS、prompt optimization 和 image generation tasks 的环境边界。
这些任务可以交给 Best-of-N、EvoX、AdaEvolve 等方法，但不能因为换了搜索方法
就重复计算 benchmark 数量。

统一只读盘点与受管供给入口为：

```bash
python3 scripts/bench.py check \
  --asset-pack skydiscover-cpu-evaluators --profile cpu-no-torch-19
python3 scripts/bench.py setup \
  --asset-pack skydiscover-cpu-evaluators --profile cpu-no-torch-19 \
  --skip-provision
```

19 个 tag 是本地 evaluator build tag，不是公开 registry 镜像。只有盘点明确报告缺失且
用户要求补齐后，才去掉 `--skip-provision`，从固定 SkyDiscover commit 和逐 context
Git tree 构建。构建镜像记录 revision/tree labels；历史 Mac image ID 作为审计基线保留，
不能用一次新的非锁定依赖构建冒充同一 image ID。构建所需的 `python:3.12-slim`
固定 Linux/amd64 manifest 与 image ID；本地缺失时按 profile 登记的传输源尝试，
并在导入后核对两者，国内源只用于加速同一份内容。Python requirements 使用
profile 固定的 PyPI index；构建适配层只在 `.tmp/` 生成增加
`ARG PIP_INDEX_URL` 的 Dockerfile，并把 index 写入 provenance label，不修改固定
SkyDiscover checkout。

## 当前可用范围

| 范围 | 当前路径 | Docker | Docker 空间 |
|---|---|---|---:|
| Circle Packing compatibility smoke | host `evaluator.py` | 不需要 | `0 GB` |
| Math/ADRS 非 Torch CPU evaluator pack | 15 个 Math + 4 个 ADRS，共 19 个镜像 tag | 需要 | 逻辑总和 `8.57 GB`；共享层实际新增约 `2.49 GB`；建议预留 `10 GB` |
| HotPotQA prompt optimization | host 数据集与模型 API | 不需要 | `0 GB`；另计数据和 API 成本 |
| Image generation | host 图像/API evaluator | 不需要 | `0 GB`；另计生成与 judge API 成本 |

这 19 个镜像已经在 `linux/amd64` Docker 环境完成构建和 `pip check`。所有镜像
都基于 `python:3.12-slim`；逐 tag 的 `docker image inspect` 逻辑大小相加为
`8.568 GB`，但 NumPy/SciPy、JAX/Optax 和 Python base 层会复用，因此本机
`docker system df` 的 images 增量只有约 `2.49 GB`，主机可用空间的粗粒度
变化约为 `3 GiB`。逻辑大小和实际增量不能相加。

## 明确排除

当前 no-GPU/no-Torch 范围不包含：

- `ADRS/eplb`；
- `math/second_autocorr_ineq`；
- `gpu_mode/*`；
- `kernelbench`。

前两个 task 的 requirements 含 `torch`，本轮没有构建对应 tag，也没有把
Torch/CUDA 依赖计入 `8.57 GB`。Circle Packing 虽然上游带 evaluator
Dockerfile，但当前兼容性 smoke 使用 host evaluator，所以同样没有计入。

## 与 Frontier-CS 合并规划

Frontier-CS Algorithmic 共用的 pinned judge image 为 `1.27 GB`。它与上述
19 个 SkyDiscover tags 的逻辑大小合计约 `9.84 GB`；考虑共享层、build cache、
临时容器和运行日志，这组 no-GPU 环境按 **至少 `10 GB` 可用空间**规划即可。

这里的空间结论只覆盖 evaluator/runtime 环境，不包含长期 Search workspace、
模型输出、候选历史或完整数据集缓存。

## 证据与相关文档

- 镜像逐 tag 清单与校验：
  [`evidence/environment/2026-07-25-skydiscover-cpu-docker-images.json`](../../evidence/environment/2026-07-25-skydiscover-cpu-docker-images.json)
- 统一空间规划：[Benchmark 镜像空间与本机 smoke 计划](../docker-storage-plan.md)
- 方法与 runtime 分类：[实验对象分类](../experiment-taxonomy.md)

[返回 Benchmark 导读](README.md)

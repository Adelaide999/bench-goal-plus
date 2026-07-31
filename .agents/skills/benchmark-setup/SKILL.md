---
name: benchmark-setup
description: 自动部署或诊断 bench-goal-plus benchmark 环境。用户要求安装依赖、拉取上游、下载 Docker 镜像、配置国内可用下载源、检查新机器是否满足 EdgeBench 或其他已登记 benchmark 的运行条件时使用。
---

# Benchmark 环境部署

从仓库根目录执行。先读 [benchmark-matrix.md](references/benchmark-matrix.md)，再以
`benchmarks/registry.json` 和 `environment/upstreams.json` 的当前内容为事实源。

## 流程

1. 确认 `git`、Python 3.10+、`uv`、Codex CLI 0.144.1+；只报告缺失项，不把凭据写入文件。
2. 同时读取 `benchmarks/registry.json` 的 readiness Docker 边界和 `benchmarks/runners.json` 的可执行 Docker contract。需要 Docker 时先运行 `docker info`；失败则停止需要容器的路径。
3. 运行 `python3 scripts/repro_env.py bootstrap --only <upstream>`。多个上游重复传 `--only`。让脚本管理 `.bench-env/venv`、`third_party/` 和 repository-local `.tmp/`。只有准备运行 `goal-plus-pi` 时才加 `--require-pi`；Plain Codex 和 Goal Plus + Codex 不应被缺失的 host Pi 阻断。
4. 运行同参数的 `doctor`。不得绕过 dirty、wrong-origin、wrong-branch、divergent 或版本检查。默认 `host:pi` 是诊断项；`--require-pi` 才把它升级为硬依赖。
5. 按 Docker owner/mode 执行 provision：native runner 调自己的 provision/doctor；eager adapter 调标准 hooks；lazy adapter 保留 evaluator 自带的创建逻辑。`--skip-provision` 也不能跳过 doctor。
6. 汇报执行命令、resolved branch/commit、Docker 状态、已拉镜像/数据 revision、pass/fail/partial 和下一步。

## 约束

- 保留上游 fork，不复制源码或数据进本仓。
- 不自动删除冲突 checkout、cache、workspace 或镜像；保留为 `_bak` 并报告。
- 国内镜像只用于传输加速。不得替换 benchmark 固定的 image tag、数据 revision、SHA256 或 evaluator。
- 不在命令、日志、manifest 或报告中持久化 API key、auth、cookie、provider header。
- 只有实际执行且留下 evidence 的检查才能记为 `pass`；未运行能力最多为 `partial`。

## Gotchas

- `bootstrap --only` 接受 upstream key，不一定等于 registry benchmark id。
- `mixed` 不代表无 Docker 等价可跑；只运行 `docker_scope` 明确允许的 host-portable task。
- EdgeBench 的 `provision` 与 `doctor` 都是必要步骤；只拉源码不代表 work/judge image 和隔离能力可用。
- 新 benchmark 自带 Docker 时优先登记 `owner=runner` 并复用其 native 命令；不要把 Dockerfile 或镜像逻辑复制进 Skill。
- 当前不实现统一 Docker Hub 拉取或自动改写 registry。已有精确 tag 的本地镜像由 benchmark-native doctor 验证；未来的镜像传输兼容放在 runner 的 native provision 或 adapter 的 `provision_environment`/`doctor_environment` hooks 中。

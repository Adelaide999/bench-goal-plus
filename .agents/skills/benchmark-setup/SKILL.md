---
name: benchmark-setup
description: 自动盘点本地 Docker 镜像并部署或诊断 bench-goal-plus benchmark 环境、provider 和认证配置。用户要求查看已有 benchmark 镜像、安装依赖、拉取上游、下载 Docker 镜像、配置国内可用下载源、检查 macOS/Linux 新机器，或验证 OAuth、API key、provider/model、endpoint、Anthropic/OpenAI-compatible wire API 是否满足 EdgeBench 或其他已登记 benchmark 的运行条件时使用。
---

# Benchmark 环境部署

从仓库根目录执行。先按实际 host/provider 读
[host-auth.md](references/host-auth.md)，再读
[benchmark-matrix.md](references/benchmark-matrix.md)。以
`benchmarks/registry.json`、`benchmarks/runners.json` 和
`environment/upstreams.json` 的当前内容为事实源。

## 流程

1. 明确 benchmark、runner、macOS/Linux、agent 和 auth mode。若用户没有指定，
   从 preset/method 和当前 host 推导，并在执行前汇报选择。
2. 确认 `git`、Python 3.10+、`uv`，再按 method 检查 agent runtime：Codex 路径要求
   Codex CLI 0.144.1+，Pi 路径要求 registry 固定的 Pi 最低版本；同时记录实际
   `pi --version`。EdgeBench smoke 默认可跟随 `latest`，正式 campaign 应冻结已验证的
   `SFORGE_PI_PACKAGE_VERSION`。未选中的 agent 只作为
   diagnostic，不得阻塞 setup；只报告缺失项，不把凭据写入文件。
3. 同时读取 registry 的 readiness Docker 边界、target 的 inventory capability 和
   runner 的可执行 Docker contract；只有 target 或 asset pack 声明
   `local_asset_inventory=true` 才能使用 profiled check。不得因为共享 runner 中有一个
   target 支持 inventory，就替其他 target 自动放行。
   需要 Docker 时先运行 `docker info`；失败则停止需要容器的路径。
4. **任何 setup、数据下载、镜像拉取或构建之前，先执行只读本地 inventory gate**：
   `python3 scripts/bench.py check --benchmark <id> --profile <profile>`；使用 preset 时执行
   `python3 scripts/bench.py check --preset <preset>`；独立 task pack 执行
   `python3 scripts/bench.py check --asset-pack <id> --profile <profile>`。逐项核对 task file、dataset revision、
   精确 Work/Judge image tag、image ID 和关联容器。此命令不得 provision、fetch、pull、
   build、run 或检查凭据；失败只报告缺失项。不得把 provision 当作本地 inventory probe。
5. inventory 后再通过
   `python3 scripts/bench.py check --environment` 检查根仓库、Goal Plus 和所有受管
   benchmark 的远端分支。该复合检查先执行 registry 声明的全部默认 inventory gate，
   再以只读 `git ls-remote` 探测更新；交互终端检测到更新时统一询问，确认后仅允许
   fast-forward。非交互环境只报告并失败关闭，需要明确使用 `--yes` 才能更新。
6. 然后通过
   `python3 scripts/bench.py setup --benchmark <id> --profile <profile> --skip-provision`
   （或对应 `--preset`）完成受管 bootstrap 和完整 doctor。全部通过时立即停止 setup，
   不得再调用 `provision`、`fetch-tasks` 或 `pull`。
   Asset pack 使用 `setup --asset-pack <id> --profile <profile> --skip-provision`。
7. 只有 inventory/doctor 明确列出缺失或错误的 task/data/image，并且用户要求或确认联网
   补齐时，才去掉 `--skip-provision` 执行已登记的 provision。只在诊断底层 bootstrap 时
   直接使用 `scripts/repro_env.py`。
8. 不得绕过 dirty、wrong-origin、wrong-branch、divergent、版本、auth、container
   architecture、network bridge 或 resource-limit 检查。
9. 汇报 host/auth 组合、resolved branch/commit、Docker 状态、复用或新拉取的镜像、数据 revision、
   pass/fail/partial 和下一步。

## 约束

- 保留上游 fork，不复制源码或数据进本仓。
- 不自动删除冲突 checkout、cache、workspace 或镜像；保留为 `_bak` 并报告。
- 国内镜像只用于传输加速。不得替换 benchmark 固定的 image tag、数据 revision、SHA256 或 evaluator。
- 不在命令、日志、manifest 或报告中持久化 API key、auth、cookie、provider header。
- 只有实际执行且留下 evidence 的检查才能记为 `pass`；未运行能力最多为 `partial`。

## Gotchas

- `bootstrap --only` 接受 upstream key，不一定等于 registry benchmark id。
- `mixed` 不代表无 Docker 等价可跑；只运行 `docker_scope` 明确允许的 host-portable task。
- 不带 `--profile` 的 benchmark `check` 只是仓库契约检查，不是 Docker inventory。
  target 不支持 profiled local-asset check 时必须默认拒绝，不得改用 provision 探测。
- EdgeBench 的 `doctor` 是必要步骤；只有本地 task/data/image gate 失败时才需要
  `provision`。只拉源码不代表 work/judge image 和隔离能力可用，本地 gate 全部通过也不应
  重复拉取。
- 新 benchmark 自带 Docker 时优先登记 `owner=runner` 并复用其 native 命令；不要把 Dockerfile 或镜像逻辑复制进 Skill。
- 当前不实现统一 Docker Hub 拉取或自动改写 registry。已有精确 tag 的本地镜像由
  benchmark-native doctor 验证；EdgeBench native provision 会联网访问 HuggingFace，且
  会重新拉取 Work/Judge image，因此必须先通过 profiled `check` 和 `--skip-provision` gate。
  所有 EdgeBench 诊断性 `docker run` 必须使用 `--pull never`。未来的镜像传输兼容
  放在 runner 的 native provision 或 adapter 的 `provision_environment`/
  `doctor_environment` hooks 中。

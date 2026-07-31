# bench-goal-plus

`bench-goal-plus` 是一个让 Codex / CodeAgent 部署、运行、监控和汇总
benchmark 的控制面仓库，主要服务 Goal Plus 相关项目。

它不复制 benchmark 源码或重写官方 evaluator，而是把不同 benchmark 的原生运行方式
接到一套统一工作流中：

- 自动检查并部署环境：安装本地依赖、拉取受管上游、下载镜像和数据、验证鉴权。
- 一键启动 benchmark campaign，并为长任务保留可监控、可停止的 controller。
- 固定并记录 model、reasoning、`T/K/C/R`、task、evaluator 和 resolved commit。
- 汇总原始指标与运行证据，生成 `report.md` 和以 campaign ID 命名的 `.xlsx`。
- 用 scaffold、registry 和 contract tests 快速接入新 benchmark。

当前重点路径是 EdgeBench + Codex。Goal Plus 可以作为其中一种运行方法和证据机制，
但不是仓库本身的架构。

## 快速开始

所有用户操作都从仓库根目录使用同一个入口：

```bash
python3 scripts/bench.py catalog
```

先用 `catalog` 查看已登记的 benchmark、preset、runner capability 和支持的方法。

### 一键启动完整 EdgeBench Codex campaign

仓库内置 `edgebench-codex-2h` preset：

| 配置 | 值 |
| --- | --- |
| Tasks | EdgeBench 全部 51 题 |
| Method | Plain Codex |
| Model | `gpt-5.6-sol` |
| Reasoning | `medium` |
| 单任务预算 `T` | 2 小时 |
| 单任务 live search `K` | 1 |
| 任务并发 `C` | 2 |
| Repeats `R` | 1 |

先检查完整执行计划：

```bash
python3 scripts/bench.py plan --preset edgebench-codex-2h
```

确认后启动。该命令会按需执行 bootstrap、doctor、provision、prepare，并使用
EdgeBench 的 native detached controller 开始 campaign：

```bash
python3 scripts/bench.py launch --preset edgebench-codex-2h
```

这里的“并发 2”是同时运行两个 task cells，即 `C=2`；不是每道题启动两个候选。
如果 51 题都用满 2 小时，会排成 26 轮，墙钟约 52 小时，另加准备和收尾时间。

### 监控、停止和汇总

`launch` 会返回 campaign path，并把后续命令写入 `agent-run.json`：

```bash
python3 scripts/bench.py status \
  --campaign runs/edgebench/<campaign-id>

python3 scripts/bench.py stop \
  --campaign runs/edgebench/<campaign-id>

python3 scripts/bench.py finish \
  --campaign runs/edgebench/<campaign-id>
```

`finish` 调用 benchmark-native finalizer，再生成统一报告。主要产物包括：

```text
runs/edgebench/<campaign-id>/comparison.json
runs/edgebench/<campaign-id>/report.md
runs/edgebench/<campaign-id>/<campaign-id>.xlsx
```

例如：

```text
edgebench-51-codex-gpt-5-6-sol-medium-2h-k1-c2-20260724-1811.xlsx
```

停止不会删除 partial campaign。是否支持 resume、detach 或任务并发由 runner capability
决定，不能从 EdgeBench 自动推断到其他 benchmark。

## 环境和鉴权

不同 host、agent 和 provider 的准备方式并不相同：

- macOS 通过 Docker Desktop / OrbStack 提供 Linux `amd64` 容器和
  `host.docker.internal`。
- Linux 需要原生 Docker、资源限制能力；loopback API/Judge bridge 和离线网络隔离还有
 额外系统要求。
- Codex 可以使用本机 OAuth，也可以显式使用 OpenAI-compatible API。
- Pi、Claude 和 native OpenEvolve 的鉴权方式与 Codex 不相同。

运行前请按实际组合阅读
[Host 与鉴权矩阵](.agents/skills/benchmark-setup/references/host-auth.md)。
密钥只能放在宿主环境或既有 auth store 中，不能写进 profile、manifest、命令记录或报告。

## 运行其他 benchmark

统一生命周期不等于所有 benchmark 使用相同实现。控制面会根据 registry 选择：

- benchmark-native runner；
- common artifact/evaluator adapter；
- OpenEvolve batch runner。

基本命令保持一致：

```bash
python3 scripts/bench.py setup --benchmark <id>
python3 scripts/bench.py plan --benchmark <id> ...
python3 scripts/bench.py launch --benchmark <id> ...
python3 scripts/bench.py status --campaign <path>
python3 scripts/bench.py finish --campaign <path>
```

每类 runner 和各 benchmark 的实际差异由
[Benchmark runner map](.agents/skills/benchmark-run/references/runner-map.md)
链接到专属 reference；registry 中“存在”不代表已经完成真实 E2E。

## 接入新 benchmark

先决定保留 native harness，还是使用 common adapter：

```bash
python3 scripts/bench.py scaffold \
  --benchmark-id <id> --shape common

python3 scripts/bench.py scaffold \
  --benchmark-id <id> --shape native
```

scaffold 默认只展示计划；加 `--write` 才创建不覆盖已有文件的模板。完整接入流程见
[benchmark-adapt Skill](.agents/skills/benchmark-adapt/SKILL.md)。

## Agent 如何使用本仓库

[AGENTS.md](AGENTS.md) 定义仓库使命、标准 workflow、目录边界和 Skill 路由。
Skills 按用户任务分工：

| Skill | 用途 |
| --- | --- |
| `bench-goal-plus` | 识别请求并路由到下面的工作流 Skill |
| `benchmark-setup` | host、依赖、Docker、上游和鉴权 |
| `benchmark-run` | plan、launch、status、stop、resume |
| `benchmark-report` | native finalize、`report.md` 和 XLSX |
| `benchmark-adapt` | 新 benchmark 的 registry、adapter/runner 和验收 |

具体配置进入 Skill references 和 registry；通用代码进入 `bench_goal_plus/`；benchmark
专属 native lifecycle 留在 `experiments/<benchmark>/` 或对应 upstream fork。

## 开发验收

```bash
.bench-env/venv/bin/python scripts/status.py --check
.bench-env/venv/bin/python -m unittest discover -s tests -v
```

只有实际命令和 evidence 都存在时才能声明 `pass`。

# 可移植 OpenEvolve + Goal Plus 复现环境

## 目标

换到一台新的 Mac 或 Linux 主机后，只依赖本仓的 `AGENTS.md` 和固定 manifest，就能重建同一 Python runtime、同一 OpenEvolve/Goal Plus 源码版本，并生成不会污染上游 checkout 的实验 workspace。

本仓只保存控制面和 lock；不 vendor 上游源码、不保存 virtualenv、不保存模型密钥。默认布局为：

```text
code/
├── bench-goal-plus/        control plane
│   ├── .bench-env/venv/    可删除并重建的本机缓存，Git ignored
│   └── runs/.../workspace/ 每次实验的独立 Git workspace，Git ignored
├── openevolve/             固定 commit 的 sibling checkout
└── goal-plus/              固定 commit 的 sibling checkout
```

## 主机前置条件

- Git；
- 可运行 bootstrap 脚本的 Python 3.10+；
- `uv`；
- Codex CLI `0.144.1+`，且已完成需要的账号认证；
- 能安装 CPython 3.12 wheel 的 macOS 或 Linux。

`uv` 会按需取得 Python 3.12。Docker、编译器或 benchmark 数据仍由具体 benchmark 的 runbook 管理，不属于这一层的 OpenEvolve example smoke。

## 一键构建和检查

```bash
python3 scripts/repro_env.py bootstrap
python3 scripts/repro_env.py doctor
```

`bootstrap` 会：

1. 读取 `environment/upstreams.json`；
2. 在本仓父目录克隆缺失的 OpenEvolve/Goal Plus，并 checkout 到固定 commit；
3. 创建 `.bench-env/venv` 的 Python 3.12 环境；
4. 安装 `environment/requirements.lock`，再以 editable、`--no-build-isolation --no-deps` 方式接入两个固定 checkout；OpenEvolve 新增 task 的额外依赖应在注册该 task 时显式加入 lock；
5. 写入 ignored 的 `.bench-env/state.json` 并运行同一套 doctor 检查。

如果 sibling checkout 已存在但 commit 不符，脚本会停止并显示差异，不会 checkout、reset 或删除用户工作。可以传一个全新的目录：

```bash
python3 scripts/repro_env.py --checkout-root /path/to/clean/checkouts bootstrap
```

`doctor` 检查 exact commit、dirty state、Python 3.12、关键 package/entrypoint 和 Codex 最低版本。`.venv/` 是历史本机缓存，不能复制到其他机器；复现标准只有 `.bench-env/venv`。

## 先跑零模型 smoke

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method goal-plus \
  --task-id function_minimization \
  --wall-time-seconds 600 \
  --concurrency 3 \
  --seed 1
```

记录命令打印的 run directory，然后执行：

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py seed-smoke \
  --run-dir runs/openevolve-compare/<run-id>
```

这一步复用 pinned OpenEvolve evaluator，不调用模型。Goal Plus 的 project `.codex` assets 会从固定 checkout 复制到 run-local workspace，`.gp/` 也只会在该 workspace 内生成。脚本不会自动删除 run directory。

## 跑三种系统

三种方法必须分别 `prepare`，不能复用已经被另一方法修改的 workspace：

```bash
# Plain Codex
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method plain-codex --wall-time-seconds 600 --concurrency 1 --seed 1

# Goal Plus + Codex
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method goal-plus --wall-time-seconds 600 --concurrency 3 --seed 1

# Native OpenEvolve
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method openevolve --wall-time-seconds 600 --concurrency 3 --seed 1
```

Codex 方法使用已有 Codex auth，不把 user config 混入实验：

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py run \
  --run-dir runs/openevolve-compare/<run-id> \
  --model <codex-model>
```

Plain Codex 使用 ephemeral session；Goal Plus 不启用 ephemeral，因为同 worker continuation 和 usage observability 需要 Codex 的原生 session provenance。任务代码与 `.gp` 状态仍全部限制在 run-local workspace。

原生 OpenEvolve 使用 OpenAI-compatible endpoint。密钥只能放在进程环境：

```bash
export OPENAI_API_KEY='<secret>'
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py run \
  --run-dir runs/openevolve-compare/<run-id> \
  --model <api-model> \
  --api-base https://api.example.com/v1
```

run manifest 只记录 model/api base 和 credential policy，不记录任何环境变量值。

## 公平预算与停止语义

主对比固定：同一 task/seed/evaluator、总 wall deadline `T`、live search concurrency `K`。OpenEvolve 的 `iterations` 被设为很大的安全天花板；到 `T` 时外层 controller 发 `SIGTERM`，利用其原生 graceful-shutdown 保存 best，超过 grace 才 kill process group。Goal Plus 收到同一 `GOAL_PLUS_OUTER_DEADLINE_AT`，prompt 要求预留 closeout 并 drain workers；外层 deadline 仍是最终保险。

这不是 token-或 evaluator-call-matched 因果消融。主结果必须同时报告 actual evaluator calls、iterations、tokens、known cost、wall time 和 coverage。需要更严格地隔离 search strategy 时，再单独运行显式 evaluator-call cap 的 ablation；不要把这种约束写进 Goal Plus core。

任何 hard kill 都将 run 标记为 `incomplete`。这种结果可用于诊断，不能进入可比主表。

## 换机验收清单

```bash
python3 scripts/repro_env.py doctor
.bench-env/venv/bin/openevolve-run --help
.bench-env/venv/bin/goal-plus --help
python3 scripts/status.py --check
python3 -m unittest discover -s tests -v
```

最后确认：upstream checkout clean 且 commit 精确匹配；实验 workspace 位于 ignored `runs/`；`.gp` 不在 `goal-plus/`、`openevolve/` 或 benchmark 源 checkout；任何准备提交的文件都不含本机绝对 home path 或 API key。

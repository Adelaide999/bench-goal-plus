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
- Codex CLI `0.144.1+`；
- Pi Coding Agent `0.80.6+`；
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
  --method goal-plus-codex \
  --task-id function_minimization \
  --wall-time-seconds 300 \
  --concurrency 2 \
  --model gpt-5.6-luna \
  --seed 1
```

记录命令打印的 run directory，然后执行：

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py seed-smoke \
  --run-dir runs/openevolve-compare/<run-id>
```

这一步复用 pinned OpenEvolve evaluator，不调用模型。Goal Plus 的 project `.codex` assets 会从固定 checkout 复制到 run-local workspace，`.gp/` 也只会在该 workspace 内生成。脚本不会自动删除 run directory。

## 跑四条路径

四种方法必须分别 `prepare`，不能复用已经被另一方法修改的 workspace。默认主协议是 `T=300s`、`K=2`、`gpt-5.6-luna/high`：

```bash
# Plain Codex
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method plain-codex --wall-time-seconds 300 --concurrency 2 \
  --model gpt-5.6-luna --seed 1

# Goal Plus + Codex
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method goal-plus-codex --wall-time-seconds 300 --concurrency 2 \
  --model gpt-5.6-luna --seed 1

# Goal Plus + Pi
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method goal-plus-pi --wall-time-seconds 300 --concurrency 2 \
  --model gpt-5.6-luna --seed 1

# Native OpenEvolve
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method openevolve --wall-time-seconds 300 --concurrency 2 \
  --model gpt-5.6-luna --seed 1
```

四条路径都使用同一个显式 OpenAI-compatible endpoint。密钥只进入进程环境：

```bash
export OPENAI_API_KEY='<secret>'
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py run \
  --run-dir runs/openevolve-compare/<run-id> \
  --model gpt-5.6-luna \
  --api-base https://api.example.com/v1
```

Plain Codex 使用 `K` 个 ephemeral lane。Goal Plus + Codex 保留原生 session provenance；Goal Plus + Pi 写入 ignored 的 run-local `pi-home/models.json`，其中只引用 `$OPENAI_API_KEY`。Codex 的自定义 provider、Responses wire API、Goal Plus MCP 注册及 headless tool approval 全由命令行显式注入，不依赖另一台机器上的个人 `config.toml`。

run manifest 只记录 model/api base 和 credential policy，不记录任何环境变量值。

如果模型/host 已结束但 Goal Plus 的确定性 selection、promotion 或 report 被中断，可对原目录执行幂等恢复，不会启动新模型：

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py closeout \
  --run-dir runs/openevolve-compare/<run-id>
```

### 为什么 Goal Plus 在 prepare 阶段先冻结空 Search run

这套主协议比较 search stage。`prepare` 对所有方法都完成 task/config/workspace materialization；对 Goal Plus 额外完成 goal/triage、controller-owned verifier freeze 和**空** Search run 创建。它不会创建候选、调用搜索模型或产生搜索结果。候选规划、`K` 个 lineage、worker 推理和 verifier iterations 全部计入 `T`。

实测表明，如果把 Goal Plus 的通用 intake/spec discovery 也塞入五分钟窗口，高推理模型可能用掉绝大多数时间而来不及启动 worker；这种结果应作为 end-to-end overhead 诊断单列，不能与 search-stage 主表混在一起。

## 公平预算与停止语义

主对比固定：同一 task/seed/evaluator/model、总 wall deadline `T`、live search concurrency `K`。OpenEvolve 的 `iterations` 被设为很大的安全天花板；到 `T` 时外层 controller 发 `SIGTERM`，利用其原生 graceful-shutdown 保存 best，超过 grace 才 kill process group。Goal Plus 收到同一 `GOAL_PLUS_OUTER_DEADLINE_AT`；到期后 controller drain/关闭 host pool，并在 `T` 外执行确定性的最终 verifier、selection 和 promotion，和 plain lane 的最终选择同口径。closeout 用时单独记录，不算搜索时间。

这不是 token-或 evaluator-call-matched 因果消融。主结果必须同时报告 actual evaluator calls、iterations、tokens、known cost、wall time 和 coverage。需要更严格地隔离 search strategy 时，再单独运行显式 evaluator-call cap 的 ablation；不要把这种约束写进 Goal Plus core。

任何 hard kill 都将 run 标记为 `incomplete`。这种结果可用于诊断，不能进入可比主表。

## 换机验收清单

```bash
python3 scripts/repro_env.py doctor
.bench-env/venv/bin/openevolve-run --help
.bench-env/venv/bin/goal-plus --help
pi --version
python3 scripts/status.py --check
python3 -m unittest discover -s tests -v
```

最后确认：upstream checkout clean 且 commit 精确匹配；实验 workspace 位于 ignored `runs/`；`.gp` 不在 `goal-plus/`、`openevolve/` 或 benchmark 源 checkout；任何准备提交的文件都不含本机绝对 home path 或 API key。

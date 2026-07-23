# 可移植 OpenEvolve + Goal Plus 复现环境

## 目标

换到一台新的 Mac 或 Linux 主机后，只依赖本仓的 `AGENTS.md` 和固定
manifest，就能重建同一 Python runtime、同一 OpenEvolve/Goal Plus 与
benchmark 源码版本，并生成不会污染上游 checkout 的实验 workspace。

本仓只保存控制面和 lock；不 vendor 上游源码、不保存 virtualenv、不保存模型密钥。默认布局为：

```text
bench-goal-plus/
├── .tmp/                    controller、verifier、build 和子进程临时文件，Git ignored
├── .bench-env/venv/        可重建的本机 Python runtime，Git ignored
├── third_party/            所有固定 commit 的上游 checkout，Git ignored
│   ├── openevolve/
│   ├── goal-plus/
│   ├── heurigym/
│   └── ...                 其他 benchmark/search backend
└── runs/.../workspace/     每次实验的独立 Git workspace，Git ignored
```

## 主机前置条件

- Git；
- 可运行 bootstrap 脚本的 Python 3.10+；
- `uv`；
- Codex CLI `0.144.1+`；
- Pi Coding Agent `0.80.6+`；
- 能安装 CPython 3.12 wheel 的 macOS 或 Linux。

`uv` 会按需取得 Python 3.12。Docker 镜像、编译器或大型 benchmark 数据仍
由具体 benchmark 的 runbook 管理；源码 checkout 统一在 `third_party/`。

## 一键构建和检查

```bash
python3 scripts/repro_env.py bootstrap
python3 scripts/repro_env.py doctor
```

`bootstrap` 会：

1. 把当前进程和所有子进程的 `TMPDIR`、`TMP`、`TEMP` 固定到本仓 `.tmp/`，不依赖 `/tmp`、`/private/tmp` 或 `/var/tmp`；
2. 读取 `environment/upstreams.json`；
3. 在本仓 `third_party/` 克隆所有缺失的 benchmark/search runtime，并 checkout 到固定 commit；
4. 创建 `.bench-env/venv` 的 Python 3.12 环境；
5. 安装 `environment/requirements.lock`，再以 editable、`--no-build-isolation --no-deps` 方式接入 manifest 中标记为 `editable` 的 OpenEvolve/Goal Plus；benchmark 新增 task 的额外依赖应在注册该 task 时显式加入 lock；
6. 写入 ignored 的 `.bench-env/state.json` 并运行同一套 doctor 检查。

如果 checkout 已存在但 commit 不符，脚本会停止并显示差异，不会 checkout、
reset 或删除用户工作。clone 先写入精确的
`<name>_bootstrap_incomplete` staging path，成功后才重命名；失败目录会原样
保留供检查。可以传一个全新的统一目录：

```bash
python3 scripts/repro_env.py \
  --checkout-root "$HOME/.tmp/bench-goal-plus-checkouts" bootstrap
```

若当前只想跑一个 benchmark，可避免下载其余大仓库：

```bash
python3 scripts/repro_env.py bootstrap --only heurigym
python3 scripts/repro_env.py doctor --only heurigym
```

`--only` 可重复；脚本会自动追加 `always=true` 的 OpenEvolve 和 Goal Plus
runtime。无 `--only` 时才准备 manifest 中的全部上游。`doctor` 检查选中
checkout 的 exact commit/dirty state、Python 3.12、关键 package/entrypoint 和
Codex/Pi 最低版本，以及本仓 `.tmp/` 是否存在且可写。`.venv/` 是历史本机缓存，不能复制到其他机器；复现标准
是从 lock 重建 `.bench-env/venv` 与 `third_party/`。

Adapter 自己的临时编译目录也必须通过 `bench_runtime_paths.py` 创建。AutoLab、
Frontier-Engineering、HeuriGym、Frontier-CS 和 OpenEvolve worker 分别使用
`.tmp/` 下的独立 namespace。已经 prepare 的 workspace 会记录当次 checkout
中动态生成的绝对路径，因此换机器后要重新 prepare；这些路径只能指向新机器
上的仓内 `.tmp/`、`runs/`、`third_party/` 和 `.bench-env/`。

当前所有受管源码都只允许出现在这个统一根目录：

```text
third_party/{ale-bench,autolab,frontier-cs,frontier-engineering,
             heurigym,swarmresearch,swarmresearch-paper-reproduce,
             skydiscover,openevolve,goal-plus}
```

runner 不再依赖 `code/` 下的旁路 checkout。`environment/upstreams.json` 是
目录名、fork 和 commit 的唯一安装清单；出现失败的 staging checkout 时脚本
会保留 `<name>_bootstrap_incomplete`，不会删除或覆盖现有目录。
当前机器的 10 个 active checkout 已全部通过 sanitized
[`full doctor`](../evidence/environment/2026-07-23-unified-third-party-doctor.json)。

## Standalone benchmark 统一入口

ALE-Bench Lite、AutoLab、Frontier-Engineering、Frontier-CS 和 HeuriGym 共用
同一个启动形状，但各自仍调用原生 evaluator、raw metric 和方向：

```bash
.bench-env/venv/bin/python experiments/benchmark_compare/experiment.py prepare \
  --benchmark frontier-engineering-malloclab \
  --method goal-plus-codex \
  --wall-time-seconds 420 --soft-closeout-seconds 60 \
  --worker-runtime-seconds 180 --concurrency 2 --model gpt-5.6-sol

.bench-env/venv/bin/python experiments/benchmark_compare/experiment.py run \
  --run-dir runs/benchmark-compare/<run-id> --model gpt-5.6-sol
```

可选 benchmark ID 和实测预算见
[`experiments/benchmark_compare/README.md`](../experiments/benchmark_compare/README.md)。
Goal Plus 的 seed evaluation 写到 run-local `controller-runtime/`，不会在定时
启动前把 `.bench-runtime/` 带进 source/candidate Git 历史。

Frontier-CS problem 0 还需要 pinned judge image。源码 sparse checkout 已包含
完整官方 image build context；新机器执行：

```bash
docker build \
  -t bench-goal-plus/frontier-cs-judge:07500f9 \
  third_party/frontier-cs/algorithmic
```

ALE 与 Frontier-CS 的 `evaluate.py` 都需要访问 host Docker socket，因此统一
runner 会仅对这两个 adapter 显式使用 Codex `danger-full-access`，并把该选择写入
run manifest；其他 adapter 仍使用 `workspace-write`。这两个 Docker case 应只在
隔离的 benchmark 主机上运行，不能把 `workspace-write` 下的“missing image”当成
真实环境缺失。

ALE 使用官方 `ale-bench:cpp20-202301` 镜像。首次 evaluator 会构建 Rust
`gen/tester/vis`，controller 将二进制缓存到 `.bench-env/cache/ale-bench/`；
缓存和 Docker image 都是可重建主机资产，不进入 Git。

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

这一步复用 pinned OpenEvolve evaluator，不调用模型。Goal Plus 的 project `.codex` assets 会从固定 checkout 复制到 run-local workspace；prepare 完成时 `.gp/` 尚不存在，只有真正发送自然 `/goal-plus` prompt 后才会在该 workspace 内生成。脚本不会自动删除 run directory。

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

Plain Codex 使用 `K` 个 ephemeral lane。每个 lane 接收同一份 common task prompt；Goal Plus + Codex 接收该 prompt 的严格超集：只在开头增加 `/goal-plus mode=autonomous`，并在末尾附加完整的 Goal Plus 并发、host/model、metric/verifier、edit surface 和预算配置。Goal Plus + Codex 保留原生 session provenance；Goal Plus + Pi 写入 ignored 的 run-local `pi-home/models.json`，其中只引用 `$OPENAI_API_KEY`。Codex 的自定义 provider、Responses wire API、Goal Plus MCP 注册及 headless tool approval 全由命令行显式注入，不依赖另一台机器上的个人 `config.toml`。

Goal Plus 配置还明确 process-verifier 的所有权：每个 candidate worker 提交自己的最终 process result；parent 等全部 workers 返回后直接 selection，由 promotion verifier 做最终 gate。不要让 parent 在 worker closeout 同时重复 process verification，否则会制造无意义的 evaluator call，并可能与 runtime-owned `results.tsv` 提交竞争。

run manifest 只记录 model/api base 和 credential policy，不记录任何环境变量值。

如果模型/host 已结束但 Goal Plus 的确定性 selection、promotion 或 report 被中断，可对原目录执行幂等恢复，不会启动新模型：

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py closeout \
  --run-dir runs/openevolve-compare/<run-id>
```

### 为什么 Goal Plus 必须从自然 prompt 开始

这套主协议比较完整系统，而不是只比较预构建后的 search stage。`prepare` 对所有方法只完成 task/config/workspace materialization；Goal Plus 不预创建 goal、triage、frozen spec、Search run、candidate 或 session。计时开始后，Codex 收到 `/goal-plus + common task prompt + Goal Plus configuration`，由 Goal Plus 自己完成 intake、spec discovery/freeze、并发 worker 启动和最终选择。

这样 Plain Codex 与 Codex + Goal Plus 的任务正文保持一致，唯一实验干预就是 Goal Plus。Goal Plus 的控制开销也属于完整系统成本，必须计入 `T`；如果后续需要排除 intake/spec discovery 开销，应另做明确标注的 engine-only 消融，而不是改变主实验入口。

## 公平预算与停止语义

主对比固定：同一 task/seed/evaluator/model、总 wall deadline `T`、live search concurrency `K`。OpenEvolve 的 `iterations` 被设为很大的安全天花板；到 `T` 时外层 controller 发 `SIGTERM`，利用其原生 graceful-shutdown 保存 best，超过 grace 才 kill process group。Goal Plus 收到同一 `GOAL_PLUS_OUTER_DEADLINE_AT`；其自然流程可以在目标满足时提前完成，也可以运行到预算上限。模型结束或到达 `T` 后，controller 只做进程清理、幂等 closeout 和同口径 final evaluator。closeout 用时单独记录。

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

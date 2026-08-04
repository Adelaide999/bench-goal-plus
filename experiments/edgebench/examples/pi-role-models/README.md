# Pi 多角色模型 Docker 示例

这个目录展示 EdgeBench + Goal Plus + Pi 在 Docker 模式下如何为主 Agent、
Candidate Worker 和 Evidence Annotation 分别选择模型。示例使用双 provider
组合：Terra 负责 Main/Annotation，Qwen3.7-Plus 负责 Worker。它是独立配置示例，
不注册到 `benchmarks/runners.json`。

## 文件职责

- `profile.json` 选择三个角色的 `PROVIDER/MODEL`，并固定示例预算。
- `pi-models.example.json` 注册 provider、模型能力和密钥环境变量名。
- API key 只存在于启动 controller 的宿主环境中，不能写进 profile 或 registry。

省略 `worker_model` 或 `evidence_annotator_model` 时，对应角色继承顶层
`model`。reasoning effort 同样默认继承顶层配置。

## 准备宿主配置

把 registry 放到仓库外的机器本地目录，只替换两个示例 `baseUrl` 并提供对应环境
变量。示例中的 Terra 使用
`contextWindow=272000`、`maxTokens=32000`，Qwen3.7-Plus 使用
`contextWindow=1000000`、`maxTokens=131072`。只有实际换模型时才应同步修改这些
参数。`apiKey` 必须保持 `$ENV_NAME` 引用形式：

```bash
mkdir -p "$HOME/.config/bench-goal-plus"
install -m 600 \
  experiments/edgebench/examples/pi-role-models/pi-models.example.json \
  "$HOME/.config/bench-goal-plus/pi-models.json"

export SFORGE_PI_MODELS_FILE="$HOME/.config/bench-goal-plus/pi-models.json"
export OPENAI_API_KEY
export GLM_PROXY_API_KEY
```

在运行前为两个 credential 环境变量提供实际值，不要把值写入命令记录或仓库文件。
Pi 内置 provider 不需要出现在 registry 中，但仍需要导出它规定的 credential
环境变量。

## Docker 运行

从仓库根目录执行。`prepare` 冻结 profile；真正拥有 Docker 生命周期的 `run`
必须使用系统 Docker daemon。如果当前 shell 没有刷新 `docker` 组，使用
`sg docker`：

```bash
PROFILE="$PWD/experiments/edgebench/examples/pi-role-models/profile.json"
CAMPAIGN_ID="edgebench-pi-role-models-$(date +%Y%m%d-%H%M%S)"

.bench-env/venv/bin/python experiments/edgebench/experiment.py prepare \
  --profile "$PROFILE" \
  --campaign-id "$CAMPAIGN_ID"

env -u DOCKER_HOST \
  -u ALL_PROXY -u HTTP_PROXY -u HTTPS_PROXY \
  -u all_proxy -u http_proxy -u https_proxy \
  sg docker -c \
  "cd '$PWD' && .bench-env/venv/bin/python \
    experiments/edgebench/experiment.py run \
    --campaign '$CAMPAIGN_ID' --detach"
```

启动时 controller 会校验三个角色模型，只保留本次使用的 registry 条目，并为
每个仅监听宿主 loopback 的 provider 建立独立 bridge。筛选后的 registry 写入
campaign 的 `runtime/pi-models.json`，随后由 EdgeBench 写入 Work 容器的
`/home/agent/.pi/agent/models.json`。密钥只通过环境传递，不会写入这些文件。

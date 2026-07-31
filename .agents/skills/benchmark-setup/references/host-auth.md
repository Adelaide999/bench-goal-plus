# Host 与鉴权矩阵

先确定三个独立维度，再执行 setup：

1. benchmark/runner；
2. host：macOS 或 Linux；
3. agent/provider：Codex OAuth、OpenAI-compatible API、Pi 或
   Anthropic-compatible API。

这些组合的依赖和网络路径不同。不要把一种组合的 doctor 结果外推到另一种组合。

## Host 差异

| 项目 | macOS | Linux |
| --- | --- | --- |
| Docker | Docker Desktop 或 OrbStack | 原生 Docker Engine |
| EdgeBench 容器架构 | Docker VM 必须提供 `linux/amd64` | daemon 必须是 `amd64/x86_64` |
| 宿主 Judge | Work container 通过 `host.docker.internal` 访问 | controller 使用 host route + systemd socket bridge |
| 宿主 loopback API | 当前 EdgeBench controller 不支持把 `127.0.0.1` API 从 Mac 桥入容器；使用容器可达的非 loopback URL | 需要 `ip`、`systemd-socket-activate` 和 `systemd-socket-proxyd` |
| `internet=false` | Docker VM 通常不能满足 SForge 的 host `iptables` gate；只能使用 profile 明确声明的 open-network smoke | 需要 SForge 可使用 passwordless `sudo iptables` 完成 allowlist |
| Codex container runtime | 需要 Linux x64 Codex runtime cache | 同样需要 Linux x64 Codex runtime cache |

两种 host 都必须通过 benchmark-native doctor。macOS 能跑 local smoke 不等于官方
offline/network-isolated protocol 已满足；正式 Linux 运行也不能跳过 bridge、resource limit
和 `iptables` 检查。

## 鉴权方式

| 路径 | 支持的鉴权 | 配置来源 | 重要限制 |
| --- | --- | --- | --- |
| EdgeBench Plain/Goal Plus Codex | Codex OAuth 或 OpenAI-compatible API | OAuth auth file，或 `SFORGE_AGENT_*` / `OPENAI_*` env | custom loopback API 只在具备 Linux bridge 时可用 |
| EdgeBench Plain/Goal Plus Pi | Pi 的 `openai-codex` 登录 | `SFORGE_PI_AUTH_FILE` 或 `~/.pi/agent/auth.json` | 当前 EdgeBench Pi runner 不接受通用 direct-API provider |
| EdgeBench Claude | Anthropic-compatible API | `SFORGE_AGENT_*` 或 `ANTHROPIC_*` env | key 和 base URL 都必需 |
| Common/OpenEvolve 的 Codex 路径 | Codex native login，或显式 OpenAI-compatible endpoint | 省略 `--api-base` 使用 native login；显式 endpoint 使用 `OPENAI_API_KEY` | custom provider 使用 Responses wire API |
| Common/OpenEvolve 的 Pi、native OpenEvolve、SkyDiscover | OpenAI-compatible API | `--api-base` + `OPENAI_API_KEY` | 不是 Codex OAuth 路径 |

### Codex OAuth

EdgeBench 查找顺序：

1. `SFORGE_CODEX_AUTH_FILE`；
2. `$CODEX_HOME/auth.json`；
3. 默认 `~/.codex/auth.json`。

OAuth 模式不需要把 token 复制进 profile 或环境变量。doctor 只记录 auth 文件路径和模式，
不记录内容。EdgeBench 还要求：

```text
~/.cache/sforge/codex/codex-0.144.1-linux-x64.tgz
```

该缓存是 Work container 使用的 Linux Codex runtime，不是当前 Mac/Linux host 的 Codex
可执行文件本身。

### EdgeBench OpenAI-compatible API

Key 的优先级：

1. `SFORGE_AGENT_API_KEY`
2. `OPENAI_API_KEY`
3. `CODEX_API_KEY`

Base URL 的优先级：

1. `SFORGE_AGENT_API_BASE_URL`
2. `OPENAI_BASE_URL`

自定义 endpoint 应同时设置 key 和 base URL：

```bash
export SFORGE_AGENT_API_KEY='<secret>'
export SFORGE_AGENT_API_BASE_URL='https://api.example.com/v1'
```

controller 会从 host 和 Work container 各做一次鉴权 probe。manifest 只记录使用了哪个环境
变量，不记录值。

### EdgeBench Pi OAuth

auth JSON 必须包含 `openai-codex` entry：

```bash
export SFORGE_PI_AUTH_FILE=/path/to/pi-auth.json
```

未设置时使用 `~/.pi/agent/auth.json`。Plain Pi 与 Goal Plus + Pi 都使用这条路径；
不能把 common/OpenEvolve 的 Pi direct-API 配置照搬到 EdgeBench。

### Anthropic-compatible API

Key 的优先级：

1. `SFORGE_AGENT_API_KEY`
2. `ANTHROPIC_AUTH_TOKEN`
3. `ANTHROPIC_API_KEY`

Base URL 的优先级：

1. `SFORGE_AGENT_API_BASE_URL`
2. `ANTHROPIC_BASE_URL`

EdgeBench Claude campaign 要求 key 与 base URL 同时存在，并在 host 和 container
完成协议匹配的 probe。

## Setup 顺序

```bash
python3 scripts/bench.py catalog
python3 scripts/bench.py setup --preset <preset>
python3 scripts/bench.py plan --preset <preset>
```

`setup` 根据 target 执行 bootstrap、doctor 和已登记的 provision。不要在 Skill 中手工复制
平台判断；实际 gate 以 `benchmarks/registry.json`、`benchmarks/runners.json`、
`environment/upstreams.json` 和 runner doctor 为准。

## Secret 边界

- Secret 只存在于继承环境或 host auth store。
- 不把 key、token、cookie、auth JSON 或 provider header 写入仓库。
- 不把 secret-bearing shell 命令保存进 evidence。
- 报告可以记录 auth mode、provider protocol 和变量名，但不能记录变量值。

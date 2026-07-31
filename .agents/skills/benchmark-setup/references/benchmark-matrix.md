# Benchmark 环境矩阵

始终重新读取 `benchmarks/registry.json` 和 `environment/upstreams.json`；本表只负责
benchmark 依赖和命令路由。macOS/Linux、OAuth/direct API、agent/provider 的差异必须另读
[Host 与鉴权矩阵](host-auth.md)。

| Benchmark | `bootstrap --only` key | Docker | 额外入口 |
|---|---|---|---|
| EdgeBench | `edgebench` | required | `experiment.py provision/doctor --profile ...` |
| ALE-Bench lite | `ale_bench` | required | 官方 lite C++/judge images |
| HeuriGym | `heurigym` | not required | pinned Python + dataset bootstrap |
| Frontier Engineering lite | `frontier_engineering` | not required | host C compiler + `make` for MallocLab |
| AutoLab CPU | `autolab` | mixed | toy ISA needs host C compiler + `make`; paper path needs containers |
| SwarmResearch | `swarmresearch`, `swarmresearch_tasks` | required | paper-compatible container path |
| Frontier-CS | `frontier_cs` | required | eager adapter hook builds the pinned judge image and creates its preserved container |
| SkyDiscover/EvoX | `skydiscover` | mixed | only registry-approved host/image subset |
| OpenEvolve examples | `openevolve` | not required | `cpu_portable` locked NumPy/SciPy set |
| PerfOpt-Bench | none | unavailable | no executable public artifact; do not claim runnable |

## Global gate

```bash
git --version
python3 --version
uv --version
```

再按实际 method 检查 agent runtime：Codex 路径运行 `codex --version`，Pi 路径运行
`pi --version`。未选中的 agent 只能是 diagnostic。Only run `docker info` as a required
gate for `required`/relevant `mixed` paths.

## Mirrors and pinned assets

- Reuse repository code for mirrors. EdgeBench Rust assets try rsproxy, SJTU, then official and verify the official SHA256.
- EdgeBench task containers keep exact work/judge image tags. A Docker daemon mirror may accelerate identical layers, but do not retag a different image as the pinned tag.
- The control plane currently relies on benchmark-native provisioning or an already-present exact image. It does not retry Docker Hub through a hard-coded mirror; add future transport support behind the registered runner/adapter provision hook.
- SForge child environments default Node.js/npm downloads to `npmmirror.com`; task network policy still comes from the official protocol.
- Record which source succeeded when evidence depends on a downloaded asset. Never record authorization headers.

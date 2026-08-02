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

- Mandatory local-first gate: before setup or any command that can fetch task data or pull/build an
  image, confirm the selected target or asset pack reports `assets=True`, then run the unified
  profiled check, for example:

  ```bash
  python3 scripts/bench.py check \
    --benchmark edgebench --profile vliw-smoke
  ```

  A preset with a frozen profile can use `check --preset <preset>`. The output records task-file
  presence, actual/expected dataset revision, exact Work/Judge references, present/missing state,
  image ID, repo tags/digests, size, architecture, and existing containers using each image. It also
  emits `read_only: true` and `acquisition_attempted: false`.
- Inventory belongs to the selected target, not its shared runner. Frontier-CS and ALE-Bench can
  therefore expose adapter-owned checks while host-only targets on `common-matrix` remain rejected.
- SkyDiscover's reviewed CPU evaluator set is an asset pack, not a benchmark target:

  ```bash
  python3 scripts/bench.py check \
    --asset-pack skydiscover-cpu-evaluators --profile cpu-no-torch-19
  python3 scripts/bench.py setup \
    --asset-pack skydiscover-cpu-evaluators --profile cpu-no-torch-19 \
    --skip-provision
  ```

  Its 19 local `:latest` tags are not published registry references. After the inventory reports
  exact missing tags and acquisition is explicitly requested, setup without `--skip-provision`
  builds the pinned upstream evaluator contexts, labels their revision/source tree, and reuses
  shared Docker layers. The profile also freezes the Linux/amd64 `python:3.12-slim` manifest and
  image ID. If that base is absent, provision transports the same pinned manifest through the
  first working registered mirror and verifies its image ID; it does not probe with `docker pull`.
  The generated build-only Dockerfile keeps the upstream instructions and adds only an
  `ARG PIP_INDEX_URL`; the selected index is frozen in the profile and image provenance label.
  Conflicting tags are retained with a `_bak` tag before replacement.
- The profiled check is guaranteed not to run `provision`, `fetch-tasks`, pull, build, `docker run`,
  or credential probes. Its only Docker commands are `docker image inspect <exact-ref>` and one
  `docker ps -a --no-trunc --format '{{json .}}'`. A failed check only reports local gaps.
- The explicit aggregate environment check preserves that ordering across every registered asset
  owner:

  ```bash
  python3 scripts/bench.py check --environment
  ```

  It runs each target's declared `default_inventory_profile` and every asset pack's default profile
  before querying the registered Git branches with `git ls-remote`. In a TTY it lists changed
  repositories and asks once before running the existing fast-forward-only bootstrap. In automation,
  it reports updates without mutating anything unless `--yes` is explicit. Dirty, wrong-origin,
  wrong-branch, divergent, or failed remote checks remain blocking; no image or dataset provision is
  part of this command.
- After inventory, run the managed bootstrap and full doctor without provisioning:

  ```bash
  python3 scripts/bench.py setup \
    --benchmark edgebench --profile vliw-smoke --skip-provision
  ```

  If all required checks pass, stop and do not run `provision`, `fetch-tasks`, `sforge pull`, or
  `docker pull`.
- EdgeBench `provision` is not a read-only/local-cache probe. It first contacts HuggingFace through
  `fetch-tasks`; its current SForge `pull` path then contacts the registry for Work and Judge images
  even when those local tags already exist. Run it only for doctor-reported missing/stale assets and
  only when network acquisition was requested or confirmed. Report the exact missing task,
  revision, or image tags before doing so.
- Reuse repository code for mirrors. EdgeBench Rust assets try rsproxy, SJTU, then official and verify the official SHA256.
- EdgeBench task containers keep exact work/judge image tags. A Docker daemon mirror may accelerate identical layers, but do not retag a different image as the pinned tag.
- The control plane currently relies on benchmark-native provisioning or an already-present exact image. It does not retry Docker Hub through a hard-coded mirror; add future transport support behind the registered runner/adapter provision hook.
- SForge child environments default Node.js/npm downloads to `npmmirror.com`; task network policy still comes from the official protocol.
- Record which source succeeded when evidence depends on a downloaded asset. Never record authorization headers.

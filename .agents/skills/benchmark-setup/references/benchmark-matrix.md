# Benchmark 环境矩阵

始终重新读取 `benchmarks/registry.json` 和 `environment/upstreams.json`；本表只负责
benchmark 依赖和命令路由。macOS/Linux、OAuth/direct API、agent/provider 的差异必须另读
[Host 与鉴权矩阵](host-auth.md)。

| Benchmark | `bootstrap --only` key | Docker | 额外入口 |
|---|---|---|---|
| EdgeBench | `edgebench` | required | `experiment.py provision/doctor --profile ...` |
| SWE-bench Verified | `swebench` | required | exact task image, repository-local Hugging Face cache, official harness |
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

## SWE-bench Verified on a shared Linux host

Keep every mutable benchmark path below the bench-goal-plus checkout. From the repository root,
route both the generic cache and Hugging Face cache explicitly before setup, plan, or launch:

```bash
export XDG_CACHE_HOME="$PWD/.tmp/xdg-cache"
export HF_HOME="$PWD/.tmp/huggingface"
```

The target's profiled `check` inspects only the pinned task metadata, exact local image tag and image
ID. It must not contact Hugging Face or start a container. The full doctor may start short-lived
diagnostic containers, always with `--pull never`; it must not pull, build, tag, commit, or remove an
image.

The official task image can have a synthetic build commit above the dataset's `base_commit`.
Do not rewrite the profile to the image's current HEAD and do not modify the image. The full doctor
must prove that `base_commit^{tree}` and `HEAD^{tree}` are identical; the Agent container can then be
reset to the official dataset base while the immutable image remains untouched. A tree mismatch is a
blocking asset/version error.

The complete dataset row is loaded host-side during `prepare`, not during the read-only inventory
gate. On hosts where `huggingface.co` is unreachable, use a transport-only mirror while retaining the
exact registered revision:

```bash
export HF_ENDPOINT=https://hf-mirror.com
python3 scripts/bench.py launch --preset <swe-bench-preset> \
  --campaign-id <planned-id> --skip-bootstrap --skip-provision
```

Before launch, verify the mirror response reports the registered commit. A failed `prepare` occurs
before any model or evaluator call; preserve its campaign path according to the normal `_bak` rule.
After the exact revision is cached under `$HF_HOME`, later runs can prevent all Hub access:

```bash
export HF_HUB_OFFLINE=1
export HF_DATASETS_OFFLINE=1
```

Python installation still uses the repository lock. If the default Python index is unavailable, a
domestic index may accelerate the same locked artifacts, for example by setting
`PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` for the unified `setup` command. It must not
change the requirements lock, dataset revision, task image tag/ID, or SWE-bench checkout commit.

The current target has external image provisioning. If the exact task image is absent, report the
missing tag and stop; do not automatically pull, retag a substitute, or mutate another user's image.
The Codex runtime archive and Pi Node/package installations may be mounted read-only from the selected
host environment. SWE Plain Codex does not mount OAuth: its profile freezes `OPENAI_BASE_URL`,
`OPENAI_API_KEY`, and Responses. When the base URL is loopback, the Linux host must provide `ip`
(`iproute2`/`iproute`) plus `systemd-socket-activate` and `systemd-socket-proxyd` (`systemd`); use the
distribution packages documented in `host-auth.md`. Doctor must verify host and task-container
`POST /responses` for the exact model. A `chatgpt.com` request is a fail-closed provider-routing error.
Credential values are never copied into the repository, command line, manifest, or report; all
campaign output, evaluator logs, dataset cache, and temporary files remain repository-local.

The pinned Codex `0.144.1` Linux archive expands to roughly 352 MB. Both full doctor and the Agent
container must extract it into the same bounded `/opt/codex` tmpfs (currently 512 MB). If extraction
reports `No space left on device`, this is a runner/runtime-capacity failure: confirm the archive's
expanded size, increase the bounded runtime tmpfs with a contract test, archive the failed campaign
with evaluator calls still at zero, and generate a new campaign ID. Do not resize Docker globally,
rewrite the task image, or rerun a terminal campaign in place.
Because the Codex binary executes from this mount, `/opt/codex` must explicitly allow `exec` while
remaining `nosuid,nodev`; otherwise full doctor must fail with `Permission denied`. Other task tmpfs
mounts do not inherit this exception.

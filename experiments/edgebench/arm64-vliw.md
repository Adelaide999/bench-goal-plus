# Local ARM64 VLIW Images

These images reconstruct the pinned EdgeBench VLIW Work and Judge task files on
native ARM64 Python 3.11.15. They are local experimental images, distinct from
the official `linux/amd64` image tags. No Agent run or official matched campaign
is implied by the image checks below.

| Role | Local image | Image ID prefix |
| --- | --- | --- |
| Work | `edgebench-arm64-local.work.vliw_kernel_optimization:9fa380a0ebef` | `af44629a81dc` |
| Judge | `edgebench-arm64-local.judge.vliw_kernel_optimization:5cdef0021634` | `252d0f154267` |

The dataset revision is `47846a4c3669ad447e0ea984833b0d352460c5f9`.
Its task has no setup scripts, so the original task directories are extracted
from stopped x86 containers. No x86 executable or site-packages directory is
copied. The task imports only the Python standard library. Work retains its
public cases and Git baseline; Judge retains its original tests. Hidden Judge
files never enter the Work image.

## Rebuild

Use a fresh repository-local build directory. Existing images can be inspected
and reused; preserve an existing conflicting local tag before rebuilding.
The Dockerfile is [docker/edgebench-vliw-arm64.Dockerfile](../../docker/edgebench-vliw-arm64.Dockerfile).

```bash
mkdir -p .tmp
BUILD_CONTEXT=$(mktemp -d "$PWD/.tmp/vliw-arm64.XXXXXX")
WORK_SOURCE=seededge/edgebench.work.vliw_kernel_optimization@sha256:f4e9334beef8b304fd942b44ad3ec6a01c7369c305d5afc8b394075d0aff3b58
JUDGE_SOURCE=seededge/edgebench.judge.vliw_kernel_optimization@sha256:3aa13f35dc05dcf33df7cad2c8c21908f02d8d72dde80857286397cfd984b2f9
docker pull --platform linux/amd64 "$WORK_SOURCE"
docker pull --platform linux/amd64 "$JUDGE_SOURCE"
WORK_CONTAINER=$(docker create --platform linux/amd64 "$WORK_SOURCE")
JUDGE_CONTAINER=$(docker create --platform linux/amd64 "$JUDGE_SOURCE")
docker cp "$WORK_CONTAINER:/home/workspace/sebench_performance_takehome" "$BUILD_CONTEXT/work"
docker cp "$JUDGE_CONTAINER:/home/workspace/sebench_performance_takehome" "$BUILD_CONTEXT/judge"
docker rm "$WORK_CONTAINER" "$JUDGE_CONTAINER"
docker build --platform linux/arm64 --target work \
  -t edgebench-arm64-local.work.vliw_kernel_optimization:9fa380a0ebef \
  -f docker/edgebench-vliw-arm64.Dockerfile "$BUILD_CONTEXT"
docker build --platform linux/arm64 --target judge \
  -t edgebench-arm64-local.judge.vliw_kernel_optimization:5cdef0021634 \
  -f docker/edgebench-vliw-arm64.Dockerfile "$BUILD_CONTEXT"
```

## Verified Behavior

The 2026-09-07 build ran on a Linux aarch64 Docker host:

- Both images report `aarch64` and Python `3.11.15`.
- SHA256 comparisons match all extracted source files: Work 49, Judge 9.
- Work contains no `test_cases/hidden_cases.json`.
- The original Work solution passes all 4 public cases.
- The same solution, mounted read-only into Judge, passes the unchanged task
  `judge.eval_cmd`: 9/9 cases, `valid=true`, `score_cycles=147734`.
- The score is simulator cycles, not CPU wall time. No native x86 comparison
  was run: this host has no x86 emulation and reports `exec format error`.

The [verification record](../../evidence/environment/2026-09-07-vliw-arm64.json)
contains image identities and check results. Local build logs, test output, and
the full file-hash manifest are retained under `.tmp/vliw-arm64-build/`.

The Work image was rebuilt on 2026-09-08 to fix task-root ownership. `WORKDIR`
had created the destination as root; `COPY --chown` assigned ownership to its
contents without changing that existing directory. Work now explicitly owns
the task root as `agent:agent`. A build step running as `agent` must create a
temporary file and directory there. The rebuilt image also passed an independent
write probe and the unchanged 4/4 public baseline at 147734 cycles. Judge is
unchanged. The original Work image remains available as
`edgebench-arm64-local.work.vliw_kernel_optimization:9fa380a0ebef_bak_root-owner_20260908`;
the dated verification record above describes that original image. Rebuild and
comparison evidence is retained under `.tmp/vliw-image-comparison-20260908/`.

For a quick repeat of the public test:

```bash
docker run --pull never --rm --platform linux/arm64 --network none \
  edgebench-arm64-local.work.vliw_kernel_optimization:9fa380a0ebef \
  python runner.py --solution solution.py --cases test_cases/public_cases.json \
  --output /tmp/vliw-public-report.json
```

## Runner Boundary

The original profiles and dataset remain `linux/amd64`. The experimental
[Pi profile](profiles/vliw-goal-plus-pi-sol-low-arm64-30m.json) explicitly selects
`linux/arm64` and a local `task_assets_dir`. That directory contains a copy of
the pinned task with only `platform` changed, plus `BENCHMARK.yaml` with
`name: edgebench-arm64-local`. Prepare copies it into the campaign. The native
doctor checks the selected task, both images, Docker architecture, resource
limits, provider tool roundtrip, and API-only network isolation. Use the normal
`check`, `plan`, and `launch --skip-bootstrap --skip-provision` lifecycle.

Pi Node installation selects the native architecture. Goal Plus is installed
through `install.sh --pi` in a container-local Python environment, and Pi loads
the registered package for both start and resume. Controller-provided source
ownership is transferred to the container user and checked before installation.
The Pi adapter fails if that source is unreadable; it cannot download another
branch in its place.

For an isolated local EdgeBench snapshot, `SFORGE_EDGEBENCH_SOURCE_DIR` selects
the checkout and `PYTHONPATH` must select the same SForge code. Goal Plus uses
`SFORGE_GOAL_PLUS_SOURCE_DIR` and `SFORGE_GOAL_PLUS_EXPECTED_REF`. Native doctor
validates these actual checkouts; the global managed-environment doctor remains
available independently. No managed tracking branch needs to change.

On a Linux host without passwordless sudo, an explicitly selected
`SFORGE_IPTABLES_HELPER_IMAGE` can execute the same host iptables operations
through a root, privileged Docker container with `nsenter`. The helper must
already exist locally; every invocation uses `--pull never`. This authority is
only used by the controller, and the task container remains unprivileged with
Judge and exact LLM endpoint rules. ARM support is currently restricted to Pi
and this VLIW task; a completed model campaign requires its own evidence.

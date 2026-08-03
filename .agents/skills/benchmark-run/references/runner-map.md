# Runner map

可执行映射以 `benchmarks/runners.json` 为准；本页只解释选择逻辑，不重复维护 target 清单。

| Workload | Controller | Lifecycle |
|---|---|---|
| Native profile benchmark | benchmark-owned controller | `provision`, `doctor`, `prepare`, `run`, `status`, `stop`, `finalize` as declared |
| SWE-EVO native repository benchmark | `experiments/swe_evo/experiment.py` | SForge worker/process judge, patch freeze, then SWE-EVO official final judge |
| Standalone artifact task | `experiments/benchmark_compare/experiment.py` | low-level `prepare`, `run`; normally reached through matrix controller |
| Benchmark x condition x seed matrix | `experiments/benchmark_campaign/experiment.py` | `list`, `prepare`, `run`, `status`, `summarize` |
| OpenEvolve examples | `experiments/openevolve_compare/experiment.py` | single/batch prepare, run, report |
| HeuriGym compatibility | `experiments/heurigym_compare/experiment.py` | forwards to common standalone implementation |

用 dispatcher 构造已登记命令；修改 contract 或接入新 runner kind 时才直接检查 controller 的 README
和 `--help`。hidden judge、service/container lifecycle、browser state 或 specialized scheduling
继续由 native controller 持有。

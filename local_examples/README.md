# Local examples

这个目录保存可以直接在 host 上运行、适合快速比较搜索方法的固定任务副本。
它们不是新的正式 benchmark，也不替代上游的官方评分路径。

| ID | 来源 | Docker | Artifact | Metric | 用途 |
|---|---|---|---|---|---|
| `local-vliw` | EdgeBench VLIW work/judge images | 不需要 | `solution.py` | `cycles` minimize | Plain Codex / Goal Plus 快速机制实验，后续可复用给 OpenEvolve、EvoX |

所有方法必须通过 controller materialize 独立 workspace，并复用同一 public /
held-out evaluator。`controller/` 只对控制面可见；如果 agent 拥有整个宿主文件
系统的读取权，held-out cases 不再具备严格保密性，因此结果必须标为
`local_example`，不能写成官方 EdgeBench 分数。

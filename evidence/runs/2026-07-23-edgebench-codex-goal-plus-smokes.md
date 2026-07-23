# EdgeBench Codex / Goal Plus 接线证据

任务固定为 `vliw_kernel_optimization`，数据固定到 HuggingFace revision
`47846a4c3669ad447e0ea984833b0d352460c5f9`。官方 SForge 同时拥有 work
container、hidden judge、自动评测和 final archive；`bench-goal-plus` 只负责任务
版本、运行协议、进程生命周期和汇总。

已有两条真实模型路径：

| 方法 | 模型 | T | K | 最佳 raw cycles | EdgeBench 0-100 | 评测轮次 |
|---|---|---:|---:|---:|---:|---:|
| Plain Codex | `gpt-5.5` | 180s | 1 | 4941 | 0.0 | 3 |
| Goal Plus + Codex | `gpt-5.6-terra/high` | 3600s | 3 | 1878 | 57.9476 | 16 |

这两轮只能证明两条 agent 路径、hidden judge、promotion bridge 和 artifact
保存真实可用。模型、T、K 都不同，不能把分数差解释成 Goal Plus 的效果。

控制面随后完成了以下验收：

- 从 `environment/upstreams.json` clone 并 editable install 固定 EdgeBench fork；
- 按固定 dataset revision 获取 51 个公开任务定义；
- 只拉取 VLIW 一题的 work/judge 镜像；
- `doctor` 验证 exact commits、Codex auth policy、Docker `linux/amd64`、任务
  revision 和两张镜像；
- `prepare` 同时生成 Plain Codex 的 K 条独立 replica 与 Goal Plus 的单 outer
  run + K 个 internal workers；
- `status`、`stop`、`finalize` 均以 campaign 目录为边界，不清理任何中间产物。

## 统一 control-plane 的真实 E2E

`edgebench-control-e2e-v4-20260723` 又用完全相同的
`gpt-5.6-terra/high`、`T=120s`、`K=1` 跑完两个 cell。controller 自己启动并
关闭 judge，两个 SForge cell 都按时 closeout，`finalize` 从归档中恢复了
evaluator 与 Codex usage：

| 方法 | raw cycles | evaluator calls | runtime | Codex input/output | 归档 session |
|---|---:|---:|---:|---:|---:|
| Plain Codex | 147734 | 1 | 120.1s | 30,289 / 232 | 1 |
| Goal Plus + Codex | 147734 | 2 | 120.1s | 495,196 / 2,375 | 1 |

这轮证明 `prepare → detached run → live status → timeout closeout → judge close →
finalize` 是一条真实模型闭环，同时证明累计 token 不能从 Codex rollout
`token_count` 逐条相加，必须按 session 取最后一条累计值。

`T=120s` 只够 Goal Plus main session 完成 Goal、triage、frozen spec 和 Search
run 创建，尚未 dispatch candidate worker；因此相同 seed 分数不是 Goal Plus
搜索效果证据。上面的 1 小时旧 run 已证明 K=3 worker/promotion 路径真实可用。
下一步使用 `T>=300s,K>=2` 做短 matched pilot，再冻结 8–12 题 Linux profile。

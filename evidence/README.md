# Evidence policy

- `legacy-smokes/`：迁自旧目录的小型历史摘要，只证明当时的环境/verifier 状态。
- `runs/<date>-<benchmark>-<method>/`：可提交的单次运行证据，至少含 summary、候选 artifact、官方 evaluator payload 与 agent run manifest。
- 仓库根 `/runs/`：完整原始运行目录，默认 gitignored；确认不含凭据后，只把支撑状态门禁所需的最小证据提升到这里。

状态 registry 中的 `pass` 必须指向本目录下真实存在的文件。对搜索策略实验，还必须保存 evaluator-call ledger 与候选父子关系；单次最终分数不足以证明方法效果。

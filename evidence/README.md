# Evidence policy

- `legacy-smokes/`：迁自旧目录的历史摘要、确定性结果和经过隐私清理的必要 checkpoint；完整迁移映射见 `docs/legacy-smoke-migration.md`。
- `environment/`：不含凭据和本机身份的环境、镜像 digest/大小、代表 case 确定性输出。
- `runs/<date>-<benchmark>-<method>/`：可提交的单次运行证据，至少含 summary、候选 artifact、官方 evaluator payload 与 agent run manifest。
- 仓库根 `/runs/`：完整原始运行目录，默认 gitignored；确认不含凭据后，只把支撑状态门禁所需的最小证据提升到这里。

状态 registry 中的 `pass` 必须指向本目录下真实存在的文件。对搜索策略实验，还必须保存 evaluator-call ledger 与候选父子关系；单次最终分数不足以证明方法效果。

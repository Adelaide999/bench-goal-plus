import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs" / "benchmarks"
BENCHMARK_DOCS = (
    "ale-bench-lite.md",
    "heurigym.md",
    "frontier-engineering-v1-lite.md",
    "autolab-cpu.md",
    "swarmresearch-15.md",
    "frontier-cs-algorithmic.md",
    "edgebench.md",
)
REQUIRED_CASE_SECTIONS = (
    "## 30 秒理解",
    "### 输入是什么",
    "### Agent 要做什么",
    "### 期待输出是什么",
    "### Verifier 如何评分",
    "## 实验怎么用",
    "## 可复用对比数据",
    "## 代码与证据",
)


class BenchmarkDocsTest(unittest.TestCase):
    def test_overview_links_every_active_benchmark(self):
        overview = (DOCS_DIR / "README.md").read_text(encoding="utf-8")
        for filename in BENCHMARK_DOCS:
            with self.subTest(filename=filename):
                self.assertIn(f"]({filename})", overview)

    def test_each_benchmark_explains_one_case_contract(self):
        for filename in BENCHMARK_DOCS:
            text = (DOCS_DIR / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn("## 代表 case：", text)
                for heading in REQUIRED_CASE_SECTIONS:
                    self.assertIn(heading, text)

    def test_local_markdown_links_resolve(self):
        markdown_files = (
            [DOCS_DIR / "README.md"]
            + [DOCS_DIR / filename for filename in BENCHMARK_DOCS]
            + [
                ROOT / "docs" / "goal-plus-benchmark-experiment.md",
                ROOT / "docs" / "openevolve-cpu-examples.md",
                ROOT / "docs" / "reproducible-environment.md",
            ]
        )
        link_pattern = re.compile(r"\[[^]]+\]\(([^)]+)\)")
        for markdown_file in markdown_files:
            text = markdown_file.read_text(encoding="utf-8")
            for target in link_pattern.findall(text):
                if target.startswith(("https://", "http://", "#")):
                    continue
                resolved = (markdown_file.parent / target).resolve()
                with self.subTest(file=markdown_file.name, target=target):
                    self.assertTrue(resolved.exists(), str(resolved))

    def test_docs_do_not_contain_local_identity_or_api_keys(self):
        extra_docs = [
            ROOT / "docs" / "goal-plus-benchmark-experiment.md",
            ROOT / "docs" / "openevolve-cpu-examples.md",
            ROOT / "docs" / "reproducible-environment.md",
        ]
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [DOCS_DIR / "README.md"]
            + [DOCS_DIR / filename for filename in BENCHMARK_DOCS]
            + extra_docs
        )
        self.assertNotRegex(combined, r"/Users/[^/\s]+")
        self.assertNotRegex(combined, r"\bsk-[A-Za-z0-9_-]{16,}\b")

    def test_experiment_protocol_covers_non_pass_at_k_claim(self):
        protocol = (ROOT / "docs" / "goal-plus-benchmark-experiment.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "Agent 并发",
            "Evaluator 并发",
            "Task 并发",
            "Independent Parallel",
            "OpenEvolve",
            "best-score AUC",
            "cross-lineage transfer",
        ):
            with self.subTest(required=required):
                self.assertIn(required, protocol)

    def test_protocol_has_every_active_benchmark(self):
        protocol = (ROOT / "docs" / "goal-plus-benchmark-experiment.md").read_text(
            encoding="utf-8"
        )
        for benchmark_name in (
            "ALE-Bench Lite",
            "HeuriGym",
            "Frontier-Engineering v1-lite",
            "AutoLab CPU subset",
            "SwarmResearch 15",
            "Frontier-CS Algorithmic",
            "EdgeBench open-source subset",
        ):
            with self.subTest(benchmark=benchmark_name):
                self.assertIn(f"### {benchmark_name}", protocol)

    def test_protocol_has_codex_integration_matrix(self):
        protocol = (ROOT / "docs" / "goal-plus-benchmark-experiment.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "## Codex 接入整改总表",
            "Plain Codex 当前证据",
            "Goal Plus + Codex 当前状态",
            "benchmark / fork 要改什么",
            "`bench-goal-plus` 要新增什么",
            "`goal-plus` core 要改什么",
            "OpenEvolve CPU examples（任务包 + 原生基线）",
            "ALE、HeuriGym、AutoLab、Frontier-Engineering",
            "Frontier-CS 与 EdgeBench 已各有至少一题的 Plain / Goal Plus 真实路径证据",
        ):
            with self.subTest(required=required):
                self.assertIn(required, protocol)

    def test_openevolve_tasks_are_separate_from_search_runners(self):
        audit = (ROOT / "docs" / "openevolve-cpu-examples.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "共同 task/evaluator substrate",
            "四套独立入口",
            "原生 OpenEvolve",
            "Plain Codex",
            "Goal Plus",
            "不需要增加 Codex provider",
            "通用 `openevolve_task` adapter",
        ):
            with self.subTest(required=required):
                self.assertIn(required, audit)
        self.assertNotIn("固定 fork 需增加 `codex_cli` provider", audit)


if __name__ == "__main__":
    unittest.main()

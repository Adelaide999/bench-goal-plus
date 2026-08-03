from __future__ import annotations

import copy
import unittest

from benchmarks.datasets import (
    list_datasets,
    load_catalog,
    resolve_panel,
    validate_catalog,
)


class DatasetCatalogTest(unittest.TestCase):
    def test_catalog_registers_scenario_datasets(self) -> None:
        catalog = load_catalog()
        self.assertEqual(validate_catalog(catalog), [])
        self.assertEqual(
            {dataset["id"] for dataset in catalog["datasets"]},
            {
                "cybench",
                "cybergym",
                "roadmapbench",
                "swe-bench-pro-clean",
                "swe-bench-verified",
                "swe-evo",
                "webarena",
                "workarena-l1",
            },
        )

    def test_stage_and_domain_filters_preserve_recommended_software_sets(self) -> None:
        selected = list_datasets(domain="software", stage=1)
        self.assertEqual(
            {dataset["id"] for dataset in selected},
            {"swe-bench-pro-clean", "swe-bench-verified", "swe-evo"},
        )

    def test_cybergym_official_smoke_panel_has_published_task_ids(self) -> None:
        panel = resolve_panel("cybergym", "official-smoke-10")
        self.assertEqual(panel["status"], "upstream_defined")
        self.assertEqual(len(panel["task_ids"]), 10)
        self.assertIn("arvo:47101", panel["task_ids"])
        self.assertIn("oss-fuzz:385167047", panel["task_ids"])

    def test_swe_evo_has_pinned_ghcr_smoke_without_freezing_development_panel(self) -> None:
        smoke = resolve_panel("swe-evo", "ghcr-smoke-2")
        development = resolve_panel("swe-evo", "development-12")
        self.assertEqual(smoke["status"], "frozen")
        self.assertEqual(len(smoke["task_ids"]), 2)
        self.assertEqual(development["status"], "selection_pending")
        self.assertEqual(development["task_ids"], [])

    def test_frozen_panel_requires_revision_and_explicit_tasks(self) -> None:
        catalog = copy.deepcopy(load_catalog())
        dataset = next(
            item for item in catalog["datasets"] if item["id"] == "swe-evo"
        )
        dataset["source"]["revision"] = None
        panel = next(item for item in dataset["panels"] if item["id"] == "development-12")
        panel["status"] = "frozen"
        errors = validate_catalog(catalog)
        self.assertTrue(any("source.revision" in error for error in errors))
        self.assertTrue(any("explicit task_ids" in error for error in errors))

    def test_explicit_task_count_must_match_panel_size(self) -> None:
        catalog = copy.deepcopy(load_catalog())
        panel = next(
            dataset for dataset in catalog["datasets"] if dataset["id"] == "cybergym"
        )["panels"][0]
        panel["task_ids"].pop()
        self.assertTrue(
            any("does not match" in error for error in validate_catalog(catalog))
        )


if __name__ == "__main__":
    unittest.main()

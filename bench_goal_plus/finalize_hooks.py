"""Small finalization hooks used when a native controller has no report command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.openevolve_compare.reporting import write_campaign_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("openevolve-batch",))
    parser.add_argument("--campaign", required=True, type=Path)
    args = parser.parse_args(argv)
    report = write_campaign_report(args.campaign.expanduser().resolve())
    print(json.dumps({"records": len(report.get("records") or [])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

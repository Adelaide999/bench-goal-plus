#!/usr/bin/env python3
# EVOLVE-BLOCK-START

from __future__ import annotations


def build_charging_policy() -> dict:
    return {
        "currents_c": [5.00, 4.50, 4.05, 4.09, 4.15, 4.18, 4.10],
        "switch_soc": [0.14, 0.18, 0.30, 0.40, 0.50, 0.85],
    }


def main() -> None:
    print(build_charging_policy())


if __name__ == "__main__":
    main()
# EVOLVE-BLOCK-END

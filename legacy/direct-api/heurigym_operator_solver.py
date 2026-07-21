#!/usr/bin/env python3
"""Conservative valid solver for the smallest HeuriGym smoke case."""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path


def solve(input_path: Path, output_path: Path) -> None:
    data = json.loads(input_path.read_text())
    nodes = {str(node_id): resource for node_id, resource, *_ in data["nodes"]}
    successors = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}

    for source, target, *_ in data.get("edges", []):
        source = str(source)
        target = str(target)
        successors[source].append(target)
        indegree[target] += 1

    ready = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node_id = ready.popleft()
        order.append(node_id)
        for target in successors[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    if len(order) != len(nodes):
        raise ValueError("input graph is not a DAG")

    current_time = 0
    schedule: dict[str, int] = {}
    for node_id in order:
        schedule[node_id] = current_time
        current_time += int(data["delay"][nodes[node_id]])
    output_path.write_text("".join(f"{node_id}:{schedule[node_id]}\n" for node_id in nodes))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    solve(args.input, args.output)


if __name__ == "__main__":
    main()


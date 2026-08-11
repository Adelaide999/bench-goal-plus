#!/usr/bin/env python3
"""Compatibility entrypoint for the modular EdgeBench controller.

Normal users invoke ``python3 scripts/bench.py``.  This file intentionally
keeps the historical native-controller path stable for registries, old
campaign commands, and focused controller debugging.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bench_runtime_paths import ensure_temp_root  # noqa: E402
from experiments.edgebench.controller.cli import build_parser, main  # noqa: E402
from experiments.edgebench.controller.context import (  # noqa: E402
    DEFAULT_PATHS,
    EdgeBenchPaths,
    current_paths,
    set_paths,
)
from experiments.edgebench.controller.environment import (  # noqa: E402
    agent_api_probe_url,
    append_no_proxy,
    authenticated_api_probe,
    bridged_base_url,
    dataset_revision,
    default_route_ipv4,
    docker_http_probe,
    docker_resource_limit_probe,
    doctor,
    doctor_payload,
    ensure_local_task_exclude,
    judge_server_environment,
    local_asset_inventory,
    loopback_api_target,
    provision,
    resolve_agent_api_config,
    resolve_pi_auth,
    resolve_pi_provider,
    rust_image_runtime_probe,
    rust_runtime_archive_status,
    rust_runtime_asset,
    sforge_iptables_permission_probe,
    start_socket_bridge,
    task_config,
    task_images,
)
from experiments.edgebench.controller.evidence import (  # noqa: E402
    add_usage,
    asset_protocol_issue,
    codex_usage,
    goal_plus_completion_evidence,
    goal_plus_stats,
    iter_json_lines,
    latest_judge_report,
    live_goal_plus_status,
    paper_protocol_issue,
    remaining_time,
    score_task_run,
    summarize_cell,
)
from experiments.edgebench.controller.io import (  # noqa: E402
    campaign_dir,
    campaign_stamp,
    git_branch,
    git_dirty,
    git_head,
    portable_command,
    portable_path,
    read_json,
    run_capture,
    sanitize_id,
    sha256_file,
    sha256_text,
    upstream_entry,
    utc_now,
    write_json,
)
from experiments.edgebench.controller.preparation import prepare  # noqa: E402
from experiments.edgebench.controller.profiles import (  # noqa: E402
    ALLOWED_PROTOCOL_OVERRIDE_FIELDS,
    CLAUDE_REASONING_EFFORTS,
    GOAL_PLUS_METHODS,
    LEGACY_PAPER_PROTOCOL_ISSUES,
    METHODS,
    OFFICIAL_PROTOCOL_FIELDS,
    OFFICIAL_REQUIRED_DEFAULTS,
    OFFICIAL_SCHEDULED_RUNS,
    OFFICIAL_TASK_COUNT,
    PAPER_LARGE_GAP_THRESHOLD_PP,
    PROFILE_PROTOCOL_OVERRIDE_FIELDS,
    _protocol_diff,
    api_protocol_for_methods,
    load_official_codex_protocol,
    load_profile,
    official_task_protocol,
    profile_task_protocol,
    protocol_diff,
    validate_claude_thinking_contract,
)
from experiments.edgebench.controller.reporting import (  # noqa: E402
    comparison_record,
    finalize_campaign,
    load_local_fast_reference,
    load_paper_reference,
    style_header,
    write_comparison_workbook,
)
from experiments.edgebench.controller.runtime import (  # noqa: E402
    EVIDENCE_ANNOTATOR_PROVIDER_ID,
    RuntimeResources,
    build_sforge_command,
    cell_environment,
    cell_has_scored_results,
    execute_campaign,
    execute_cell_queue,
    finish_campaign_cell,
    judge_ready,
    launch,
    merge_agent_extra_env,
    prepare_runtime_resources,
    print_status,
    process_alive,
    start_campaign_cell,
    start_or_reuse_judge,
    status_payload,
    stop_campaign,
    update_campaign_cell,
)


# Historical constants remain readable for callers that inspect the module.
# Runtime code uses ``current_paths()`` so tests and embedded callers can inject
# an isolated path set without mutating module globals.
EDGE_ROOT = DEFAULT_PATHS.edge_root
GOAL_PLUS_ROOT = DEFAULT_PATHS.goal_plus_root
TASKS_DIR = DEFAULT_PATHS.tasks_dir
PROFILE_DIR = DEFAULT_PATHS.profile_dir
OFFICIAL_CODEX_PROTOCOL_PATH = DEFAULT_PATHS.official_codex_protocol_path
PAPER_REFERENCE_PATH = DEFAULT_PATHS.paper_reference_path
RUNS_ROOT = DEFAULT_PATHS.runs_root
UPSTREAM_MANIFEST = DEFAULT_PATHS.upstream_manifest
VENV = DEFAULT_PATHS.venv
VENV_PYTHON = DEFAULT_PATHS.venv_python
SFORGE = DEFAULT_PATHS.sforge


if __name__ == "__main__":
    raise SystemExit(main())

"""Repository-local runtime paths for portable benchmark execution."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, MutableMapping


ROOT = Path(__file__).resolve().parent
DEFAULT_TEMP_ROOT = ROOT / ".tmp"
TEMP_ENVIRONMENT_KEYS = ("TMPDIR", "TMP", "TEMP")


def ensure_temp_root(namespace: str | None = None) -> Path:
    """Return a writable repository-local temporary directory."""
    root = DEFAULT_TEMP_ROOT
    if namespace:
        root = root / namespace
    root.mkdir(parents=True, exist_ok=True)
    return root


def configure_temp_environment(
    environment: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    """Route host temporary files to ``bench-goal-plus/.tmp``.

    When configuring the current process, also reset Python's cached tempfile
    directory. Child-process environment dictionaries can be configured
    without mutating the controller process.
    """
    target = os.environ if environment is None else environment
    temp_root = str(ensure_temp_root())
    for key in TEMP_ENVIRONMENT_KEYS:
        target[key] = temp_root
    if target is os.environ:
        tempfile.tempdir = temp_root
    return target


@contextmanager
def temporary_directory(
    *,
    prefix: str,
    namespace: str,
) -> Iterator[Path]:
    """Create a disposable directory below the repository-local temp root."""
    with tempfile.TemporaryDirectory(
        prefix=prefix,
        dir=ensure_temp_root(namespace),
    ) as temporary:
        yield Path(temporary)


def make_preserved_temp_directory(*, prefix: str, namespace: str) -> Path:
    """Create a retained diagnostic directory below the local temp root."""
    return Path(
        tempfile.mkdtemp(
            prefix=prefix,
            dir=ensure_temp_root(namespace),
        )
    )


# Importers should never silently fall back to a system-wide /tmp. This also
# makes ordinary unittest TemporaryDirectory calls repository-local once the
# benchmark runtime has been imported.
configure_temp_environment()

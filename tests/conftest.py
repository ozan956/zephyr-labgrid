# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures.

The runner tests import ``runners.core`` from a Zephyr tree. Set
ZEPHYR_BASE or run inside a west workspace; otherwise those tests are
skipped.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def find_zephyr_base():
    base = os.environ.get('ZEPHYR_BASE')
    if base and Path(base, 'scripts/west_commands/runners/core.py').is_file():
        return Path(base)
    try:
        topdir = subprocess.run(['west', 'topdir'], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, check=True).stdout.strip()
        rel = subprocess.run(['west', 'config', 'zephyr.base'], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True).stdout.strip() or 'zephyr'
        base = Path(topdir, rel)
        if Path(base, 'scripts/west_commands/runners/core.py').is_file():
            return base
    except Exception:
        pass
    return None


ZEPHYR_BASE = find_zephyr_base()


@pytest.fixture(scope='session')
def zephyr_runners():
    """Make ``runners.core`` importable, or skip."""
    if ZEPHYR_BASE is None:
        pytest.skip('no Zephyr tree: set ZEPHYR_BASE')
    path = str(ZEPHYR_BASE / 'scripts' / 'west_commands')
    if path not in sys.path:
        sys.path.insert(0, path)
    import runners.core  # noqa: F401
    return ZEPHYR_BASE


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('ZEPHYR_LABGRID_LOCK_DIR', str(tmp_path / 'locks'))
    return tmp_path / 'locks'


@pytest.fixture
def clean_env(monkeypatch):
    for var in ('ZEPHYR_LABGRID_ENV', 'LG_ENV', 'LG_PLACE', 'LG_COORDINATOR',
                'LG_PTY_NO_PURGE', 'ZEPHYR_LABGRID_PURGE'):
        monkeypatch.delenv(var, raising=False)


class FakePlace:
    def __init__(self, name, tags=None, acquired=None, acquired_resources=None, allowed=()):
        self.name = name
        self.tags = tags or {}
        self.acquired = acquired
        self.acquired_resources = acquired_resources or []
        self.allowed = list(allowed)


@pytest.fixture
def fake_place():
    return FakePlace

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
    pytest.importorskip('west', reason='runners.core needs the west package')
    path = str(ZEPHYR_BASE / 'scripts' / 'west_commands')
    if path not in sys.path:
        sys.path.insert(0, path)
    import runners.core  # noqa: F401
    return ZEPHYR_BASE


from zephyr_labgrid import common as _common  # noqa: E402

REAL_RELEASE_IN_CHILD = _common.PlaceLock._release_in_child


@pytest.fixture(autouse=True)
def release_in_process(monkeypatch):
    """Run the release in this process so that tests can fake labgrid-client.
    tests/test_common.py covers the real child process."""
    def run(self):
        if not _common.release_if_unused(self.place, self.coordinator, log=self.log,
                                         pid=self.pid):
            raise _common.PlaceLockError(f'could not release place {self.place}')
    monkeypatch.setattr(_common.PlaceLock, '_release_in_child', run)


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('ZEPHYR_LABGRID_LOCK_DIR', str(tmp_path / 'locks'))
    return tmp_path / 'locks'


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every test starts without the variables the tools read."""
    for var in ('ZEPHYR_LABGRID_ENV', 'ZEPHYR_LABGRID_ENV_DIR', 'LG_ENV', 'LG_PLACE',
                'LG_COORDINATOR'):
        monkeypatch.delenv(var, raising=False)
    # labgrid-client's owner name for this user is then h/u
    monkeypatch.setenv('LG_HOSTNAME', 'h')
    monkeypatch.setenv('LG_USERNAME', 'u')


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


@pytest.fixture
def place_info():
    """An entry of common.lab_places."""
    def make(platform=None, acquired=None, allowed=(), **tags):
        if platform:
            tags['zephyr_platform'] = platform
        return {'tags': tags, 'acquired': acquired, 'allowed': list(allowed)}
    return make


class FakeScriptDriver:
    """Same signature as FlashScriptDriver.flash() in labgrid master."""

    def __init__(self, args, name=None):
        self.args = args
        self.name = name
        self.script = None
        self.device = object()
        self.calls = []

    def flash(self, script=None, args=None, timeout=None):
        self.calls.append((args, timeout))


class FakeTarget:
    def __init__(self, drivers):
        self.by_key = drivers       # protocol/class name -> driver
        self.drivers = list(drivers.values())   # as labgrid's Target.drivers
        self.activated = []
        self.deactivated = []
        self.cleaned = False

    def get_driver(self, cls, name=None, **kw):
        from labgrid.exceptions import NoDriverFoundError
        key = cls if isinstance(cls, str) else cls.__name__
        if name is not None:
            for drv in self.drivers:
                if getattr(drv, 'name', None) == name:
                    return drv
            raise NoDriverFoundError(name)
        if key == 'FlashScriptDriver':
            # like labgrid: several drivers of a class and no name is an error
            scripts = [d for d in self.drivers if isinstance(d, FakeScriptDriver)]
            if len(scripts) > 1:
                raise NoDriverFoundError('multiple drivers matching FlashScriptDriver')
            if scripts:
                return scripts[0]
        if key in self.by_key:
            return self.by_key[key]
        raise NoDriverFoundError(key)

    def activate(self, drv):
        self.activated.append(drv)

    def deactivate(self, drv):
        self.deactivated.append(drv)

    def cleanup(self):
        self.cleaned = True


@pytest.fixture(autouse=True)
def fake_script_driver_class(monkeypatch):
    """The tools tell script drivers apart with isinstance()."""
    import labgrid.driver
    monkeypatch.setattr(labgrid.driver, 'FlashScriptDriver', FakeScriptDriver)

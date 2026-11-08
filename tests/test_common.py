# SPDX-License-Identifier: Apache-2.0
import os

import pytest

from zephyr_labgrid import common


def test_default_env_prefers_zephyr_variable(clean_env, monkeypatch):
    assert common.default_env() is None
    monkeypatch.setenv('LG_ENV', '/lg.yaml')
    assert common.default_env() == '/lg.yaml'
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV', '/zl.yaml')
    assert common.default_env() == '/zl.yaml'


def test_coordinator_for_env_reads_option(tmp_path, clean_env, monkeypatch):
    env = tmp_path / 'env.yaml'
    env.write_text('options:\n  coordinator_address: lab:1234\ntargets: {}\n')
    assert common.coordinator_for_env(str(env)) == 'lab:1234'
    env.write_text('targets: {}\n')
    assert common.coordinator_for_env(str(env)) == common.DEFAULT_COORDINATOR
    monkeypatch.setenv('LG_COORDINATOR', 'other:1')
    assert common.coordinator_for_env(str(env)) == 'other:1'
    assert common.coordinator_for_env('/does/not/exist.yaml') == 'other:1'


# -- purge workaround --------------------------------------------------------

class FakeItem:
    """Stand-in for pyserial's TelnetSubnegotiation."""

    def __init__(self, answer):
        self.answer = answer
        self.set_calls = 0

    def set(self, value):
        self.set_calls += 1

    def wait(self, timeout):
        import serial
        if not self.answer:
            raise serial.SerialException("timeout while waiting for option 'purge'")


@pytest.fixture
def rfc2217_class(monkeypatch):
    """A fresh copy of serial.rfc2217.Serial so patches do not leak."""
    import serial.rfc2217
    cls = type('Serial', (serial.rfc2217.Serial,), {})
    monkeypatch.setattr(serial.rfc2217, 'Serial', cls)
    return cls


def make_port(cls, answer):
    port = cls.__new__(cls)
    port._rfc2217_options = {'purge': FakeItem(answer)}
    return port


def test_purge_auto_detects_broken_server(rfc2217_class, monkeypatch):
    monkeypatch.setattr(common, 'PURGE_PROBE_TIMEOUT', 0.01)
    warnings = []
    common.install_purge_workaround(warn=warnings.append)
    port = make_port(rfc2217_class, answer=False)
    port.rfc2217_send_purge(1)          # times out, must not raise
    assert common.purge_was_broken()
    assert len(warnings) == 1 and 'without purge' in warnings[0]
    port.rfc2217_send_purge(1)          # skipped now
    assert port._rfc2217_options['purge'].set_calls == 1
    # another port in the same process is skipped as well
    other = make_port(rfc2217_class, answer=False)
    other.rfc2217_send_purge(1)
    assert other._rfc2217_options['purge'].set_calls == 0
    assert len(warnings) == 1


def test_purge_auto_keeps_working_server(rfc2217_class):
    common.install_purge_workaround()
    port = make_port(rfc2217_class, answer=True)
    port.rfc2217_send_purge(1)
    port.rfc2217_send_purge(1)
    assert port._rfc2217_options['purge'].set_calls == 2
    assert not common.purge_was_broken()


# -- PlaceLock ---------------------------------------------------------------

class FakeCoordinator:
    """Replaces run_labgrid_client: one place, one user."""

    def __init__(self):
        self.acquired = False
        self.calls = []

    def __call__(self, args, coordinator=None):
        self.calls.append((tuple(args), coordinator))
        action = args[-1]
        if action == 'acquire':
            if self.acquired:
                return 1, 'You have already acquired place x.'
            self.acquired = True
            return 0, 'acquired place x'
        if action == 'release':
            if not self.acquired:
                return 1, 'place x is not acquired'
            self.acquired = False
            return 0, 'released place x'
        raise AssertionError(args)


@pytest.fixture
def coordinator(monkeypatch):
    fake = FakeCoordinator()
    monkeypatch.setattr(common, 'run_labgrid_client', fake)
    return fake


def test_placelock_acquire_release(coordinator, lock_dir):
    log = []
    with common.PlaceLock('x', 'c:1', log=log.append) as lock:
        assert coordinator.acquired
        assert os.path.exists(lock.marker)
        assert os.path.exists(lock.pidfile)
    assert not coordinator.acquired
    assert not os.path.exists(lock.marker)
    assert coordinator.calls[0][1] == 'c:1'
    assert log == ['acquired place x', 'released place x']


def test_placelock_keeps_place_acquired_by_hand(coordinator, lock_dir):
    coordinator.acquired = True            # user ran labgrid-client acquire
    log = []
    with common.PlaceLock('x', log=log.append):
        pass
    assert coordinator.acquired
    assert 'keeping it' in log[0]
    assert len(coordinator.calls) == 1     # no release call


def test_placelock_shared_by_two_tools(coordinator, lock_dir, monkeypatch):
    first = common.PlaceLock('x')
    first.acquire()
    # second tool: another pid that is alive
    second = common.PlaceLock('x')
    second.pidfile = os.path.join(second.dir, '999999.pid')
    monkeypatch.setattr(common, 'pid_alive', lambda pid: pid == 999999 or pid == os.getpid())
    log = []
    second.log = log.append
    second.acquire()
    assert 'sharing it' in log[-1]
    first.release()                        # not last: must not release
    assert coordinator.acquired
    assert os.path.exists(second.marker)
    second.release()                       # last one out releases
    assert not coordinator.acquired


def test_placelock_ignores_dead_pids(coordinator, lock_dir):
    lock = common.PlaceLock('x')
    lock.acquire()
    stale = os.path.join(lock.dir, '4000000000.pid')   # pid that can not exist
    open(stale, 'w').close()
    lock.release()
    assert not coordinator.acquired
    assert not os.path.exists(stale)


def test_placelock_waits_for_a_busy_place(lock_dir, monkeypatch):
    answers = [(1, 'Error: Place x is already acquired by o/v. To work simultaneously ...'),
               (1, 'Place x is already acquired'),
               (0, 'acquired place x')]
    monkeypatch.setattr(common, 'run_labgrid_client',
                        lambda args, coordinator=None: answers.pop(0))
    monkeypatch.setattr(common.time, 'sleep', lambda s: None)
    log = []
    lock = common.PlaceLock('x', log=log.append)
    lock.acquire(wait=60)
    assert lock.registered and answers == []
    assert log[0].startswith('place x is in use')
    assert log[-1] == 'acquired place x'


def test_placelock_gives_up_after_the_wait(lock_dir, monkeypatch):
    monkeypatch.setattr(common, 'run_labgrid_client', lambda args, coordinator=None:
                        (1, 'Place x is already acquired by o/v.'))
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(common.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(common.time, 'sleep', lambda s: None)
    with pytest.raises(common.PlaceLockError, match='acquired by o/v'):
        common.PlaceLock('x').acquire(wait=30)


def test_placelock_place_of_the_user_on_another_host_is_busy(lock_dir, monkeypatch):
    monkeypatch.setattr(common, 'run_labgrid_client', lambda args, coordinator=None:
                        (1, 'You have already acquired place x on other-host. To work '
                            'simultaneously, execute ...'))
    with pytest.raises(common.PlaceLockError, match='on other-host'):
        common.PlaceLock('x').acquire()


def test_placelock_error_on_foreign_owner(coordinator, lock_dir, monkeypatch):
    monkeypatch.setattr(common, 'run_labgrid_client',
                        lambda args, coordinator=None: (1, 'Place x is already acquired by h/u.'))
    with pytest.raises(common.PlaceLockError):
        common.PlaceLock('x').acquire()


def test_placelock_stale_marker_is_not_trusted(coordinator, lock_dir):
    """A killed run left its marker. The user acquired by hand since: a tool
    must not release the place in the end."""
    first = common.PlaceLock('x')
    first.acquire()
    first.registered = False               # killed: no release, pid file gone
    os.unlink(first.pidfile)
    log = []
    with common.PlaceLock('x', log=log.append):
        pass
    assert coordinator.acquired
    assert 'release it by hand' in log[0]
    assert not os.path.exists(first.marker)


FAKE_CLIENT = """#!/bin/sh
# fake labgrid-client: logs the action, release takes a while
for a; do action=$a; done
echo "$action" >> "$FAKE_LOG"
[ "$action" = release ] && sleep 1
echo "$action done"
"""


@pytest.fixture
def fake_client_on_path(tmp_path, monkeypatch):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    script = bindir / 'labgrid-client'
    script.write_text(FAKE_CLIENT)
    script.chmod(0o755)
    monkeypatch.setenv('PATH', f'{bindir}{os.pathsep}{os.environ["PATH"]}')
    monkeypatch.setenv('FAKE_LOG', str(tmp_path / 'calls'))
    return tmp_path / 'calls'


def test_release_in_child_process(fake_client_on_path, lock_dir, monkeypatch):
    from conftest import REAL_RELEASE_IN_CHILD
    monkeypatch.setattr(common.PlaceLock, '_release_in_child', REAL_RELEASE_IN_CHILD)
    log = []
    with common.PlaceLock('x', 'c:1', log=log.append) as lock:
        pass
    assert fake_client_on_path.read_text().split() == ['acquire', 'release']
    assert log[-1] == 'released place x'
    assert not os.path.exists(lock.marker)


def test_release_survives_sigkill(fake_client_on_path, lock_dir):
    """Twister kills labgrid-pty 0.5 s after SIGTERM. The release must
    still happen and leave no marker behind."""
    import signal
    import subprocess
    import sys
    import time
    code = ('import sys; sys.path.insert(0, sys.argv[1]); '
            'from zephyr_labgrid import common; '
            'lock = common.PlaceLock("x", "c:1"); lock.acquire(); '
            'print("ready", flush=True); lock.release()')
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen([sys.executable, '-c', code, root], stdout=subprocess.PIPE,
                            text=True)
    assert proc.stdout.readline().strip() == 'ready'
    time.sleep(0.5)                         # release child runs, fake release sleeps
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    marker = os.path.join(common.place_dir('x', 'c:1'), common.PlaceLock.MARKER)
    deadline = time.monotonic() + 10
    while os.path.exists(marker) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert fake_client_on_path.read_text().split() == ['acquire', 'release']
    assert not os.path.exists(marker)


def test_placelock_release_without_acquire_is_noop(coordinator, lock_dir):
    common.PlaceLock('x').release()
    assert coordinator.calls == []


# -- console handshake -------------------------------------------------------

def test_console_ready_handshake(lock_dir, monkeypatch):
    assert not common.console_is_ready('p', 'c:1')
    path = common.mark_console_ready('p', 'c:1')
    assert common.console_is_ready('p', 'c:1')
    assert common.wait_console_ready('p', 'c:1', timeout=0.01)
    common.clear_console_ready(path)
    assert not common.console_is_ready('p', 'c:1')
    assert not common.wait_console_ready('p', 'c:1', timeout=0.05)


def test_console_ready_ignores_dead_process(lock_dir):
    directory = common.place_dir('p', 'c:1')
    os.makedirs(directory)
    stale = os.path.join(directory, 'console-4000000000.ready')
    open(stale, 'w').close()
    assert not common.console_is_ready('p', 'c:1')
    assert not os.path.exists(stale)



def test_resolve_env_order(clean_env, monkeypatch):
    tags = {'zephyr_env': '/abs/tag.yaml'}
    assert common.resolve_env('/opt.yaml', 'p', tags=tags) == '/opt.yaml'
    monkeypatch.setenv('LG_ENV', '/lg.yaml')
    assert common.resolve_env(None, 'p', tags=tags) == '/lg.yaml'
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV', '/zl.yaml')
    assert common.resolve_env(None, 'p', tags=tags) == '/zl.yaml'


def test_resolve_env_from_tag(clean_env, monkeypatch):
    assert common.resolve_env(None, 'p', tags={'zephyr_env': '/abs/e.yaml'}) == '/abs/e.yaml'
    with pytest.raises(ValueError, match='ZEPHYR_LABGRID_ENV_DIR'):
        common.resolve_env(None, 'p', tags={'zephyr_env': 'rel/e.yaml'})
    assert common.resolve_env(None, 'p', env_dir='/envs',
                              tags={'zephyr_env': 'rel/e.yaml'}) == '/envs/rel/e.yaml'
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV_DIR', '/shared')
    assert common.resolve_env(None, 'p', tags={'zephyr_env': 'e.yaml'}) == '/shared/e.yaml'
    with pytest.raises(ValueError, match='no zephyr_env tag'):
        common.resolve_env(None, 'p', tags={})


def test_placeinfo_prints_places(monkeypatch, capsys, fake_place):
    import json

    import labgrid.remote.client

    from zephyr_labgrid import placeinfo

    class Session:
        places = {'p': fake_place('p', tags={'zephyr_env': 'e.yaml'}, acquired='h/u',
                                  allowed=['h/v'])}
    monkeypatch.setattr(labgrid.remote.client, 'start_session', lambda address: Session())
    monkeypatch.setattr(common, 'close_session', lambda s: None)
    assert placeinfo.main(['-x', 'c:1']) == 0
    assert json.loads(capsys.readouterr().out) == {
        'p': {'tags': {'zephyr_env': 'e.yaml'}, 'acquired': 'h/u', 'allowed': ['h/v']}}


def test_lab_places_ignores_labgrid_dir_in_cwd(tmp_path, monkeypatch):
    """The child process must not import ./labgrid from the current directory."""
    (tmp_path / 'labgrid').mkdir()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(common.PlaceLookupError) as e:
        common.lab_places(coordinator='127.0.0.1:1')
    assert 'cannot import' not in str(e.value)
    assert 'not reachable' in str(e.value)


# -- ownership and place selection -------------------------------------------

def test_whoami_and_owned_by(place_info):
    assert common.whoami() == 'h/u'
    assert common.owned_by(place_info(acquired='h/u'))
    assert common.owned_by(place_info(acquired='x/y', allowed=['h/u']))
    assert not common.owned_by(place_info(acquired='x/y'))
    assert not common.owned_by(place_info())


def test_platform_matches_and_selects():
    assert common.platform_matches('b/q', 'b/q', 'b')
    assert common.platform_matches('b', 'b/q', 'b')
    assert not common.platform_matches('b/q', 'b/r', 'b')
    assert not common.platform_matches('c/q', 'b/q', 'b')
    assert common.platform_selects('b/q', 'b')
    assert common.platform_selects('b', 'b/q')
    assert not common.platform_selects('b/q', 'b/r')


def test_select_owned_place(place_info):
    places = {'mine': place_info('b/q', acquired='h/u'),
              'free': place_info('b/q'),
              'other': place_info('c/q', acquired='h/u')}
    assert common.select_owned_place(places, 'b/q', 'b') == 'mine'
    places['mine2'] = place_info('b/q', acquired='h/u')
    with pytest.raises(common.PlaceSelectError, match='several places.*mine, mine2'):
        common.select_owned_place(places, 'b/q', 'b')
    with pytest.raises(common.PlaceSelectError, match='Free places for it: free'):
        common.select_owned_place({'free': place_info('b/q')}, 'b/q', 'b')
    with pytest.raises(common.PlaceSelectError, match='in use: busy'):
        common.select_owned_place({'busy': place_info('b/q', acquired='x/y')}, 'b/q', 'b')
    with pytest.raises(common.PlaceSelectError, match='No place has a matching'):
        common.select_owned_place({}, 'b/q', 'b')


def test_check_owned(place_info):
    places = {'mine': place_info(acquired='h/u'), 'free': place_info(),
              'busy': place_info(acquired='x/y')}
    common.check_owned(places, 'mine')
    with pytest.raises(common.PlaceSelectError, match='labgrid-client -p free acquire'):
        common.check_owned(places, 'free')
    with pytest.raises(common.PlaceSelectError, match='acquired by x/y'):
        common.check_owned(places, 'busy')
    with pytest.raises(common.PlaceSelectError, match='does not exist'):
        common.check_owned(places, 'nope')


def test_console_starting_marker(lock_dir):
    assert not common.console_expected('p', 'c:1')
    path = common.mark_console_starting('p', 'c:1')
    assert common.console_expected('p', 'c:1')
    common.clear_console_ready(path)
    assert not common.console_expected('p', 'c:1')


def test_started_by_twister(tmp_path):
    import subprocess
    import sys
    code = 'import time; time.sleep(30)'
    procs = [subprocess.Popen([sys.executable, '-c', code] + extra)
             for extra in (['scripts/twister', '-p', 'b'],
                           ['scripts/twister', '--flash-before'],
                           ['west', 'build'])]
    try:
        assert [common.started_by_twister(p.pid) for p in procs] == [True, False, False]
    finally:
        for p in procs:
            p.kill()
            p.wait()


# -- flasher selection, shared by the runner and the check tool ---------------

def test_select_flasher_skips_the_reset_script():
    from conftest import FakeScriptDriver, FakeTarget
    flash = FakeScriptDriver(['{image}'])
    reset = FakeScriptDriver(['{device.path}'], name='reset')
    target = FakeTarget({'flash': flash, 'reset': reset})
    assert common.select_flasher(target, activate=False) == (flash, 'script')
    assert target.activated == []
    with pytest.raises(LookupError, match='no flash driver'):
        common.select_flasher(FakeTarget({'reset': reset}))


def test_check_accepts_a_flash_and_a_reset_script(tmp_path, monkeypatch):
    """Regression: two FlashScriptDrivers made the check report no flash driver."""
    import io

    import labgrid
    from conftest import FakeScriptDriver, FakeTarget

    from zephyr_labgrid import check
    target = FakeTarget({'flash': FakeScriptDriver(['{image}']),
                         'reset': FakeScriptDriver([], name='reset'),
                         'ConsoleProtocol': object()})

    class Env:
        def __init__(self, config_file):
            pass

        def get_target(self):
            return target
    monkeypatch.setattr(labgrid, 'Environment', Env)
    env = tmp_path / 'e.yaml'
    env.write_text('targets: {}\n')
    out = io.StringIO()
    rep = check.Report(out)
    check.check_env_file(rep, str(env), 'p')
    assert 'ok    flash driver FakeScriptDriver' in out.getvalue()
    assert rep.failed == 0, out.getvalue()


def test_lab_places_asks_once_per_process(monkeypatch):
    import subprocess
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '{"p": {"tags": {}}}', '')
    monkeypatch.setattr(common, '_LAB_PLACES', {})
    monkeypatch.setattr(common.subprocess, 'run', run)
    assert common.lab_places('c:1') == common.lab_places('c:1') == {'p': {'tags': {}}}
    assert len(calls) == 1

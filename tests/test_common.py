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


def test_purge_mode_from_env(clean_env, monkeypatch):
    assert common.purge_mode_from_env() == 'auto'
    monkeypatch.setenv('ZEPHYR_LABGRID_PURGE', 'on')
    assert common.purge_mode_from_env() == 'on'
    monkeypatch.setenv('LG_PTY_NO_PURGE', '1')
    assert common.purge_mode_from_env() == 'off'


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
    assert common.install_purge_workaround('auto', warn=warnings.append)
    port = make_port(rfc2217_class, answer=False)
    port.rfc2217_send_purge(1)          # times out, must not raise
    assert common.purge_was_broken()
    assert len(warnings) == 1 and 'LG_PTY_NO_PURGE' in warnings[0]
    port.rfc2217_send_purge(1)          # skipped now
    assert port._rfc2217_options['purge'].set_calls == 1
    # another port in the same process is skipped as well
    other = make_port(rfc2217_class, answer=False)
    other.rfc2217_send_purge(1)
    assert other._rfc2217_options['purge'].set_calls == 0
    assert len(warnings) == 1


def test_purge_auto_keeps_working_server(rfc2217_class):
    common.install_purge_workaround('auto')
    port = make_port(rfc2217_class, answer=True)
    port.rfc2217_send_purge(1)
    port.rfc2217_send_purge(1)
    assert port._rfc2217_options['purge'].set_calls == 2
    assert not common.purge_was_broken()


def test_purge_off_disables_resets(rfc2217_class):
    assert common.install_purge_workaround('off')
    port = make_port(rfc2217_class, answer=False)
    port.reset_input_buffer()
    port.reset_output_buffer()


def test_purge_on_changes_nothing(rfc2217_class):
    before = rfc2217_class.rfc2217_send_purge
    assert not common.install_purge_workaround('on')
    assert rfc2217_class.rfc2217_send_purge is before
    with pytest.raises(ValueError):
        common.install_purge_workaround('sometimes')


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


def test_placelock_error_on_foreign_owner(coordinator, lock_dir, monkeypatch):
    monkeypatch.setattr(common, 'run_labgrid_client',
                        lambda args, coordinator=None: (1, 'Place x is already acquired by h/u.'))
    with pytest.raises(common.PlaceLockError):
        common.PlaceLock('x').acquire()


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


def test_purge_cache_is_per_host(lock_dir, rfc2217_class, monkeypatch):
    monkeypatch.setattr(common, 'PURGE_PROBE_TIMEOUT', 0.01)
    common.install_purge_workaround('auto')
    port = make_port(rfc2217_class, answer=False)
    port.portstr = 'rfc2217://exporter:40001'
    port.rfc2217_send_purge(1)
    cache = common.purge_cache_path(port)
    assert cache.endswith('purge-broken-exporter') and os.path.isfile(cache)
    # a new process (flag cleared) on another port of the same host skips the probe
    delattr(rfc2217_class, common._PURGE_FLAG)
    other = make_port(rfc2217_class, answer=False)
    other.portstr = 'rfc2217://exporter:40002'
    other.rfc2217_send_purge(1)
    assert other._rfc2217_options['purge'].set_calls == 0


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


def test_resolve_env_reports_lookup_failure(clean_env, monkeypatch):
    def fail(place, coordinator=None):
        raise common.PlaceLookupError('place p does not exist')
    monkeypatch.setattr(common, 'place_tags', fail)
    with pytest.raises(ValueError, match='does not exist'):
        common.resolve_env(None, 'p')


def test_placeinfo_prints_tags(monkeypatch, capsys, fake_place):
    import json

    import labgrid.remote.client

    from zephyr_labgrid import placeinfo

    class Session:
        places = {'p': fake_place('p', tags={'zephyr_env': 'e.yaml'})}
    monkeypatch.setattr(labgrid.remote.client, 'start_session', lambda address: Session())
    monkeypatch.setattr(common, 'close_session', lambda s: None)
    assert placeinfo.main(['-x', 'c:1', 'p']) == 0
    assert json.loads(capsys.readouterr().out) == {'zephyr_env': 'e.yaml'}
    assert placeinfo.main(['-x', 'c:1', 'missing']) == 2


def test_place_tags_ignores_labgrid_dir_in_cwd(tmp_path, monkeypatch):
    """The child process must not import ./labgrid from the current directory."""
    (tmp_path / 'labgrid').mkdir()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(common.PlaceLookupError) as e:
        common.place_tags('p', coordinator='127.0.0.1:1')
    assert 'cannot import' not in str(e.value)
    assert 'not reachable' in str(e.value)

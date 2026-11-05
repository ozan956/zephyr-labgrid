# SPDX-License-Identifier: Apache-2.0
"""Tests for the labgrid west runner. Need a Zephyr tree (ZEPHYR_BASE)."""

import argparse
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope='module')
def runner_mod(zephyr_runners):
    spec = importlib.util.spec_from_file_location(
        'labgrid_runner', ROOT / 'scripts' / 'labgrid_runner.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner_config(zephyr_runners, tmp_path):
    from runners.core import FileType, RunnerConfig
    hex_file = tmp_path / 'zephyr.hex'
    hex_file.write_text(':00000001FF\n')
    bin_file = tmp_path / 'zephyr.bin'
    bin_file.write_bytes(b'\0' * 16)
    return RunnerConfig(str(tmp_path), '/boards/x', str(tmp_path / 'zephyr.elf'), None,
                        str(hex_file), str(bin_file), None, None, None, FileType.OTHER)


def create(runner_mod, cfg, argv):
    parser = argparse.ArgumentParser()
    runner_mod.LabgridBinaryRunner.add_parser(parser)
    args = parser.parse_args(argv)
    return runner_mod.LabgridBinaryRunner.create(cfg, args)


def test_name_and_caps(runner_mod):
    cls = runner_mod.LabgridBinaryRunner
    assert cls.name() == 'labgrid'
    caps = cls.capabilities()
    assert caps.commands == {'flash'}
    assert caps.dev_id and caps.reset and caps.file


def test_create_from_arguments(runner_mod, runner_config, clean_env):
    r = create(runner_mod, runner_config,
               ['--dev-id', 'p1', '--env', '/e.yaml', '--acquire', '--wait-console', '5',
                '--driver', 'Flash', '--timeout', '7'])
    assert (r.place, r.env_file, r.acquire, r.wait_console) == ('p1', '/e.yaml', True, 5.0)
    assert (r.driver_name, r.timeout, r.reset) == ('Flash', 7.0, False)


def test_create_from_environment(runner_mod, runner_config, clean_env, monkeypatch):
    monkeypatch.setenv('LG_ENV', '/lg.yaml')
    monkeypatch.setenv('LG_PLACE', 'p2')
    r = create(runner_mod, runner_config, [])
    assert (r.place, r.env_file) == ('p2', '/lg.yaml')
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV', '/zl.yaml')
    assert create(runner_mod, runner_config, []).env_file == '/zl.yaml'


def test_create_errors(runner_mod, runner_config, clean_env, monkeypatch):
    with pytest.raises(ValueError, match='--dev-id'):
        create(runner_mod, runner_config, ['--env', '/e.yaml'])
    # no env: looked up from the place tag later, in do_run
    assert create(runner_mod, runner_config, ['--dev-id', 'p']).env_file is None


def test_image_prefers_hex_then_bin(runner_mod, runner_config, clean_env):
    r = create(runner_mod, runner_config, ['--dev-id', 'p', '--env', '/e.yaml'])
    assert r._image() == runner_config.hex_file
    os.unlink(runner_config.hex_file)
    assert r._image() == runner_config.bin_file
    # west fills cfg.file from --file
    r2 = create(runner_mod, runner_config._replace(file='/some/image.bin'),
                ['--dev-id', 'p', '--env', '/e.yaml'])
    assert r2._image() == '/some/image.bin'


class FakeConf:
    def __init__(self, values, edt=None):
        self.values = values
        self.edt = edt

    def __contains__(self, item):
        return item in self.values

    def __getitem__(self, item):
        return self.values[item]

    def getboolean(self, option):
        return bool(self.values.get(option, False))


class FakeNode:
    def __init__(self, addr):
        self.regs = [type('Reg', (), {'addr': addr})()]


class FakeEdt:
    def __init__(self, boot=None, code=None):
        self.label2node = {'boot_partition': FakeNode(boot)} if boot is not None else {}
        self._code = code

    def chosen_node(self, name):
        assert name == 'zephyr,code-partition'
        return FakeNode(self._code)


@pytest.fixture
def runner(runner_mod, runner_config, clean_env):
    return create(runner_mod, runner_config, ['--dev-id', 'p', '--env', '/e.yaml'])


def test_flash_address_from_kconfig(runner):
    runner._build_conf = FakeConf({'CONFIG_FLASH_BASE_ADDRESS': 0x08000000,
                                   'CONFIG_HAS_FLASH_LOAD_OFFSET': True,
                                   'CONFIG_FLASH_LOAD_OFFSET': 0x1000})
    assert runner._flash_address() == '0x8001000'


def test_flash_address_from_devicetree(runner):
    runner._build_conf = FakeConf({'CONFIG_ESP_SIMPLE_BOOT': True}, FakeEdt(boot=0x1000))
    assert runner._flash_address() == '0x1000'
    runner._build_conf = FakeConf({}, FakeEdt(code=0x20000))
    assert runner._flash_address() == '0x20000'


def test_flash_address_error_is_readable(runner):
    runner._build_conf = FakeConf({}, FakeEdt())
    runner._build_conf.edt.chosen_node = lambda name: None
    with pytest.raises(RuntimeError, match='flash address'):
        runner._flash_address()


class FakeScriptDriver:
    """Same signature as FlashScriptDriver.flash() in labgrid master."""

    def __init__(self, args):
        self.args = args
        self.device = object()
        self.calls = []

    def flash(self, script=None, args=None, timeout=None):
        self.calls.append((args, timeout))


class FakeManagedFile:
    def __init__(self, local, resource):
        self.local = local

    def sync_to_resource(self):
        pass

    def get_remote_path(self):
        return f'/remote/{os.path.basename(self.local)}'


@pytest.fixture
def managed_file(monkeypatch):
    import labgrid.util.managedfile
    monkeypatch.setattr(labgrid.util.managedfile, 'ManagedFile', FakeManagedFile)


def test_flash_with_script_substitutes_placeholders(runner, managed_file):
    runner._build_conf = FakeConf({'CONFIG_FLASH_BASE_ADDRESS': 0x1000})
    drv = FakeScriptDriver(['{device.devnode}', '{address}', '{image}'])
    runner._flash_with_script(drv, '/build/zephyr.bin')
    assert drv.calls == [(['{device.devnode}', '0x1000', '/remote/zephyr.bin'], None)]


def test_flash_with_script_appends_image_without_placeholder(runner, managed_file):
    drv = FakeScriptDriver(['--fast'])
    runner.timeout = 42
    runner._flash_with_script(drv, '/build/zephyr.hex')
    assert drv.calls == [(['--fast', '/remote/zephyr.hex'], 42)]



class FakeTarget:
    def __init__(self, drivers):
        self.drivers = drivers      # protocol/class name -> driver
        self.deactivated = []
        self.cleaned = False

    def get_driver(self, cls, name=None, **kw):
        from labgrid.exceptions import NoDriverFoundError
        key = cls if isinstance(cls, str) else cls.__name__
        if name is not None:
            for drv in self.drivers.values():
                if getattr(drv, 'name', None) == name:
                    return drv
            raise NoDriverFoundError(name)
        if key in self.drivers:
            return self.drivers[key]
        raise NoDriverFoundError(key)

    def deactivate(self, drv):
        self.deactivated.append(drv)

    def cleanup(self):
        self.cleaned = True


class FakeBootstrap:
    name = 'boot'

    def __init__(self):
        self.loaded = []

    def load(self, image):
        self.loaded.append(image)


def test_get_flasher_prefers_bootstrap(runner):
    boot = FakeBootstrap()
    script = FakeScriptDriver([])
    target = FakeTarget({'BootstrapProtocol': boot, 'FlashScriptDriver': script})
    assert runner._get_flasher(target) == (boot, 'bootstrap')
    assert runner._get_flasher(FakeTarget({'FlashScriptDriver': script})) == (script, 'script')
    with pytest.raises(RuntimeError, match='no flash driver'):
        runner._get_flasher(FakeTarget({}))


def test_get_flasher_by_name(runner):
    boot = FakeBootstrap()
    runner.driver_name = 'boot'
    assert runner._get_flasher(FakeTarget({'x': boot})) == (boot, 'bootstrap')
    runner.driver_name = 'missing'
    with pytest.raises(RuntimeError, match='not found'):
        runner._get_flasher(FakeTarget({'x': boot}))


def test_do_run_flashes_and_cleans_up(runner, monkeypatch):
    boot = FakeBootstrap()
    target = FakeTarget({'BootstrapProtocol': boot})

    class FakeEnvironment:
        def __init__(self, config_file):
            assert config_file == '/e.yaml'

        def get_target(self):
            return target

    import labgrid
    monkeypatch.setattr(labgrid, 'Environment', FakeEnvironment)
    runner.do_run('flash')
    assert boot.loaded == [runner.cfg.hex_file]
    assert target.deactivated == [boot] and target.cleaned
    assert os.environ['LG_PLACE'] == 'p'


def test_do_run_with_acquire_uses_place_lock(runner, monkeypatch, lock_dir):
    from zephyr_labgrid import common
    calls = []

    def fake_client(args, coordinator=None):
        calls.append(args[-1])
        return (0, 'acquired place p') if args[-1] == 'acquire' else (0, 'released place p')

    monkeypatch.setattr(common, 'run_labgrid_client', fake_client)
    boot = FakeBootstrap()

    class FakeEnvironment:
        def __init__(self, config_file):
            pass

        def get_target(self):
            return FakeTarget({'BootstrapProtocol': boot})

    import labgrid
    monkeypatch.setattr(labgrid, 'Environment', FakeEnvironment)
    runner.acquire = True
    runner.do_run('flash')
    assert calls == ['acquire', 'release']
    assert boot.loaded


def test_do_run_releases_on_error(runner, monkeypatch, lock_dir):
    from zephyr_labgrid import common
    calls = []
    monkeypatch.setattr(common, 'run_labgrid_client',
                        lambda args, coordinator=None: (calls.append(args[-1]) or 0, 'ok'))

    class FakeEnvironment:
        def __init__(self, config_file):
            raise OSError('no such file')

    import labgrid
    monkeypatch.setattr(labgrid, 'Environment', FakeEnvironment)
    runner.acquire = True
    with pytest.raises(RuntimeError, match='could not load'):
        runner.do_run('flash')
    assert calls == ['acquire', 'release']


def test_wait_console(runner, monkeypatch, lock_dir):
    from zephyr_labgrid import common
    waited = []
    monkeypatch.setattr(common, 'wait_console_ready',
                        lambda place, coordinator, timeout: waited.append((place, timeout)) or False)
    monkeypatch.setattr(runner, '_flash', lambda *a: None)
    runner.wait_console = 3
    runner.do_run('flash')
    assert waited == [('p', 3)]


def fake_environment(monkeypatch, target, created=None):
    class FakeEnvironment:
        def __init__(self, config_file):
            if created is not None:
                created.append(config_file)

        def get_target(self):
            return target

    import labgrid
    monkeypatch.setattr(labgrid, 'Environment', FakeEnvironment)


def test_env_from_place_tag(runner_mod, runner_config, clean_env, monkeypatch, tmp_path):
    from zephyr_labgrid import common
    monkeypatch.setattr(common, 'place_tags', lambda place, coordinator=None:
                        {'zephyr_env': 'stm32/labgrid.yaml'})
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV_DIR', str(tmp_path))
    created = []
    fake_environment(monkeypatch, FakeTarget({'BootstrapProtocol': FakeBootstrap()}), created)
    r = create(runner_mod, runner_config, ['--dev-id', 'p'])
    r.do_run('flash')
    assert created == [str(tmp_path / 'stm32/labgrid.yaml')]

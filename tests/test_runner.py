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
    assert caps.commands == {'flash', 'reset'}
    assert caps.dev_id and caps.reset and caps.file and caps.dry_run


def test_create_from_arguments(runner_mod, runner_config, clean_env):
    r = create(runner_mod, runner_config,
               ['--dev-id', 'p1', '--env', '/e.yaml', '--wait-console', '5',
                '--driver', 'Flash', '--timeout', '7', '--ignore-platform'])
    assert (r.place, r.env_file, r.wait_console) == ('p1', '/e.yaml', 5.0)
    assert r.ignore_platform and not r.acquire
    assert (r.driver_name, r.timeout, r.reset) == ('Flash', 7.0, False)


def test_create_from_environment(runner_mod, runner_config, clean_env, monkeypatch):
    monkeypatch.setenv('LG_ENV', '/lg.yaml')
    monkeypatch.setenv('LG_PLACE', 'p2')
    r = create(runner_mod, runner_config, [])
    assert (r.place, r.env_file) == ('p2', '/lg.yaml')
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV', '/zl.yaml')
    assert create(runner_mod, runner_config, []).env_file == '/zl.yaml'


def test_create_needs_no_place_or_env(runner_mod, runner_config, clean_env):
    # both are looked up later, in do_run
    r = create(runner_mod, runner_config, [])
    assert (r.place, r.env_file) == (None, None)


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

    def get(self, option, *args):
        return self.values.get(option, *args)

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


BOARD = {'CONFIG_BOARD_TARGET': 'b/q', 'CONFIG_BOARD': 'b'}


@pytest.fixture(autouse=True)
def not_under_twister(monkeypatch):
    """The tests must not depend on who started pytest: a parent process
    with "twister" in its command line would make every flash wait."""
    from zephyr_labgrid import common
    monkeypatch.setattr(common, 'started_by_twister', lambda pid=None: False)


@pytest.fixture
def lab(monkeypatch, place_info):
    """The coordinator's places as the runner sees them. Place p is ours."""
    from zephyr_labgrid import common
    places = {'p': place_info('b/q', acquired='h/u')}
    monkeypatch.setattr(common, 'lab_places', lambda coordinator=None: places)
    return places


@pytest.fixture
def runner(runner_mod, runner_config, clean_env, lab):
    r = create(runner_mod, runner_config, ['--dev-id', 'p', '--env', '/e.yaml'])
    r._build_conf = FakeConf(dict(BOARD))
    return r


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

    def __init__(self, args, name=None):
        self.args = args
        self.name = name
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


@pytest.fixture(autouse=True)
def fake_script_driver_class(monkeypatch):
    """The runner tells script drivers apart with isinstance()."""
    import labgrid.driver
    monkeypatch.setattr(labgrid.driver, 'FlashScriptDriver', FakeScriptDriver)


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
        if key in self.by_key:
            return self.by_key[key]
        raise NoDriverFoundError(key)

    def activate(self, drv):
        self.activated.append(drv)

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

    seen = []

    class FakeEnvironment:
        def __init__(self, config_file):
            assert config_file == '/e.yaml'
            seen.append(os.environ.get('LG_PLACE'))

        def get_target(self):
            return target

    import labgrid
    monkeypatch.setattr(labgrid, 'Environment', FakeEnvironment)
    runner.do_run('flash')
    assert boot.loaded == [runner.cfg.hex_file]
    assert target.deactivated == [boot] and target.cleaned
    # LG_PLACE is set for the environment file only, then restored
    assert seen == ['p'] and 'LG_PLACE' not in os.environ


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
    assert calls == ['acquire']         # held until west exits (sysbuild)
    common.release_process_places()
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
    common.release_process_places()     # what atexit does when west dies
    assert calls == ['acquire', 'release']


def test_wait_console(runner, monkeypatch, lock_dir):
    from zephyr_labgrid import common
    waited = []
    monkeypatch.setattr(common, 'wait_console_ready', lambda place, coordinator, timeout:
                        waited.append((place, timeout)) or False)
    monkeypatch.setattr(runner, '_run_on_target', lambda *a: None)
    runner.wait_console = 3
    runner.do_run('flash')
    assert waited == [('p', 3)]
    runner.wait_console = 0
    runner.do_run('flash')
    assert waited == [('p', 3)]


def test_wait_console_by_default_only_for_a_starting_pty(runner_mod, runner, monkeypatch,
                                                       lock_dir):
    from zephyr_labgrid import common
    waited = []
    monkeypatch.setattr(common, 'wait_console_ready', lambda place, coordinator, timeout:
                        waited.append(timeout) or True)
    monkeypatch.setattr(runner, '_run_on_target', lambda *a: None)
    assert runner.wait_console is None
    runner.do_run('flash')                  # interactive: no labgrid-pty, no wait
    assert waited == []
    common.mark_console_starting('p', common.coordinator_for_env('/e.yaml'))
    runner.do_run('flash')
    assert waited == [runner_mod.AUTO_CONSOLE_WAIT]


def fake_environment(monkeypatch, target, created=None):
    class FakeEnvironment:
        def __init__(self, config_file):
            if created is not None:
                created.append(config_file)

        def get_target(self):
            return target

    import labgrid
    monkeypatch.setattr(labgrid, 'Environment', FakeEnvironment)


def test_sysbuild_holds_place_across_images(runner_mod, runner_config, clean_env,
                                            monkeypatch, lock_dir, lab):
    """west flash runs the runner once per sysbuild image in one process;
    the place must stay acquired from the first image to the last."""
    from zephyr_labgrid import common
    calls = []
    monkeypatch.setattr(common, 'run_labgrid_client',
                        lambda args, coordinator=None: (calls.append(args[-1]) or 0, 'ok'))
    boot = FakeBootstrap()
    fake_environment(monkeypatch, FakeTarget({'BootstrapProtocol': boot}))
    for _ in ('mcuboot', 'app'):
        r = create(runner_mod, runner_config,
                   ['--dev-id', 'p', '--env', '/e.yaml', '--acquire'])
        r._build_conf = FakeConf(dict(BOARD))
        r.do_run('flash')
    assert calls == ['acquire']
    assert len(boot.loaded) == 2
    common.release_process_places()
    common.release_process_places()     # idempotent
    assert calls == ['acquire', 'release']


class FakeReset:
    def __init__(self):
        self.count = 0

    def reset(self):
        self.count += 1


class FakeOpenOCD:
    def __init__(self):
        self.commands = []

    def execute(self, commands):
        self.commands.append(commands)


def test_reset_command_uses_reset_protocol(runner, monkeypatch):
    rst = FakeReset()
    boot = FakeBootstrap()
    target = FakeTarget({'ResetProtocol': rst, 'BootstrapProtocol': boot})
    fake_environment(monkeypatch, target)
    runner.do_run('reset')
    assert rst.count == 1 and not boot.loaded and target.cleaned


def test_reset_command_falls_back_to_openocd(runner, monkeypatch):
    ocd = FakeOpenOCD()
    target = FakeTarget({'OpenOCDDriver': ocd})
    fake_environment(monkeypatch, target)
    runner.do_run('reset')
    assert ocd.commands == [['init', 'reset run', 'shutdown']]
    assert target.deactivated == [ocd]


def test_reset_command_without_any_driver_fails(runner, monkeypatch):
    fake_environment(monkeypatch, FakeTarget({'BootstrapProtocol': FakeBootstrap()}))
    with pytest.raises(RuntimeError, match='can not reset'):
        runner.do_run('reset')


def test_dry_run_flashes_nothing(runner_mod, runner_config, clean_env, monkeypatch, caplog,
                                 lab):
    created = []
    fake_environment(monkeypatch, FakeTarget({}), created)
    runner = create(runner_mod, runner_config, ['--dev-id', 'p', '--env', '/e.yaml', '--dry-run'])
    runner._build_conf = FakeConf(dict(BOARD))
    with caplog.at_level('INFO'):
        runner.do_run('flash')
    assert created == []
    assert 'would flash' in caplog.text


def test_env_from_place_tag(runner_mod, runner_config, clean_env, monkeypatch, tmp_path, lab):
    lab['p']['tags']['zephyr_env'] = 'stm32/labgrid.yaml'
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV_DIR', str(tmp_path))
    created = []
    fake_environment(monkeypatch, FakeTarget({'BootstrapProtocol': FakeBootstrap()}), created)
    r = create(runner_mod, runner_config, ['--dev-id', 'p'])
    r._build_conf = FakeConf(dict(BOARD))
    r.do_run('flash')
    assert created == [str(tmp_path / 'stm32/labgrid.yaml')]


def test_place_is_picked_from_the_build(runner_mod, runner_config, clean_env, monkeypatch,
                                        lab, place_info, caplog):
    lab['other'] = place_info('c/q', acquired='h/u')
    lab['free'] = place_info('b/q')
    fake_environment(monkeypatch, FakeTarget({'BootstrapProtocol': FakeBootstrap()}))
    r = create(runner_mod, runner_config, ['--env', '/e.yaml'])
    r._build_conf = FakeConf(dict(BOARD))
    with caplog.at_level('INFO'):
        r.do_run('flash')
    assert r.place == 'p'
    assert 'the one you hold for b/q' in caplog.text


def test_place_must_be_ours(runner, lab):
    lab['p']['acquired'] = None
    with pytest.raises(RuntimeError, match='labgrid-client -p p acquire'):
        runner.do_run('flash')
    lab['p']['acquired'] = 'x/y'
    with pytest.raises(RuntimeError, match='acquired by x/y'):
        runner.do_run('flash')


def test_platform_must_fit_the_build(runner, lab, monkeypatch):
    lab['p']['tags']['zephyr_platform'] = 'c/q'
    with pytest.raises(RuntimeError, match='--ignore-platform'):
        runner.do_run('flash')
    runner.ignore_platform = True
    fake_environment(monkeypatch, FakeTarget({'BootstrapProtocol': FakeBootstrap()}))
    runner.do_run('flash')


def test_flasher_is_not_the_reset_script(runner):
    flash = FakeScriptDriver(['{image}'])
    reset = FakeScriptDriver(['{device.path}'], name='reset')
    target = FakeTarget({'flash': flash, 'reset': reset})
    assert runner._get_flasher(target) == (flash, 'script')
    assert target.activated == [flash]
    with pytest.raises(RuntimeError, match='no flash driver'):
        runner._get_flasher(FakeTarget({'reset': reset}))
    two = FakeTarget({'a': flash, 'b': FakeScriptDriver([], name='other')})
    with pytest.raises(RuntimeError, match='pick one with --driver'):
        runner._get_flasher(two)


def test_reset_command_uses_the_reset_script(runner, monkeypatch):
    reset = FakeScriptDriver(['{device.path}'], name='reset')
    power = type('Power', (), {'cycle': lambda self: pytest.fail('power cycled')})()
    target = FakeTarget({'flash': FakeScriptDriver(['{image}']), 'reset': reset,
                         'PowerProtocol': power})
    fake_environment(monkeypatch, target)
    runner.do_run('reset')
    assert reset.calls == [(None, None)]    # its own args, no image
    assert target.deactivated == [reset]

# SPDX-License-Identifier: Apache-2.0
"""West runner that flashes through a labgrid place.

The runner is a thin client: it resolves a labgrid environment (``--env``,
``$ZEPHYR_LABGRID_ENV``, or the ``zephyr_env`` tag of the place), points it
at a place (``--dev-id`` or ``$LG_PLACE``) and asks the flash driver of the
target to load the image. The actual
flashing tool (OpenOCD, or a vendor tool behind FlashScriptDriver)
runs wherever the labgrid exporter decides, usually on the exporter host
next to the probe.

Supported labgrid drivers:

- any driver implementing ``BootstrapProtocol`` (OpenOCDDriver, FlashromDriver,
  the USB loaders): the runner calls ``load(image)``.
- ``FlashScriptDriver``: the runner copies the image to the exporter and
  runs the driver's script with ``{image}`` in ``args`` replaced by the
  remote path of the image and ``{address}`` by the flash offset from the
  build configuration (for raw .bin images).
"""

import os
import signal
import sys
from pathlib import Path

from runners.core import RunnerCaps, RunnerConfig, ZephyrBinaryRunner

# The zephyr_labgrid package sits next to scripts/ in the module checkout.
# west loads this file by path, so put the checkout first on sys.path; a pip
# installed copy of the package is used only when the checkout has none.
_MODULE_ROOT = str(Path(__file__).resolve().parent.parent)
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from zephyr_labgrid import common  # noqa: E402


class LabgridBinaryRunner(ZephyrBinaryRunner):
    """Flash a Zephyr image through a labgrid place."""

    def __init__(self, cfg: RunnerConfig, env_file, place, driver_name=None,
                 power_cycle=False, reset=False, timeout=None, acquire=False,
                 wait_console=0.0, env_dir=None):
        super().__init__(cfg)
        self.env_file = env_file
        self.env_dir = env_dir
        self.place = place
        self.driver_name = driver_name
        self.power_cycle = power_cycle
        self.reset = reset
        self.timeout = timeout
        self.acquire = acquire
        self.wait_console = wait_console

    @classmethod
    def name(cls):
        return 'labgrid'

    @classmethod
    def capabilities(cls):
        return RunnerCaps(commands={'flash'}, dev_id=True, reset=True,
                          file=True)

    @classmethod
    def dev_id_help(cls) -> str:
        return 'labgrid place name (defaults to $LG_PLACE)'

    @classmethod
    def do_add_parser(cls, parser):
        parser.add_argument('--env', default=None,
                            help='labgrid environment YAML (defaults to '
                                 '$ZEPHYR_LABGRID_ENV, then $LG_ENV, then the '
                                 'zephyr_env tag of the place)')
        parser.add_argument('--env-dir', default=None,
                            help='directory for a relative zephyr_env tag '
                                 '(defaults to $ZEPHYR_LABGRID_ENV_DIR)')
        parser.add_argument('--driver', default=None,
                            help='name of the labgrid driver to flash with '
                                 '(default: the BootstrapProtocol driver, '
                                 'else the FlashScriptDriver of the target)')
        parser.add_argument('--power-cycle', action='store_true',
                            help='power cycle the place before flashing '
                                 '(needs a PowerProtocol driver)')
        parser.add_argument('--timeout', type=float, default=None,
                            help='override labgrid resource wait timeout')
        parser.add_argument('--acquire', action='store_true',
                            help='acquire the place before flashing and release '
                                 'it afterwards (kept if already acquired by you)')
        parser.add_argument('--wait-console', type=float, default=0.0, metavar='SECONDS',
                            help='wait up to SECONDS for a labgrid-pty on this host '
                                 'to have the console of the place open before '
                                 'flashing (Twister starts both at the same time)')
        parser.set_defaults(reset=False)

    @classmethod
    def do_create(cls, cfg: RunnerConfig, args):
        # ZEPHYR_LABGRID_ENV is preferred over LG_ENV: LG_ENV also activates
        # labgrid's own pytest plugin inside pytest-twister-harness runs.
        # Without either, the zephyr_env tag of the place is looked up in
        # do_run, so that creating the runner never talks to the coordinator.
        env_file = args.env or common.default_env()
        place = args.dev_id or common.default_place()
        if not place:
            raise ValueError('labgrid runner needs --dev-id or $LG_PLACE')
        return LabgridBinaryRunner(cfg, env_file=env_file, place=place,
                                   env_dir=args.env_dir,
                                   driver_name=args.driver,
                                   power_cycle=args.power_cycle,
                                   reset=args.reset, timeout=args.timeout,
                                   acquire=args.acquire,
                                   wait_console=args.wait_console)

    def _image(self) -> str:
        if self.cfg.file is not None:
            return self.cfg.file
        for candidate in (self.cfg.hex_file, self.cfg.bin_file, self.cfg.elf_file):
            if candidate and Path(candidate).is_file():
                return candidate
        raise RuntimeError('no image found in build directory')

    def _get_flasher(self, target):
        """Return (driver, kind) where kind is 'bootstrap' or 'script'."""
        from labgrid.driver import FlashScriptDriver
        from labgrid.driver.common import Driver
        from labgrid.exceptions import NoDriverFoundError

        if self.driver_name:
            try:
                drv = target.get_driver(Driver, name=self.driver_name)
            except NoDriverFoundError:
                raise RuntimeError(f'labgrid driver "{self.driver_name}" not found '
                                   f'in {self.env_file}') from None
            if isinstance(drv, FlashScriptDriver):
                return drv, 'script'
            if hasattr(drv, 'load'):
                return drv, 'bootstrap'
            raise RuntimeError(f'labgrid driver "{self.driver_name}" can not flash '
                               '(needs BootstrapProtocol or FlashScriptDriver)')

        try:
            return target.get_driver('BootstrapProtocol'), 'bootstrap'
        except NoDriverFoundError:
            pass
        try:
            return target.get_driver('FlashScriptDriver'), 'script'
        except NoDriverFoundError:
            raise RuntimeError('no flash driver (BootstrapProtocol or FlashScriptDriver) '
                               f'in {self.env_file}; check the drivers section and the '
                               f'resources of place "{self.place}"') from None

    def _flash_address(self) -> str:
        """Flash offset of the image as hex string, from the build config.

        Same rule as Zephyr's own runners: CONFIG_FLASH_BASE_ADDRESS plus
        CONFIG_FLASH_LOAD_OFFSET when the build has one. For raw .bin images
        the flashing tool needs this; .hex and .elf carry their own address.
        """
        conf = self.build_conf
        try:
            if 'CONFIG_FLASH_BASE_ADDRESS' in conf:
                return hex(self.flash_address_from_build_conf(conf))
            # Builds without CONFIG_FLASH_BASE_ADDRESS (Espressif SoCs) take the
            # offset from the devicetree, same as soc/espressif/common/CMakeLists.txt:
            # the boot partition for simple boot, else the chosen code partition.
            if conf.getboolean('CONFIG_ESP_SIMPLE_BOOT'):
                node = conf.edt.label2node['boot_partition']
            else:
                node = conf.edt.chosen_node('zephyr,code-partition')
            return hex(node.regs[0].addr)
        except Exception as e:
            raise RuntimeError('environment uses {address} but the flash address '
                               f'could not be read from the build: {e}') from e

    def _flash_with_script(self, drv, image):
        from labgrid.util.managedfile import ManagedFile

        mf = ManagedFile(image, drv.device)
        mf.sync_to_resource()
        remote_image = mf.get_remote_path()
        subst = {'{image}': remote_image}
        if any('{address}' in a for a in drv.args):
            subst['{address}'] = self._flash_address()
        args = []
        for a in drv.args:
            for key, value in subst.items():
                a = a.replace(key, value)
            args.append(a)
        if '{image}' not in ''.join(drv.args):
            # no placeholder: pass the image as the last argument
            args.append(remote_image)
        drv.flash(args=args, timeout=self.timeout)

    def _reset_target(self, target):
        """Best effort reset: ResetProtocol, then PowerProtocol, else rely on
        the flasher having reset the target (e.g. OpenOCD 'reset run')."""
        from labgrid.exceptions import NoDriverFoundError

        for proto, action in (('ResetProtocol', 'reset'), ('PowerProtocol', 'cycle')):
            try:
                drv = target.get_driver(proto)
            except NoDriverFoundError:
                continue
            self.logger.info(f'resetting target via {proto}')
            getattr(drv, action)()
            return
        self.logger.info('no reset/power driver on target, relying on flasher reset')

    def _resolve_env(self):
        if self.env_file:
            return
        try:
            self.env_file = common.resolve_env(None, self.place, env_dir=self.env_dir)
        except ValueError as e:
            raise RuntimeError(str(e)) from None
        self.logger.info(f'labgrid environment {self.env_file} (zephyr_env tag of '
                         f'place {self.place})')

    def do_run(self, command, **kwargs):
        try:
            from labgrid import Environment
            from labgrid.exceptions import NoDriverFoundError, NoResourceFoundError
        except ImportError as e:
            raise RuntimeError('labgrid runner needs the labgrid python package '
                               'in the environment running west') from e

        self._resolve_env()
        image = self._image()
        self.logger.info(f'flashing {image} via labgrid place {self.place}')

        lock = None
        if self.acquire:
            # Twister terminates west flash on its flash timeout. Turn the
            # signal into an exception so the place is released below.
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
            lock = common.PlaceLock(self.place, common.coordinator_for_env(self.env_file),
                                    log=self.logger.info)
            try:
                lock.acquire()
            except common.PlaceLockError as e:
                raise RuntimeError(str(e)) from None

        try:
            if self.wait_console > 0:
                coordinator = common.coordinator_for_env(self.env_file)
                if common.wait_console_ready(self.place, coordinator, self.wait_console):
                    self.logger.info('console bridge is open')
                else:
                    self.logger.warning(f'no console bridge for place {self.place} '
                                        f'after {self.wait_console:g} s, flashing anyway')
            self._flash(image, Environment, NoDriverFoundError, NoResourceFoundError)
        finally:
            if lock:
                try:
                    lock.release()
                except common.PlaceLockError as e:
                    self.logger.warning(str(e))

    def _flash(self, image, Environment, NoDriverFoundError, NoResourceFoundError):
        # labgrid environment files refer to the place as !template $LG_PLACE
        os.environ['LG_PLACE'] = self.place
        try:
            env = Environment(config_file=self.env_file)
            target = env.get_target()
        except Exception as e:
            raise RuntimeError(f'could not load labgrid environment {self.env_file}: '
                               f'{e}') from e

        try:
            try:
                if self.power_cycle:
                    try:
                        power = target.get_driver('PowerProtocol')
                    except NoDriverFoundError:
                        raise RuntimeError('--power-cycle needs a PowerProtocol driver '
                                           f'in {self.env_file}') from None
                    power.cycle()

                flasher, kind = self._get_flasher(target)
                if self.timeout is not None and hasattr(flasher, 'interface'):
                    flasher.interface.timeout = self.timeout
                if kind == 'bootstrap':
                    flasher.load(image)
                else:
                    self._flash_with_script(flasher, image)
                target.deactivate(flasher)

                if self.reset:
                    self._reset_target(target)
            except NoResourceFoundError as e:
                raise RuntimeError(
                    f'labgrid place "{self.place}" has no matching resource: {e}. '
                    'Is the place acquired by you and the exporter running?') from e
        finally:
            target.cleanup()

# SPDX-License-Identifier: Apache-2.0
"""West runner that flashes and resets through a labgrid place.

The runner is a thin client. It uses a place the user holds (``--dev-id``,
``$LG_PLACE``, or the one place of the user whose ``zephyr_platform`` tag
fits the build), resolves its labgrid environment (``--env``,
``$ZEPHYR_LABGRID_ENV``, or the ``zephyr_env`` tag of the place) and asks the
flash driver of the target to load the image. The actual
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

import argparse
import os
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

# Under Twister, how long to look for a starting labgrid-pty, and how long
# to wait for its console to open.
TWISTER_GRACE = 5.0
AUTO_CONSOLE_WAIT = 30.0


class LabgridBinaryRunner(ZephyrBinaryRunner):
    """Flash a Zephyr image through a labgrid place."""

    def __init__(self, cfg: RunnerConfig, env_file, place, driver_name=None,
                 power_cycle=False, timeout=None, acquire=False, acquire_wait=0.0,
                 wait_console=None, env_dir=None, ignore_platform=False):
        super().__init__(cfg)
        self.env_file = env_file
        self.env_dir = env_dir
        self.place = place
        self.driver_name = driver_name
        self.power_cycle = power_cycle
        self.timeout = timeout
        self.acquire = acquire
        self.acquire_wait = acquire_wait
        self.ignore_platform = ignore_platform
        self.wait_console = wait_console
        self.flash_before = False   # from the place tags, when they are read

    @classmethod
    def name(cls):
        return 'labgrid'

    @classmethod
    def capabilities(cls):
        # No reset=True: west would then add --reset to every flash, and the
        # flashers reset the board themselves.
        return RunnerCaps(commands={'flash', 'reset'}, dev_id=True, file=True,
                          dry_run=True)

    @classmethod
    def dev_id_help(cls) -> str:
        return ('labgrid place name (defaults to $LG_PLACE, then to the one place '
                'you hold whose zephyr_platform tag fits the build)')

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
                            help='time limit for the flash or reset script of the '
                                 'environment')
        # Not for users: hardware maps from labgrid-twister-hwmap pass it, so
        # that Twister acquires each place for a test and releases it after.
        parser.add_argument('--acquire', action='store_true', help=argparse.SUPPRESS)
        parser.add_argument('--acquire-wait', type=float, default=0.0, help=argparse.SUPPRESS)
        parser.add_argument('--ignore-platform', action='store_true',
                            help='flash even when the zephyr_platform tag of the '
                                 'place does not fit the build')
        parser.add_argument('--wait-console', type=float, default=None, metavar='SECONDS',
                            help='wait up to SECONDS for a labgrid-pty on this host '
                                 'to have the console of the place open before '
                                 'flashing. Default: wait when one is starting, as '
                                 'under Twister. 0 never waits')

    @classmethod
    def do_create(cls, cfg: RunnerConfig, args):
        # Without an environment file, do_run takes it from the place tags,
        # so that creating the runner never talks to the coordinator.
        env_file = args.env or common.default_env()
        # Without a place, do_run picks the one the user holds for this board.
        place = args.dev_id or common.default_place()
        runner = LabgridBinaryRunner(cfg, env_file=env_file, place=place,
                                     env_dir=args.env_dir,
                                     driver_name=args.driver,
                                     power_cycle=args.power_cycle,
                                     timeout=args.timeout,
                                     acquire=args.acquire,
                                     acquire_wait=args.acquire_wait,
                                     wait_console=args.wait_console,
                                     ignore_platform=args.ignore_platform)
        # west does not apply --dry-run itself; every runner reads it.
        runner.dry_run = args.dry_run
        return runner

    def _image(self) -> str:
        if self.cfg.file is not None:
            return self.cfg.file
        for candidate in (self.cfg.hex_file, self.cfg.bin_file, self.cfg.elf_file):
            if candidate and Path(candidate).is_file():
                return candidate
        raise RuntimeError('no image found in build directory')

    def _get_flasher(self, target):
        """Return (driver, kind) where kind is 'bootstrap' or 'script'."""
        try:
            return common.select_flasher(target, self.driver_name)
        except LookupError as e:
            raise RuntimeError(f'{e} in {self.env_file}. Check the drivers section and '
                               f'the resources of place "{self.place}"') from None

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
        """Reset through ResetProtocol, then a FlashScriptDriver named
        "reset", then PowerProtocol, then OpenOCD."""
        from labgrid.driver import FlashScriptDriver
        from labgrid.exceptions import NoDriverFoundError

        try:
            drv = target.get_driver('ResetProtocol')
        except NoDriverFoundError:
            pass
        else:
            self.logger.info('resetting target via ResetProtocol')
            drv.reset()
            return
        # Boards that only a vendor tool can reset (J-Link, esptool): the lab
        # owner adds the command as a FlashScriptDriver named "reset".
        try:
            drv = target.get_driver(FlashScriptDriver, name=common.RESET_SCRIPT)
        except NoDriverFoundError:
            pass
        else:
            self.logger.info('resetting target via the reset script')
            drv.flash(timeout=self.timeout)
            target.deactivate(drv)
            return
        try:
            drv = target.get_driver('PowerProtocol')
        except NoDriverFoundError:
            pass
        else:
            self.logger.info('resetting target via PowerProtocol')
            drv.cycle()
            return
        try:
            from labgrid.driver import OpenOCDDriver
            drv = target.get_driver(OpenOCDDriver)
        except NoDriverFoundError:
            drv = None
        if drv is not None:
            self.logger.info('resetting target via OpenOCD')
            drv.execute(['init', 'reset run', 'shutdown'])
            target.deactivate(drv)
            return
        raise RuntimeError(f'can not reset place "{self.place}": {self.env_file} has '
                           'no ResetProtocol, reset script, PowerProtocol or OpenOCD '
                           'driver')

    def _board(self):
        conf = self.build_conf
        target = conf.get('CONFIG_BOARD_TARGET') if 'CONFIG_BOARD_TARGET' in conf else None
        board = conf.get('CONFIG_BOARD') if 'CONFIG_BOARD' in conf else None
        return target, board

    def _resolve_place(self):
        """Pick the place and its environment file.

        One coordinator query gives the owner, the tags and, without a
        --dev-id, the place of the user that fits the build.
        """
        if self.acquire and self.place and self.env_file:
            # A generated hardware map: it took the place and the file from
            # the tags, and the place is acquired already.
            return
        coordinator = common.coordinator_for_env(self.env_file)
        try:
            places = common.lab_places(coordinator)
        except common.PlaceLookupError as e:
            raise RuntimeError(str(e)) from None
        target, board = self._board()
        try:
            if self.place:
                if not (self.acquire and self.dry_run):
                    common.check_owned(places, self.place)
            else:
                if not target:
                    raise common.PlaceSelectError(
                        'the build has no CONFIG_BOARD_TARGET, pass --dev-id')
                self.place = common.select_owned_place(places, target, board)
                self.logger.info(f'using place {self.place}, the one you hold '
                                 f'for {target}')
        except common.PlaceSelectError as e:
            raise RuntimeError(str(e)) from None

        tags = places[self.place]['tags']
        self.flash_before = common.tag_is_true(tags.get('zephyr_flash_before'))
        tag = tags.get('zephyr_platform')
        if (tag and target and not self.ignore_platform
                and not common.platform_matches(tag, target, board)):
            raise RuntimeError(f'place {self.place} is for {tag}, the build is for '
                               f'{target}. Pass --ignore-platform to flash anyway')

        if not self.env_file:
            try:
                self.env_file = common.resolve_env(None, self.place, env_dir=self.env_dir,
                                                   tags=tags)
            except ValueError as e:
                raise RuntimeError(str(e)) from None
            self.logger.info(f'labgrid environment {self.env_file} (zephyr_env tag of '
                             f'place {self.place})')

    def _describe(self, command):
        """--dry-run: say what would happen, change nothing."""
        log = self.logger.info
        log(f'would use labgrid place {self.place} with environment {self.env_file}')
        if self.acquire:
            log(f'would acquire place {self.place} and release it when west exits')
        if command == 'reset':
            log('would reset via ResetProtocol, the reset script, PowerProtocol or '
                'OpenOCD')
            return
        if self.wait_console is None:
            log('would wait for labgrid-pty when one is starting')
        elif self.wait_console > 0:
            log(f'would wait up to {self.wait_console:g} s for labgrid-pty')
        if self.power_cycle:
            log('would power cycle the place first')
        driver = self.driver_name or 'the BootstrapProtocol driver, else FlashScriptDriver'
        log(f'would flash {self._image()} with {driver}')

    def do_run(self, command, **kwargs):
        try:
            import labgrid  # noqa: F401
        except ImportError as e:
            raise RuntimeError('labgrid runner needs the labgrid python package '
                               'in the environment running west') from e

        if self.acquire and not self.dry_run:
            if not self.place:
                raise RuntimeError('--acquire needs --dev-id')
            # Twister terminates west flash on its flash timeout: release
            # the place then, as atexit does on a normal exit.
            common.release_places_on_sigterm()
            try:
                common.hold_place_for_process(
                    self.place, common.coordinator_for_env(self.env_file),
                    log=self.logger.info, wait=self.acquire_wait)
            except common.PlaceLockError as e:
                raise RuntimeError(str(e)) from None

        self._resolve_place()
        if self.dry_run:
            self._describe(command)
            return

        if command == 'flash':
            image = self._image()
            self.logger.info(f'flashing {image} via labgrid place {self.place}')
        else:
            image = None
            self.logger.info(f'resetting via labgrid place {self.place}')

        if command == 'flash':
            self._wait_for_console()
        self._run_on_target(command, image)

    def _wait_for_console(self):
        """Twister starts labgrid-pty and west flash at the same time, and
        the remote console takes seconds to open. Flashing first would
        lose the boot output, so wait for the console when a labgrid-pty
        for the place is starting. An interactive west flash, without
        one, does not wait."""
        coordinator = common.coordinator_for_env(self.env_file)
        if self.flash_before and common.console_expected(self.place, coordinator):
            raise RuntimeError(f'place {self.place} flashes over its console port, '
                               'and a labgrid-pty has the console open. Close it first')
        timeout = self.wait_console
        if timeout is None:
            grace = TWISTER_GRACE if common.started_by_twister() else 0.0
            if not common.console_expected(self.place, coordinator, grace):
                return
            timeout = AUTO_CONSOLE_WAIT
        if timeout <= 0:
            return
        if common.wait_console_ready(self.place, coordinator, timeout):
            self.logger.info('console bridge is open')
        else:
            self.logger.warning(f'no console bridge for place {self.place} '
                                f'after {timeout:g} s, flashing anyway')

    def _run_on_target(self, command, image):
        from labgrid import Environment
        from labgrid.exceptions import NoDriverFoundError, NoResourceFoundError

        # labgrid environment files refer to the place as !template $LG_PLACE.
        # Restore the variable afterwards: west runs the runner once per
        # sysbuild image in one process, and the next image may have another
        # place.
        old_place = os.environ.get('LG_PLACE')
        os.environ['LG_PLACE'] = self.place
        try:
            env = Environment(config_file=self.env_file)
            target = env.get_target()
        except Exception as e:
            raise RuntimeError(f'could not load labgrid environment {self.env_file}: '
                               f'{e}') from e
        finally:
            if old_place is None:
                os.environ.pop('LG_PLACE', None)
            else:
                os.environ['LG_PLACE'] = old_place

        try:
            try:
                if command == 'reset':
                    self._reset_target(target)
                    return

                if self.power_cycle:
                    try:
                        power = target.get_driver('PowerProtocol')
                    except NoDriverFoundError:
                        raise RuntimeError('--power-cycle needs a PowerProtocol driver '
                                           f'in {self.env_file}') from None
                    power.cycle()

                flasher, kind = self._get_flasher(target)
                if kind == 'bootstrap':
                    flasher.load(image)
                else:
                    self._flash_with_script(flasher, image)
                target.deactivate(flasher)
            except NoResourceFoundError as e:
                raise RuntimeError(
                    f'labgrid place "{self.place}" has no matching resource: {e}. '
                    'Is the exporter running?') from e
        finally:
            target.cleanup()

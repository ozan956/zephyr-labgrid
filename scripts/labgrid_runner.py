# SPDX-License-Identifier: Apache-2.0
"""West runner that flashes through a labgrid place.

The runner is a thin client: it resolves a labgrid environment (``--env`` or
``$LG_ENV``), points it at a place (``--dev-id`` or ``$LG_PLACE``) and asks the
target's BootstrapProtocol driver to load the image. The actual flashing tool
(OpenOCD, pyOCD, a vendor script via FlashScriptDriver, ...) runs wherever the
labgrid exporter decides, usually on the exporter host next to the probe.
"""

import os
import sys
from pathlib import Path

from runners.core import FileType, RunnerCaps, RunnerConfig, ZephyrBinaryRunner


class LabgridBinaryRunner(ZephyrBinaryRunner):
    """Flash a Zephyr image through a labgrid place."""

    def __init__(self, cfg: RunnerConfig, env_file, place, driver_name=None,
                 power_cycle=False, reset=False, timeout=None):
        super().__init__(cfg)
        self.env_file = env_file
        self.place = place
        self.driver_name = driver_name
        self.power_cycle = power_cycle
        self.reset = reset
        self.timeout = timeout

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
                            help='labgrid environment YAML (defaults to $ZEPHYR_LABGRID_ENV, then $LG_ENV)')
        parser.add_argument('--driver', default=None,
                            help='name of the BootstrapProtocol driver to use '
                                 '(default: the only/first one on the target)')
        parser.add_argument('--power-cycle', action='store_true',
                            help='power cycle the place before flashing '
                                 '(needs a PowerProtocol driver)')
        parser.add_argument('--timeout', type=float, default=None,
                            help='override labgrid resource wait timeout')
        parser.set_defaults(reset=False)

    @classmethod
    def do_create(cls, cfg: RunnerConfig, args):
        # ZEPHYR_LABGRID_ENV is preferred over LG_ENV: LG_ENV also activates
        # labgrid's own pytest plugin inside pytest-twister-harness runs.
        env_file = (args.env or os.environ.get('ZEPHYR_LABGRID_ENV')
                    or os.environ.get('LG_ENV'))
        place = args.dev_id or os.environ.get('LG_PLACE')
        if not env_file:
            raise ValueError('labgrid runner needs --env, $ZEPHYR_LABGRID_ENV or $LG_ENV')
        if not place:
            raise ValueError('labgrid runner needs --dev-id or $LG_PLACE')
        return LabgridBinaryRunner(cfg, env_file=env_file, place=place,
                                   driver_name=args.driver,
                                   power_cycle=args.power_cycle,
                                   reset=args.reset, timeout=args.timeout)

    def _image(self) -> str:
        if self.cfg.file is not None:
            return self.cfg.file
        for candidate in (self.cfg.hex_file, self.cfg.bin_file, self.cfg.elf_file):
            if candidate and Path(candidate).is_file():
                return candidate
        raise RuntimeError('no image found in build directory')

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

    def do_run(self, command, **kwargs):
        try:
            from labgrid import Environment
        except ImportError as e:
            raise RuntimeError('labgrid runner needs the labgrid python package '
                               'in the environment running west') from e

        image = self._image()
        self.logger.info(f'flashing {image} via labgrid place {self.place}')

        # labgrid environment files refer to the place as !template $LG_PLACE
        os.environ['LG_PLACE'] = self.place
        env = Environment(config_file=self.env_file)
        target = env.get_target()
        try:
            if self.power_cycle:
                power = target.get_driver('PowerProtocol')
                power.cycle()

            flasher = target.get_driver('BootstrapProtocol', name=self.driver_name)
            if self.timeout is not None and hasattr(flasher, 'interface'):
                flasher.interface.timeout = self.timeout
            flasher.load(image)
            target.deactivate(flasher)

            if self.reset:
                self._reset_target(target)
        finally:
            target.cleanup()

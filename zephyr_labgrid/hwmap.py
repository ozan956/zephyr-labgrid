# SPDX-License-Identifier: Apache-2.0
"""Generate a Twister hardware map from labgrid places.

Every place with a ``zephyr_platform`` tag becomes one DUT entry that flashes
with the ``labgrid`` west runner and uses ``labgrid-pty`` for the console.

Tags read from the place:
  zephyr_platform   Zephyr board target, e.g. stm32f746g_disco/stm32f746xx (required)
  zephyr_env        labgrid environment file for this place; relative names are
                    resolved against --env-dir. Falls back to --env.
  zephyr_fixtures   comma separated Twister fixtures, e.g. gpio_loopback,i2c_bus
  zephyr_flash_timeout  seconds for one flash; without it Twister's
                    --device-flash-timeout applies. --wait is added to it.
  zephyr_flash_before   true/false; flash before opening the console. Needed
                    when the console port is also the flash port (ESP32 with a
                    USB-UART bridge).
  zephyr_pty_args   comma separated extra arguments for labgrid-pty, e.g.
                    --reset-rts for boards whose reset line is wired to RTS.

Usage:
  labgrid-twister-hwmap [-x COORDINATOR] [-p PLATFORM]... [--place NAME]...
                        [--env FILE] [--env-dir DIR] [--force-env FILE]
                        [--wait SECONDS] [--pty NAME] [-o hwmap.yaml]

Write the map once, like twister --generate-hardware-map for boards on the
desk, and run Twister with it as usual. Each test acquires its place when
it starts and releases it when it ends; a place you hold already stays
yours. When someone else holds a place, the test waits up to --wait
seconds (default 300) for it.
"""

import argparse
import os
import sys

import yaml

from . import common

PROG = 'labgrid-twister-hwmap'
TRUE_WORDS = ('1', 'true', 'yes', 'on')
DEFAULT_WAIT = 300
# Twister's default --device-flash-timeout, for places without the tag
TWISTER_FLASH_TIMEOUT = 60


def tag_is_true(value):
    return str(value or '').strip().lower() in TRUE_WORDS


def split_list(value):
    return [a.strip() for a in str(value or '').split(',') if a.strip()]


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-x', '--coordinator', default=common.default_coordinator(),
                        help='coordinator HOST[:PORT] (default $LG_COORDINATOR)')
    parser.add_argument('-p', '--platform', action='append', default=[],
                        help='only places whose zephyr_platform tag fits this '
                             'board target, may be repeated')
    parser.add_argument('--place', action='append', default=[],
                        help='only this place, may be repeated')
    parser.add_argument('--env', default=os.environ.get('ZEPHYR_LABGRID_ENV'),
                        help='labgrid environment file used when a place has no '
                             'zephyr_env tag (default $ZEPHYR_LABGRID_ENV)')
    parser.add_argument('--force-env', default=None, metavar='FILE',
                        help='use this environment file for every place and '
                             'ignore zephyr_env tags')
    parser.add_argument('--env-dir', default=common.default_env_dir(),
                        help='directory for relative zephyr_env tag values '
                             '(default $ZEPHYR_LABGRID_ENV_DIR, else the directory '
                             'of --env)')
    parser.add_argument('--pty', default='labgrid-pty',
                        help='console bridge command (default: labgrid-pty from PATH)')
    parser.add_argument('--wait-console', type=float, default=None, metavar='SECONDS',
                        help='how long the runner waits for the console before '
                             'flashing (default: it waits when Twister opens the '
                             'console first, see the runner)')
    parser.add_argument('--wait', type=float, default=DEFAULT_WAIT, metavar='SECONDS',
                        help='how long a test waits for a place that someone else '
                             f'holds (default {DEFAULT_WAIT:g}, 0 fails at once)')
    parser.add_argument('-o', '--output', default='-', help='output file (default stdout)')
    return parser


def resolve_env(name, place_tags, args):
    """Environment file for a place, absolute. Raises SystemExit with a
    message when it can not be decided."""
    env = args.force_env or place_tags.get('zephyr_env') or args.env
    if not env:
        sys.exit(f'{PROG}: place {name} has no zephyr_env tag and no --env given')
    if not os.path.isabs(env):
        env_dir = args.env_dir or (os.path.dirname(os.path.abspath(args.env))
                                   if args.env else None)
        if env_dir is None:
            sys.exit(f'{PROG}: zephyr_env tag of {name} is the relative path '
                     f'"{env}"; set ZEPHYR_LABGRID_ENV_DIR or give --env-dir')
        env = os.path.join(env_dir, env)
    return os.path.abspath(env)


def make_entry(name, place, args):
    """Build the hardware map entry for one place (an entry of
    common.lab_places), or None when the place has no zephyr_platform tag."""
    tags = place['tags']
    platform = tags.get('zephyr_platform')
    if not platform:
        return None
    env = resolve_env(name, tags, args)
    if not os.path.isfile(env):
        print(f'warning: environment file {env} for place {name} does not exist',
              file=sys.stderr)

    flash_before = tag_is_true(tags.get('zephyr_flash_before'))
    # --acquire: the runner and labgrid-pty of a test acquire the place
    # together and the last of them releases it.
    lock = ['--acquire'] + ([f'--acquire-wait={args.wait:g}'] if args.wait > 0 else [])
    runner_params = [f'--dev-id={name}', f'--env={env}'] + lock
    # A board flashed before the console opens has nothing to wait for. For
    # the others the runner decides, as it knows Twister's --flash-before.
    if flash_before:
        runner_params.append('--wait-console=0')
    elif args.wait_console is not None:
        runner_params.append(f'--wait-console={args.wait_console:g}')
    pty = [args.pty, '-p', name, '-e', env] + split_list(tags.get('zephyr_pty_args')) + lock
    entry = {
        'connected': True,
        'id': name,
        'platform': platform,
        'product': 'labgrid',
        'runner': 'labgrid',
        'runner_params': runner_params,
        'serial_pty': ','.join(pty),
    }
    if tags.get('zephyr_flash_timeout') or args.wait > 0:
        # Twister's flash timeout covers the wait for a busy place too
        flash_timeout = int(tags.get('zephyr_flash_timeout') or TWISTER_FLASH_TIMEOUT)
        entry['flash_timeout'] = flash_timeout + int(args.wait)
    if flash_before:
        entry['flash_before'] = True
    fixtures = split_list(tags.get('zephyr_fixtures'))
    if fixtures:
        entry['fixtures'] = fixtures
    if place.get('acquired') and not common.owned_by(place):
        entry['notes'] = f'acquired by {place["acquired"]} when the map was written'
    return entry


def wanted(name, place, args):
    """Does the place pass the --place and --platform filters?"""
    if args.place and name not in args.place:
        return False
    if args.platform:
        tag = place['tags'].get('zephyr_platform')
        return any(common.platform_selects(tag, p) for p in args.platform)
    return True


def generate(places, args):
    """Return (entries, skipped) for the dict of common.lab_places.
    ``skipped`` maps a place name to the reason it is not in the map."""
    entries = []
    skipped = {}
    for name in sorted(places):
        place = places[name]
        if not wanted(name, place, args):
            continue
        if not place['tags'].get('zephyr_platform'):
            skipped[name] = 'no zephyr_platform tag'
            continue
        entries.append(make_entry(name, place, args))
    return entries, skipped


def dump(entries, coordinator):
    header = f'# Twister hardware map generated by {PROG} from {coordinator}\n'
    return header + yaml.safe_dump(entries, sort_keys=False, default_flow_style=False)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        places = common.lab_places(args.coordinator)
    except common.PlaceLookupError as e:
        sys.exit(f'{PROG}: {e}')

    entries, skipped = generate(places, args)
    text = dump(entries, args.coordinator)
    if args.output == '-':
        sys.stdout.write(text)
    else:
        with open(args.output, 'w') as f:
            f.write(text)
        print(f'wrote {len(entries)} DUT(s) to {args.output}', file=sys.stderr)
    for name, reason in skipped.items():
        print(f'skipped place {name}: {reason}', file=sys.stderr)


if __name__ == '__main__':
    main()

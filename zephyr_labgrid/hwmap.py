# SPDX-License-Identifier: Apache-2.0
"""Generate a Twister hardware map from labgrid places.

Every place with a ``zephyr_platform`` tag becomes one DUT entry that flashes
with the ``labgrid`` west runner and uses ``labgrid-pty`` for the console.

Tags read from the place:
  zephyr_platform   Zephyr board target, e.g. stm32f746g_disco/stm32f746xx (required)
  zephyr_env        labgrid environment file for this place; relative names are
                    resolved against --env-dir. Falls back to --env.
  zephyr_fixtures   comma separated Twister fixtures, e.g. gpio_loopback,i2c_bus
  zephyr_flash_timeout  seconds, default 120
  zephyr_flash_before   true/false; flash before opening the console. Needed
                    when the console port is also the flash port (ESP32 with a
                    USB-UART bridge).
  zephyr_pty_args   comma separated extra arguments for labgrid-pty, e.g.
                    --reset-rts for boards whose reset line is wired to RTS.

Usage:
  labgrid-twister-hwmap [-x COORDINATOR] [--env FILE] [--env-dir DIR]
                        [--force-env FILE] [--pty NAME] [--acquire | --hooks DIR]
                        [-o hwmap.yaml]

With --acquire, the runner and labgrid-pty get the --acquire flag: each of
them takes the place while it runs and gives it back afterwards. With
--hooks DIR, a pre and post script per place is written there instead. They
acquire and release the place around the whole test. Twister passes no
arguments to these scripts, so one small file per place is the only way to
make them place specific.
"""

import argparse
import os
import stat
import sys

import yaml

from . import common

PROG = 'labgrid-twister-hwmap'
TRUE_WORDS = ('1', 'true', 'yes', 'on')


def tag_is_true(value):
    return str(value or '').strip().lower() in TRUE_WORDS


def split_list(value):
    return [a.strip() for a in str(value or '').split(',') if a.strip()]


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-x', '--coordinator', default=common.default_coordinator(),
                        help='coordinator HOST[:PORT] (default $LG_COORDINATOR)')
    parser.add_argument('--env', default=os.environ.get('ZEPHYR_LABGRID_ENV'),
                        help='labgrid environment file used when a place has no '
                             'zephyr_env tag (default $ZEPHYR_LABGRID_ENV)')
    parser.add_argument('--force-env', default=None, metavar='FILE',
                        help='use this environment file for every place and '
                             'ignore zephyr_env tags')
    parser.add_argument('--env-dir', default=None,
                        help='directory for relative zephyr_env tag values '
                             '(default: directory of --env)')
    parser.add_argument('--pty', default='labgrid-pty',
                        help='console bridge command (default: labgrid-pty from PATH)')
    parser.add_argument('--acquire', action='store_true',
                        help='add --acquire to the runner and to labgrid-pty')
    parser.add_argument('--wait-console', type=float, default=30, metavar='SECONDS',
                        help='runner waits this long for the console bridge before '
                             'flashing when flash_before is false (default 30, 0 '
                             'disables)')
    parser.add_argument('--hooks', default=None, metavar='DIR',
                        help='write per place acquire/release scripts into DIR and '
                             'reference them as pre_script/post_script')
    parser.add_argument('--include-unavailable', action='store_true',
                        help='also list places that are acquired by someone else')
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
                     f'"{env}"; give --env-dir or --env')
        env = os.path.join(env_dir, env)
    return os.path.abspath(env)


def make_entry(name, place, args, hooks_writer=None):
    """Build the hardware map entry for one place, or None when the place has
    no zephyr_platform tag."""
    tags = place.tags
    platform = tags.get('zephyr_platform')
    if not platform:
        return None
    env = resolve_env(name, tags, args)
    if not os.path.isfile(env):
        print(f'warning: environment file {env} for place {name} does not exist',
              file=sys.stderr)

    flash_before = tag_is_true(tags.get('zephyr_flash_before'))
    runner_params = [f'--dev-id={name}', f'--env={env}']
    if not flash_before and args.wait_console > 0:
        # Twister starts labgrid-pty and west flash together; let the flash
        # wait until the console is open so no boot output is lost.
        runner_params.append(f'--wait-console={args.wait_console:g}')
    pty = [args.pty, '-p', name, '-e', env] + split_list(tags.get('zephyr_pty_args'))
    if args.acquire:
        runner_params.append('--acquire')
        pty.append('--acquire')
    entry = {
        'connected': True,
        'id': name,
        'platform': platform,
        'product': 'labgrid',
        'runner': 'labgrid',
        'runner_params': runner_params,
        'serial_pty': ','.join(pty),
        'flash_timeout': int(tags.get('zephyr_flash_timeout', 120)),
    }
    if flash_before:
        entry['flash_before'] = True
    fixtures = split_list(tags.get('zephyr_fixtures'))
    if fixtures:
        entry['fixtures'] = fixtures
    if place.acquired and not args.include_unavailable:
        entry['notes'] = f'acquired by {place.acquired}'
    if hooks_writer:
        entry['pre_script'] = hooks_writer(name, 'pre', 'acquire')
        entry['post_script'] = hooks_writer(name, 'post', 'release')
    return entry


def write_hook(directory, coordinator, place, kind, action):
    os.makedirs(directory, exist_ok=True)
    path = os.path.abspath(os.path.join(directory, f'{place}-{kind}'))
    with open(path, 'w') as f:
        f.write('#!/bin/sh\n'
                f'# generated by {PROG}: {kind} script for {place}\n'
                f'exec labgrid-client -x {coordinator} -p {place} {action}\n')
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def generate(places, args):
    """Return (entries, skipped) for a dict name -> place."""
    hooks_writer = None
    if args.hooks:
        def hooks_writer(name, kind, action):
            return write_hook(args.hooks, args.coordinator, name, kind, action)
    entries = []
    skipped = []
    for name in sorted(places):
        entry = make_entry(name, places[name], args, hooks_writer)
        if entry is None:
            skipped.append(name)
        else:
            entries.append(entry)
    return entries, skipped


def dump(entries, coordinator):
    header = f'# Twister hardware map generated by {PROG} from {coordinator}\n'
    return header + yaml.safe_dump(entries, sort_keys=False, default_flow_style=False)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.acquire and args.hooks:
        parser.error('--acquire and --hooks lock the place in two different ways, pick one')

    try:
        from labgrid.remote.client import start_session
    except ImportError:
        sys.exit(f'{PROG}: python package labgrid is missing')

    try:
        session = start_session(args.coordinator)
    except Exception as e:
        sys.exit(f'{PROG}: can not reach coordinator {args.coordinator}: {e}')

    entries, skipped = generate(session.places, args)
    text = dump(entries, args.coordinator)
    if args.output == '-':
        sys.stdout.write(text)
    else:
        with open(args.output, 'w') as f:
            f.write(text)
        print(f'wrote {len(entries)} DUT(s) to {args.output}', file=sys.stderr)
    if skipped:
        print(f'skipped {len(skipped)} place(s) without zephyr_platform tag: '
              f'{", ".join(skipped)}', file=sys.stderr)


if __name__ == '__main__':
    main()

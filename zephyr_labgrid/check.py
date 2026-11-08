# SPDX-License-Identifier: Apache-2.0
"""Check a zephyr-labgrid setup before the first Twister run.

Goes through the things that usually go wrong on a new setup and prints one
line per check: ``ok``, ``warn`` or ``FAIL``. Exit code 1 when a check
failed.

Checks:
  python      labgrid, pyserial-labgrid and PyYAML importable
  path        labgrid-pty and labgrid-client on PATH
  env vars    environment file from --env, ZEPHYR_LABGRID_ENV or the zephyr_env
              tag; LG_ENV not set (pytest plugin trap)
  coordinator reachable, lists the places
  place       exists, acquired by you, zephyr_* tags
  env file    loads, has a console driver and a flash driver, image files exist
  exporter    flash tool found on the exporter host (--tool, openocd by default
              for OpenOCDDriver)
  console     opens, RFC2217 purge answered (ser2net 4.6.0 problem)
  hwmap       entries match the coordinator (--hwmap)
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

from . import common

PROG = 'labgrid-twister-check'


class Report:
    def __init__(self, out=sys.stdout):
        self.out = out
        self.failed = 0
        self.warned = 0

    def ok(self, msg):
        print(f'ok    {msg}', file=self.out)

    def warn(self, msg):
        self.warned += 1
        print(f'warn  {msg}', file=self.out)

    def fail(self, msg):
        self.failed += 1
        print(f'FAIL  {msg}', file=self.out)

    def info(self, msg):
        print(f'      {msg}', file=self.out)


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-x', '--coordinator', default=None,
                        help='coordinator HOST[:PORT] (default: coordinator_address '
                             'of the environment file, then $LG_COORDINATOR)')
    parser.add_argument('-e', '--env', default=common.default_env(),
                        help='labgrid environment file (default $ZEPHYR_LABGRID_ENV, '
                             'then the zephyr_env tag of the place)')
    parser.add_argument('--env-dir', default=None,
                        help='directory for a relative zephyr_env tag '
                             '(default $ZEPHYR_LABGRID_ENV_DIR)')
    parser.add_argument('-p', '--place', default=common.default_place(),
                        help='labgrid place (default $LG_PLACE)')
    parser.add_argument('--tool', action='append', default=[], metavar='NAME',
                        help='flash tool that must exist on the exporter host, '
                             'may be repeated (default: openocd for OpenOCDDriver)')
    parser.add_argument('--hwmap', default=None, metavar='FILE',
                        help='Twister hardware map to check against the coordinator')
    parser.add_argument('--no-console', action='store_true',
                        help='do not open the console')
    parser.add_argument('--pty', default='labgrid-pty',
                        help='console bridge command that must be on PATH')
    return parser


# -- individual checks -------------------------------------------------------

def check_python(rep):
    ok = True
    for mod, pkg in (('labgrid', 'labgrid'), ('serial', 'pyserial-labgrid'), ('yaml', 'PyYAML')):
        try:
            m = __import__(mod)
            version = getattr(m, '__version__', None) or getattr(m, 'VERSION', '')
            rep.ok(f'python package {pkg} {version}'.rstrip())
        except ImportError:
            rep.fail(f'python package {pkg} is missing: pip install {pkg}')
            ok = False
    if ok and not labgrid_is_new_enough():
        rep.fail('labgrid is too old: zephyr-labgrid needs labgrid master. '
                 f'pip install "{LABGRID_MASTER}"')
        ok = False
    return ok


LABGRID_MASTER = 'labgrid @ git+https://github.com/labgrid-project/labgrid.git'


def labgrid_is_new_enough():
    """labgrid master has features no release has yet (26.0.1): the runner
    passes a timeout to FlashScriptDriver.flash()."""
    import inspect
    try:
        from labgrid.driver import FlashScriptDriver
    except ImportError:
        return False
    return 'timeout' in inspect.signature(FlashScriptDriver.flash).parameters


def check_path(rep, pty):
    for name in (pty, 'labgrid-client'):
        where = shutil.which(name)
        if where:
            rep.ok(f'{name} found at {where}')
        else:
            rep.fail(f'{name} not on PATH (pip install this module or add scripts/ '
                     'to PATH)')


def check_env_vars(rep, args):
    if os.environ.get('ZEPHYR_LABGRID_ENV'):
        rep.ok(f'ZEPHYR_LABGRID_ENV={os.environ["ZEPHYR_LABGRID_ENV"]}')
    elif args.env:
        rep.ok(f'environment file {args.env} from --env')
    elif args.place:
        rep.info('no --env or ZEPHYR_LABGRID_ENV: the zephyr_env tag of the place is used')
    else:
        rep.fail('no environment file: pass --place (zephyr_env tag), --env or set '
                 'ZEPHYR_LABGRID_ENV')
    if os.environ.get('LG_ENV'):
        rep.warn('LG_ENV is set. It turns on the labgrid pytest plugin inside '
                 'Twister pytest suites. Use ZEPHYR_LABGRID_ENV instead.')
    if os.environ.get('LG_COORDINATOR'):
        rep.ok(f'LG_COORDINATOR={os.environ["LG_COORDINATOR"]}')
    else:
        rep.info('LG_COORDINATOR not set: the coordinator_address of the environment '
                 f'file, else {common.DEFAULT_COORDINATOR}')
    extra = os.environ.get('ZEPHYR_EXTRA_MODULES', '')
    if extra:
        rep.ok(f'ZEPHYR_EXTRA_MODULES={extra}')
    else:
        rep.info('ZEPHYR_EXTRA_MODULES not set: the module must come from west.yml')


def owned(place):
    """A labgrid Place of the session, held by this user."""
    return common.owned_by({'acquired': place.acquired,
                            'allowed': list(getattr(place, 'allowed', None) or [])})


def check_coordinator(rep, coordinator):
    """Returns the session or None."""
    try:
        from labgrid.remote.client import start_session
        session = start_session(coordinator)
    except Exception as e:
        rep.fail(f'coordinator {coordinator} not reachable: {e}')
        return None
    places = session.places
    zephyr = [n for n, p in places.items() if p.tags.get('zephyr_platform')]
    rep.ok(f'coordinator {coordinator}: {len(places)} place(s), '
           f'{len(zephyr)} with zephyr_platform tag')
    return session


def check_place(rep, session, name):
    """Returns the Place or None."""
    place = session.places.get(name)
    if place is None:
        rep.fail(f'place {name} does not exist on the coordinator. Places: '
                 f'{", ".join(sorted(session.places)) or "none"}')
        return None
    if not place.acquired:
        rep.warn(f'place {name} is not acquired. west needs it acquired by you: '
                 f'labgrid-client -p {name} acquire. Twister acquires it per test with '
                 'a map from labgrid-twister-hwmap')
    elif owned(place):
        rep.ok(f'place {name} is acquired by you ({place.acquired})')
    else:
        rep.fail(f'place {name} is acquired by {place.acquired}')
    tags = place.tags
    if tags.get('zephyr_platform'):
        rep.ok(f'tag zephyr_platform={tags["zephyr_platform"]}')
    else:
        rep.warn(f'place {name} has no zephyr_platform tag; labgrid-twister-hwmap '
                 'will skip it')
    if tags.get('zephyr_env'):
        rep.ok(f'tag zephyr_env={tags["zephyr_env"]}')
    else:
        rep.info('no zephyr_env tag: labgrid-twister-hwmap needs --env')
    if not place.acquired_resources and place.acquired:
        rep.fail(f'place {name} is acquired but has no resources; is the exporter '
                 'running and do the matches fit?')
    return place


def _driver_classes(target):
    return [type(d).__name__ for d in target.drivers]


def check_env_file(rep, env_file, place):
    """Load the environment. Returns (env, target) or (None, None)."""
    if not env_file:
        return None, None
    if not os.path.isfile(env_file):
        rep.fail(f'environment file {env_file} does not exist')
        return None, None
    if place:
        os.environ['LG_PLACE'] = place
    try:
        from labgrid import Environment
        env = Environment(config_file=env_file)
        target = env.get_target()
    except Exception as e:
        rep.fail(f'environment file {env_file} does not load: {e}')
        return None, None
    if target is None:
        rep.fail(f'environment file {env_file} has no target "main"')
        return env, None
    rep.ok(f'environment file {env_file} loads')
    drivers = _driver_classes(target)
    rep.info(f'drivers: {", ".join(drivers) or "none"}')

    from labgrid.exceptions import NoDriverFoundError
    try:
        target.get_driver('ConsoleProtocol', activate=False)
        rep.ok('console driver present')
    except NoDriverFoundError:
        rep.fail('no ConsoleProtocol driver (SerialDriver) in the environment')

    # The same rule as the runner: a FlashScriptDriver named "reset" is the
    # reset script, not the flasher.
    try:
        flasher, _ = common.select_flasher(target, activate=False)
        rep.ok(f'flash driver {type(flasher).__name__}')
    except LookupError as e:
        flasher = None
        rep.fail(f'{e} in the environment')

    # image files referenced by FlashScriptDriver
    if flasher is not None and type(flasher).__name__ == 'FlashScriptDriver':
        if flasher.script:
            try:
                path = env.config.get_image_path(flasher.script)
                if os.path.isfile(path):
                    rep.ok(f'flash script {path}')
                    if not os.access(path, os.X_OK):
                        rep.warn(f'flash script {path} is not executable')
                else:
                    rep.fail(f'flash script {path} does not exist')
            except Exception as e:
                rep.fail(f'flash script "{flasher.script}" not in the images section: {e}')
        else:
            rep.warn('FlashScriptDriver has no script; west flash -r labgrid needs one')
    return env, target


def bound_resources(target):
    """Resources of the target that live on an exporter, after the RemotePlace
    has been expanded. Returns [] when the place is not acquired."""
    from labgrid.resource.common import NetworkResource
    try:
        target.await_resources(target.resources, timeout=5.0)
    except Exception:
        pass
    return [r for r in target.resources if isinstance(r, NetworkResource)]


def check_resources(rep, target, place):
    """Check that the drivers find their resources. Returns the list of
    network resources."""
    from labgrid.exceptions import NoResourceFoundError
    if place is None or not place.acquired:
        rep.info('place not acquired: skipping resource and exporter checks')
        return []
    resources = bound_resources(target)
    if not resources:
        rep.fail('the place has no resources this environment can use')
        return []
    for res in resources:
        state = 'available' if res.avail else 'NOT available'
        rep.ok(f'resource {type(res).__name__} {res.name} on {res.host}: {state}')
    for drv in target.drivers:
        try:
            target.get_driver(type(drv), name=drv.name, activate=False)
        except NoResourceFoundError as e:
            rep.fail(f'driver {type(drv).__name__} has no resource in the place: {e}')
        except Exception:
            pass
    return resources


def default_tools(target):
    tools = []
    for drv in target.drivers:
        if type(drv).__name__ == 'OpenOCDDriver':
            tools.append('openocd')
    return tools


# Where the example flash scripts look for vendor tools besides PATH.
TOOL_DIRS = ('"$HOME/.local/bin" /opt/SEGGER/JLink "$HOME/opt/SEGGER-JLink" '
             '/opt/st/stm32cubeclt*/STM32CubeProgrammer/bin')


def check_exporter_tools(rep, resources, tools):
    if not tools:
        rep.info('no --tool given: exporter tool check skipped')
        return
    hosts = {}
    for res in resources:
        hosts.setdefault(res.host, res)
    for host, res in hosts.items():
        for tool in tools:
            # the places the example flash scripts look, after the PATH of
            # the non-interactive ssh shell
            script = ('command -v "$1" 2>/dev/null && exit 0; '
                      f'for d in {TOOL_DIRS}; do '
                      'test -x "$d/$1" && echo "$d/$1" && exit 0; done; exit 1')
            cmd = res.wrap_command(['sh', '-c', script, 'sh', tool])
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, timeout=30)
            except Exception as e:
                rep.fail(f'could not run a command on exporter {host}: {e}')
                break
            if proc.returncode == 0:
                rep.ok(f'{tool} on exporter {host}: {proc.stdout.strip()}')
            else:
                rep.fail(f'{tool} not found on exporter {host}: not on the PATH of '
                         f'a non-interactive ssh shell and not in {TOOL_DIRS}')


def check_console(rep, target, place):
    if place is None or not place.acquired:
        return
    from labgrid.exceptions import NoDriverFoundError, NoResourceFoundError
    common.install_purge_workaround()
    start = time.monotonic()
    try:
        console = target.get_driver('ConsoleProtocol')
    except NoDriverFoundError:
        return
    except NoResourceFoundError as e:
        rep.fail(f'console has no resource: {e}')
        return
    except Exception as e:
        rep.fail(f'console does not open: {e}')
        return
    took = time.monotonic() - start
    rep.ok(f'console opened in {took:.1f} s')
    if common.purge_was_broken():
        rep.warn('serial server ignores the RFC2217 purge request (ser2net 4.6.0, '
                 'labgrid issue #1396). labgrid-pty goes on without purge, ser2net '
                 '4.6.1 or newer fixes it')
    else:
        rep.ok('RFC2217 purge answered')
    ser = getattr(console, 'serial', None)
    if ser is not None:
        ser.timeout = 0.5
        try:
            data = ser.read(max(1, ser.in_waiting))
            rep.info(f'{len(data)} byte(s) of console output in 0.5 s')
        except Exception as e:
            rep.warn(f'console read failed: {e}')
    try:
        target.deactivate(console)
    except Exception:
        pass


def check_hwmap(rep, path, session):
    import yaml
    try:
        with open(path) as f:
            entries = yaml.safe_load(f) or []
    except Exception as e:
        rep.fail(f'hardware map {path} does not load: {e}')
        return
    if not isinstance(entries, list):
        rep.fail(f'hardware map {path} is not a list')
        return
    rep.ok(f'hardware map {path}: {len(entries)} entries')
    checked_pty = set()
    for entry in entries:
        ident = entry.get('id')
        label = f'hwmap {ident or "?"}'
        if entry.get('runner') != 'labgrid':
            rep.info(f'{label}: runner is {entry.get("runner")}, not labgrid, skipped')
            continue
        if not ident:
            rep.fail('hwmap entry without id: Twister drops runner_params when id is empty')
            continue
        params = entry.get('runner_params') or []
        if not any(p.startswith('--dev-id') for p in params):
            rep.fail(f'{label}: runner_params has no --dev-id')
        has_tag = bool(session is not None and ident in session.places
                       and session.places[ident].tags.get('zephyr_env'))
        if not (any(p.startswith('--env') for p in params)
                or os.environ.get('ZEPHYR_LABGRID_ENV') or has_tag):
            rep.fail(f'{label}: runner_params has no --env, ZEPHYR_LABGRID_ENV is not set '
                     'and the place has no zephyr_env tag')
        for p in params:
            if p.startswith('--env='):
                env = p.split('=', 1)[1]
                if not os.path.isfile(env):
                    rep.fail(f'{label}: environment file {env} does not exist')
        pty = entry.get('serial_pty')
        if not pty:
            rep.fail(f'{label}: no serial_pty')
        else:
            words = [w for w in pty.replace(' ', ',').split(',') if w]
            cmd = words[0]
            if cmd not in checked_pty:
                checked_pty.add(cmd)
                if shutil.which(cmd) or os.path.isfile(cmd):
                    rep.ok(f'serial_pty command {cmd} found')
                else:
                    rep.fail(f'serial_pty command {cmd} not on PATH')
            if '--acquire' in words and entry.get('pre_script'):
                rep.warn(f'{label}: both --acquire and pre_script lock the place')
        if session is not None:
            place = session.places.get(ident)
            if place is None:
                rep.fail(f'{label}: place {ident} does not exist on the coordinator')
                continue
            tag = place.tags.get('zephyr_platform')
            if tag and tag != entry.get('platform'):
                rep.warn(f'{label}: platform {entry.get("platform")} but tag '
                         f'zephyr_platform={tag}')
            if place.acquired and not owned(place):
                rep.warn(f'{label}: place acquired by {place.acquired}')
            if entry.get('flash_before') != (
                    common.tag_is_true(place.tags.get('zephyr_flash_before'))):
                if place.tags.get('zephyr_flash_before'):
                    rep.warn(f'{label}: flash_before differs from the zephyr_flash_before tag')


# -- main --------------------------------------------------------------------

def run(args, rep):
    if not check_python(rep):
        return
    check_path(rep, args.pty)
    check_env_vars(rep, args)

    coordinator = args.coordinator or common.coordinator_for_env(args.env)
    session = check_coordinator(rep, coordinator)

    place = None
    if session is not None and args.place:
        place = check_place(rep, session, args.place)
        if place is not None and not args.env:
            try:
                args.env = common.resolve_env(None, args.place, env_dir=args.env_dir,
                                              tags=place.tags)
                rep.ok(f'environment file {args.env} from the zephyr_env tag')
            except ValueError as e:
                rep.fail(str(e))
    elif not args.place:
        rep.info('no --place/$LG_PLACE: place, resource and console checks skipped')

    if args.hwmap:
        check_hwmap(rep, args.hwmap, session)

    if session is not None:
        common.close_session(session)

    if args.place and place is not None and not owned(place):
        # Loading the environment needs the place acquired by you.
        rep.info('place not acquired by you: environment, resource and console '
                 'checks skipped')
        return
    env, target = check_env_file(rep, args.env, args.place)
    if target is not None:
        resources = check_resources(rep, target, place)
        tools = args.tool or default_tools(target)
        if resources:
            check_exporter_tools(rep, resources, tools)
        if not args.no_console:
            check_console(rep, target, place)
        try:
            target.cleanup()
        except Exception:
            pass


def main(argv=None):
    args = build_parser().parse_args(argv)
    rep = Report()
    run(args, rep)
    if rep.failed:
        print(f'{rep.failed} check(s) failed, {rep.warned} warning(s)')
        sys.exit(1)
    print(f'all checks passed, {rep.warned} warning(s)')


if __name__ == '__main__':
    main()

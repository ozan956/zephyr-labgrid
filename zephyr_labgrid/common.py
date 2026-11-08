# SPDX-License-Identifier: Apache-2.0
"""Small helpers used by the runner, the console bridge and the tools."""

import atexit
import contextlib
import getpass
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

DEFAULT_COORDINATOR = '127.0.0.1:20408'


def default_env():
    """Environment file from $ZEPHYR_LABGRID_ENV, then $LG_ENV.

    ZEPHYR_LABGRID_ENV is preferred because LG_ENV also switches on labgrid's
    own pytest plugin inside pytest-twister-harness runs.
    """
    return os.environ.get('ZEPHYR_LABGRID_ENV') or os.environ.get('LG_ENV')


def default_place():
    return os.environ.get('LG_PLACE')


def default_coordinator():
    return os.environ.get('LG_COORDINATOR', DEFAULT_COORDINATOR)


def default_env_dir():
    return os.environ.get('ZEPHYR_LABGRID_ENV_DIR')


def close_session(session):
    """Stop a labgrid client session from ``start_session``."""
    try:
        session.loop.run_until_complete(session.stop())
        session.loop.run_until_complete(session.close())
    except Exception:
        pass


def python_child(module, func, *args):
    """Command that runs zephyr_labgrid.<module>.<func>(args) in a child.

    sys.path[0], the current directory for python -c, becomes the directory
    of this package: a labgrid clone in the current directory would hide
    the installed labgrid package.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ('import sys; sys.path[0] = sys.argv.pop(1); '
            f'from zephyr_labgrid.{module} import {func}; sys.exit({func}(sys.argv[1:]))')
    return [sys.executable, '-c', code, root, *args]


_LAB_PLACES = {}


def lab_places(coordinator=None):
    """All places of the coordinator as a dict, read in a child process.

    ``{name: {'tags': {...}, 'acquired': 'host/user' or None,
    'allowed': [...]}}``. A child process because labgrid's RemotePlace
    opens a coordinator session of its own later in this process, and the
    coordinator accepts one session per process. Raises PlaceLookupError.
    """
    import json
    coordinator = coordinator or default_coordinator()
    # west runs the runner once per sysbuild image in one process
    if coordinator in _LAB_PLACES:
        return _LAB_PLACES[coordinator]
    env = dict(os.environ)
    env.pop('LG_ENV', None)
    proc = subprocess.run(python_child('placeinfo', 'main', '-x', coordinator),
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise PlaceLookupError(proc.stderr.strip() or
                               f'could not read the places of {coordinator}')
    _LAB_PLACES[coordinator] = json.loads(proc.stdout)
    return _LAB_PLACES[coordinator]


TRUE_WORDS = ('1', 'true', 'yes', 'on')


def tag_is_true(value):
    """A place tag used as a flag, like zephyr_flash_before=true."""
    return str(value or '').strip().lower() in TRUE_WORDS


def whoami():
    """The owner name labgrid-client uses for this user, ``host/user``."""
    host = os.environ.get('LG_HOSTNAME') or socket.gethostname()
    user = os.environ.get('LG_USERNAME') or getpass.getuser()
    return f'{host}/{user}'


def owned_by(info, me=None):
    """True when the place (an entry of lab_places) is acquired by ``me``
    or ``me`` is allowed to use it."""
    me = me or whoami()
    return info.get('acquired') == me or me in (info.get('allowed') or [])


def platform_matches(tag, board_target, board=None):
    """Does a ``zephyr_platform`` tag fit a build?

    ``board_target`` is CONFIG_BOARD_TARGET (``stm32f746g_disco/stm32f746xx``),
    ``board`` is CONFIG_BOARD. A tag without qualifiers matches every target
    of that board.
    """
    if not tag or not board_target:
        return False
    if tag == board_target:
        return True
    return '/' not in tag and tag == (board or board_target.split('/')[0])


def platform_selects(tag, platform):
    """Does a Twister ``-p`` platform select a place with this
    ``zephyr_platform`` tag? A board name without qualifiers selects every
    target of the board, as Twister treats it."""
    if not tag or not platform:
        return False
    if tag == platform:
        return True
    return ('/' not in platform and tag.split('/')[0] == platform) or \
        ('/' not in tag and platform.split('/')[0] == tag)


class PlaceSelectError(RuntimeError):
    pass


def select_owned_place(places, board_target, board=None, me=None):
    """The one place owned by ``me`` whose zephyr_platform tag fits the
    build. Raises PlaceSelectError with a hint when there is none or more
    than one."""
    me = me or whoami()
    fitting = sorted(name for name, info in places.items()
                     if platform_matches(info['tags'].get('zephyr_platform'),
                                         board_target, board))
    mine = [name for name in fitting if owned_by(places[name], me)]
    if len(mine) == 1:
        return mine[0]
    if mine:
        raise PlaceSelectError(f'you hold several places for {board_target}: '
                               f'{", ".join(mine)}. Pick one with --dev-id')
    free = [name for name in fitting if not places[name].get('acquired')]
    if free:
        hint = (f'Free places for it: {", ".join(free)}. Take one with: '
                f'labgrid-client -p {free[0]} acquire')
    elif fitting:
        hint = f'All places for it are in use: {", ".join(fitting)}'
    else:
        hint = 'No place has a matching zephyr_platform tag'
    raise PlaceSelectError(f'you hold no place for {board_target}. {hint}')


def check_owned(places, place, me=None):
    """Raise PlaceSelectError unless ``place`` exists and is ``me``'s."""
    me = me or whoami()
    info = places.get(place)
    if info is None:
        raise PlaceSelectError(f'place {place} does not exist. Places: '
                               f'{", ".join(sorted(places)) or "none"}')
    if owned_by(info, me):
        return
    if info.get('acquired'):
        raise PlaceSelectError(f'place {place} is acquired by {info["acquired"]}, '
                               f'not by you ({me})')
    raise PlaceSelectError(f'place {place} is not acquired. Take it first with: '
                           f'labgrid-client -p {place} acquire')


# Name of the FlashScriptDriver that resets the board instead of flashing it.
RESET_SCRIPT = 'reset'


def select_flasher(target, driver_name=None, activate=True):
    """The flash driver of a target, as (driver, kind) with kind 'bootstrap'
    or 'script'.

    ``driver_name`` picks a driver by name. Otherwise the BootstrapProtocol
    driver, else the one FlashScriptDriver that is not the reset script.
    Raises LookupError.
    """
    from labgrid.driver import FlashScriptDriver
    from labgrid.driver.common import Driver
    from labgrid.exceptions import NoDriverFoundError

    if driver_name:
        try:
            drv = target.get_driver(Driver, name=driver_name, activate=activate)
        except NoDriverFoundError:
            raise LookupError(f'labgrid driver "{driver_name}" not found') from None
        if isinstance(drv, FlashScriptDriver):
            return drv, 'script'
        if hasattr(drv, 'load'):
            return drv, 'bootstrap'
        raise LookupError(f'labgrid driver "{driver_name}" can not flash '
                          '(needs BootstrapProtocol or FlashScriptDriver)')
    try:
        return target.get_driver('BootstrapProtocol', activate=activate), 'bootstrap'
    except NoDriverFoundError:
        pass
    scripts = [d for d in target.drivers
               if isinstance(d, FlashScriptDriver) and d.name != RESET_SCRIPT]
    if len(scripts) == 1:
        if activate:
            target.activate(scripts[0])
        return scripts[0], 'script'
    if scripts:
        raise LookupError('several FlashScriptDrivers, pick one with --driver')
    raise LookupError('no flash driver (BootstrapProtocol or FlashScriptDriver)')


class PlaceLookupError(RuntimeError):
    pass


def resolve_env(env_file, place, env_dir=None, tags=None):
    """Find the labgrid environment file for a place.

    Order: ``env_file`` (the --env option), $ZEPHYR_LABGRID_ENV, $LG_ENV,
    then the ``zephyr_env`` tag in ``tags``, the tags of the place. A relative
    tag is resolved against ``env_dir`` (--env-dir, else
    $ZEPHYR_LABGRID_ENV_DIR). Returns the path, raises ValueError with a hint
    when nothing fits.
    """
    env_file = env_file or default_env()
    if env_file:
        return env_file
    tag = (tags or {}).get('zephyr_env')
    if not tag:
        raise ValueError(f'no --env given, $ZEPHYR_LABGRID_ENV is not set and place '
                         f'{place} has no zephyr_env tag')
    if os.path.isabs(tag):
        return tag
    env_dir = env_dir or default_env_dir()
    if not env_dir:
        raise ValueError(f'place {place} has zephyr_env={tag}, a relative path: set '
                         '$ZEPHYR_LABGRID_ENV_DIR (or --env-dir) to the directory '
                         'with the environment files')
    return os.path.join(env_dir, tag)


def coordinator_for_env(env_file):
    """Coordinator address for an environment file: the ``coordinator_address``
    option of the file when set, else $LG_COORDINATOR, else the default."""
    address = None
    if env_file:
        try:
            import yaml
            with open(env_file) as f:
                data = yaml.safe_load(f) or {}
            address = (data.get('options') or {}).get('coordinator_address')
        except Exception:
            address = None
    return address or default_coordinator()


# ---------------------------------------------------------------------------
# RFC2217 purge
#
# ser2net 4.6.0 never answers the RFC2217 PURGE request (labgrid issue
# #1396), and pyserial then fails to open the port. The first purge of a
# process gets a short timeout, and when it is not answered the process
# sends no more purges.
# ---------------------------------------------------------------------------

PURGE_PROBE_TIMEOUT = 1.0
_PURGE_FLAG = '_zephyr_labgrid_purge_broken'


def install_purge_workaround(warn=None):
    """Patch serial.rfc2217.Serial. ``warn`` gets a message when the
    server does not answer the purge."""
    import serial
    import serial.rfc2217

    cls = serial.rfc2217.Serial
    if getattr(cls, '_zephyr_labgrid_patched', False):
        return

    def send_purge(self, value):
        if getattr(cls, _PURGE_FLAG, False):
            return
        item = self._rfc2217_options['purge']
        item.set(value)
        try:
            item.wait(PURGE_PROBE_TIMEOUT)
        except serial.SerialException:
            setattr(cls, _PURGE_FLAG, True)
            if warn:
                warn('the serial server did not answer the RFC2217 purge request '
                     '(ser2net 4.6.0, labgrid issue #1396). Going on without purge, '
                     'ser2net 4.6.1 or newer fixes it.')

    cls.rfc2217_send_purge = send_purge
    cls._zephyr_labgrid_patched = True


def purge_was_broken():
    """True when the server did not answer a purge in this process."""
    try:
        import serial.rfc2217
    except ImportError:
        return False
    return bool(getattr(serial.rfc2217.Serial, _PURGE_FLAG, False))


# ---------------------------------------------------------------------------
# Place locks through labgrid-client
#
# Used by the hidden --acquire of hardware maps. The runner and labgrid-pty
# of a test share the place through a lock directory, see docs/design.rst.
# ---------------------------------------------------------------------------

class PlaceLockError(RuntimeError):
    pass


def labgrid_client_command():
    exe = shutil.which('labgrid-client')
    if exe:
        return [exe]
    return [sys.executable, '-c', 'from labgrid.remote.client import main; main()']


def run_labgrid_client(args, coordinator=None):
    """Run labgrid-client with ``args``. Returns (returncode, output)."""
    cmd = labgrid_client_command()
    if coordinator:
        cmd += ['-x', coordinator]
    cmd += list(args)
    env = dict(os.environ)
    # labgrid-client would otherwise read the environment file and act on
    # every RemotePlace in it.
    env.pop('LG_ENV', None)
    proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    return proc.returncode, proc.stdout.strip()


def lock_root():
    return os.environ.get('ZEPHYR_LABGRID_LOCK_DIR') or os.path.join(
        tempfile.gettempdir(), f'zephyr-labgrid-{os.getuid()}')


def place_dir(place, coordinator=None):
    """Directory where the tools of one labgrid user on this host
    coordinate for one place. Users with their own LG_USERNAME never share
    it, so that they never wait for each other's lock."""
    coordinator = coordinator or default_coordinator()
    key = re.sub(r'[^A-Za-z0-9._-]+', '_', f'{coordinator}-{whoami()}-{place}')
    return os.path.join(lock_root(), key)


def mark_console_ready(place, coordinator=None):
    """Tell other tools that this process has the console of the place open.
    Returns the marker path, remove it on exit (see clear_console_ready)."""
    directory = place_dir(place, coordinator)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, f'console-{os.getpid()}.ready')
    open(path, 'w').close()
    return path


def clear_console_ready(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def mark_console_starting(place, coordinator=None):
    """Tell other tools that this process is opening the console of the
    place. The marker of a process that died is ignored."""
    directory = place_dir(place, coordinator)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, f'console-{os.getpid()}.starting')
    open(path, 'w').close()
    return path


def _live_marker(place, coordinator, suffix):
    """True when a live process left a console-<pid><suffix> marker.
    Markers of dead processes are removed."""
    directory = place_dir(place, coordinator)
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    for name in names:
        if not (name.startswith('console-') and name.endswith(suffix)):
            continue
        try:
            pid = int(name[len('console-'):-len(suffix)])
        except ValueError:
            continue
        if pid_alive(pid):
            return True
        try:
            os.unlink(os.path.join(directory, name))
        except OSError:
            pass
    return False


def console_is_ready(place, coordinator=None):
    """True when a live process has marked the console of the place open."""
    return _live_marker(place, coordinator, '.ready')


def console_expected(place, coordinator=None, grace=0.0, poll=0.2):
    """True when a labgrid-pty for the place is starting or open. Waits up
    to ``grace`` seconds for one to show up."""
    deadline = time.monotonic() + grace
    while True:
        if (_live_marker(place, coordinator, '.starting')
                or _live_marker(place, coordinator, '.ready')):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


def twister_words(pid=None):
    """Command line of the parent process when it is Twister, else None.
    Twister passes nothing to its tools that says how it runs them, its
    command line (Linux /proc) does."""
    pid = pid or os.getppid()
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            words = f.read().split(b'\0')
    except OSError:
        return None
    return words if any(b'twister' in w for w in words) else None


def started_by_twister(pid=None):
    """True when the parent process is a Twister run that opens the console
    before flashing, so that a labgrid-pty is about to start. Twister's
    --flash-before opens the console after flashing, so there is nothing to
    wait for then.
    """
    words = twister_words(pid)
    return words is not None and b'--flash-before' not in words


def twister_flashes_after_console(pid=None):
    """True when the parent is a Twister run without a hardware map and
    without --flash-before, so that it flashes while the console is open.
    A generated hardware map sets flash_before for the places that need it.
    """
    words = twister_words(pid)
    return (words is not None and b'--flash-before' not in words
            and not any(w.startswith(b'--hardware-map') for w in words))


def wait_console_ready(place, coordinator=None, timeout=30.0, poll=0.2):
    """Wait until a console bridge for the place is open. Returns True when
    it is, False on timeout.

    Twister starts labgrid-pty and west flash at the same time when
    flash_before is false. Opening a remote console takes a few seconds;
    the flasher resets the board, and the first output would be lost.
    """
    deadline = time.monotonic() + timeout
    while True:
        if console_is_ready(place, coordinator):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError, ValueError):
        return False
    return True


_PROCESS_LOCKS = {}


def hold_place_for_process(place, coordinator=None, log=None, wait=0.0):
    """Acquire the place once for the whole process and release it at exit.

    ``west flash`` on a sysbuild build runs the runner once per image
    (MCUboot, then the application, ...) in one process. Releasing after
    every image would let someone else take the place in between.
    """
    coordinator = coordinator or default_coordinator()
    key = (coordinator, place)
    lock = _PROCESS_LOCKS.get(key)
    if lock is None:
        lock = PlaceLock(place, coordinator, log=log)
        lock.acquire(wait=wait)
        if not _PROCESS_LOCKS:
            atexit.register(release_process_places)
        _PROCESS_LOCKS[key] = lock
    return lock


def release_process_places():
    """Release what hold_place_for_process acquired. Safe to call twice.

    SIGTERM is ignored meanwhile: Twister terminates west on its flash
    timeout, and a second signal must not cut the release short.
    """
    try:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    except ValueError:
        pass    # not the main thread
    while _PROCESS_LOCKS:
        _, lock = _PROCESS_LOCKS.popitem()
        try:
            lock.release()
        except PlaceLockError as e:
            lock.log(str(e))


def release_places_on_sigterm():
    """On SIGTERM, release the places of hold_place_for_process and exit."""
    def handler(signum, frame):
        release_process_places()
        os._exit(128 + signum)
    signal.signal(signal.SIGTERM, handler)


def release_if_unused(place, coordinator=None, log=print, pid=None):
    """Unregister the tool ``pid``, then release the place when the tools
    still own it and none uses it.

    Runs in the child process that PlaceLock.release() starts, under the
    lock of the place, so a tool that starts meanwhile waits for it.
    Returns True when nothing went wrong.
    """
    lock = PlaceLock(place, coordinator, log=log)
    with lock._locked():
        if pid is not None:
            try:
                os.unlink(os.path.join(lock.dir, f'{pid}.pid'))
            except OSError:
                pass
        if not os.path.exists(lock.marker):
            return True     # released already, or acquired by hand
        others = lock._other_users()
        if others:
            log(f'place {place} is still used by another tool '
                f'(pid {", ".join(map(str, others))}), not releasing')
            return True
        rc, out = run_labgrid_client(['-p', place, 'release'], lock.coordinator)
        try:
            os.unlink(lock.marker)
        except OSError:
            pass
    if rc != 0:
        log(f'could not release place {place}: {out}')
        return False
    log(f'released place {place}')
    return True


def _release_main(argv):
    """Entry point of the release child process: PLACE COORDINATOR PID."""
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)

    def log(msg):
        try:
            print(msg, flush=True)
        except OSError:
            pass    # the parent is gone, the release still happens
    return 0 if release_if_unused(argv[0], argv[1], log=log, pid=int(argv[2])) else 1


class PlaceLock:
    """Hold a place for the lifetime of a ``with`` block, shared with the
    other zephyr-labgrid tools on this host (see above)."""

    MARKER = 'acquired-by-tools'

    def __init__(self, place, coordinator=None, log=None):
        self.place = place
        self.coordinator = coordinator or default_coordinator()
        self.log = log or (lambda msg: None)
        self.dir = place_dir(place, self.coordinator)
        self.pid = os.getpid()
        self.pidfile = os.path.join(self.dir, f'{self.pid}.pid')
        self.marker = os.path.join(self.dir, self.MARKER)
        self.registered = False

    @contextlib.contextmanager
    def _locked(self):
        # Imported here: west imports every module runner for every command,
        # and a top level import of fcntl broke all runners on Windows.
        import fcntl
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(self.dir, 'lock'), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _other_users(self):
        """PIDs of other live tools registered for this place. Stale files
        of dead processes are removed."""
        others = []
        for name in os.listdir(self.dir):
            if not name.endswith('.pid'):
                continue
            path = os.path.join(self.dir, name)
            if path == self.pidfile:
                continue
            try:
                pid = int(name[:-4])
            except ValueError:
                continue
            if pid_alive(pid):
                others.append(pid)
            else:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return others

    def _ours(self, out):
        """labgrid-client says the place is ours on this host. "You have
        already acquired place X on HOST" means another host, not ours."""
        return re.search(rf'You have already acquired place {re.escape(self.place)}\.(\s|$)',
                         out) is not None

    @staticmethod
    def _busy(out):
        """Someone else holds the place (client check or coordinator race)."""
        return 'is already acquired' in out or 'You have already acquired place' in out

    def acquire(self, wait=0.0, poll=5.0):
        """Acquire the place, or share it with the other zephyr-labgrid
        tools of this run. When someone else holds it, try again for up to
        ``wait`` seconds. Raises PlaceLockError."""
        deadline = time.monotonic() + wait
        while True:
            busy = self._try_acquire(final=time.monotonic() >= deadline)
            if not busy:
                return
            self.log(f'place {self.place} is in use: {busy}. Waiting for it')
            time.sleep(max(0.0, min(poll, deadline - time.monotonic())))

    def _try_acquire(self, final):
        """One attempt. Returns None when the place is held now, or the
        labgrid-client message when it is busy and ``final`` is false."""
        with self._locked():
            rc, out = run_labgrid_client(['-p', self.place, 'acquire'], self.coordinator)
            if rc == 0:
                open(self.marker, 'w').close()
                self.log(f'acquired place {self.place}')
            elif self._ours(out):
                if not os.path.exists(self.marker):
                    self.log(f'place {self.place} is already acquired by you, keeping it')
                elif self._other_users():
                    self.log(f'place {self.place} is held by another zephyr-labgrid '
                             'tool, sharing it')
                else:
                    # Marker without a live tool: left by a killed run. The
                    # place may as well be acquired by hand since, so never
                    # release it automatically.
                    os.unlink(self.marker)
                    self.log(f'place {self.place} is acquired by you and a stopped '
                             'zephyr-labgrid run left its marker behind. Keeping the '
                             'place, release it by hand when nobody uses it: '
                             f'labgrid-client -p {self.place} release')
            elif self._busy(out) and not final:
                return out
            else:
                raise PlaceLockError(f'could not acquire place {self.place}: {out}')
            with open(self.pidfile, 'w') as f:
                f.write(f'{self.pid}\n')
            self.registered = True
            return None

    def release(self):
        if not self.registered:
            return
        self.registered = False
        self._release_in_child()

    def _release_in_child(self):
        """Run release_if_unused in a child process and wait for it.

        Twister sends SIGTERM and 0.5 s later SIGKILL, and it collects the
        children to kill before the SIGTERM. A child started after that
        survives the SIGKILL of this process and finishes the release. It
        is started before anything waits for the lock of the place, which
        another tool may hold for a while.
        """
        proc = subprocess.Popen(python_child('common', '_release_main', self.place,
                                             self.coordinator, str(self.pid)),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, start_new_session=True)
        out, _ = proc.communicate()
        lines = out.strip().splitlines()
        if proc.returncode != 0:
            raise PlaceLockError('\n'.join(lines) or f'could not release place {self.place}')
        for line in lines:
            self.log(line)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.release()
        except PlaceLockError as e:
            # do not hide the original error
            if exc is None:
                raise
            self.log(str(e))
        return False

# SPDX-License-Identifier: Apache-2.0
"""Bridge a labgrid console to stdin/stdout.

Intended as Twister's ``serial_pty`` script (and the pytest-twister-harness
``--device-serial-pty``): Twister starts this with a pty on its stdio and
talks to it as if it were a serial port. We forward everything to the
console driver of the labgrid target.

Usage: labgrid-pty [-e ENV] [-p PLACE] [-l LOGFILE] [--reset-rts]
  PLACE defaults to $LG_PLACE, then to the place you hold for
        $TWISTER_PLATFORM (Twister sets it), then to the one place you
        hold. The place must be acquired by you.
  ENV   defaults to $ZEPHYR_LABGRID_ENV (then $LG_ENV, then the zephyr_env
        tag of the place, relative to --env-dir/$ZEPHYR_LABGRID_ENV_DIR)

Exit codes: 0 on stdin EOF or SIGTERM, 1 on a labgrid error, 2 on usage.
"""

import argparse
import os
import select
import signal
import sys
import threading
import time
import traceback

from . import common

PROG = 'labgrid-pty'


def warn(msg):
    print(f'{PROG}: {msg}', file=sys.stderr, flush=True)


def die(msg, code=1):
    warn(msg)
    sys.exit(code)


def reset_rts(ser, pulse=0.1):
    """Pulse RTS (EN on ESP32 dev kits) through a pyserial object. Works over
    RFC2217 when ser2net forwards modem control."""
    ser.dtr = False
    ser.rts = True
    time.sleep(pulse)
    ser.rts = False


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-e', '--env', default=common.default_env(),
                        help='labgrid environment file (default $ZEPHYR_LABGRID_ENV, '
                             'then the zephyr_env tag of the place)')
    parser.add_argument('--env-dir', default=None,
                        help='directory for a relative zephyr_env tag '
                             '(default $ZEPHYR_LABGRID_ENV_DIR)')
    parser.add_argument('-p', '--place', default=common.default_place(),
                        help='labgrid place (default $LG_PLACE, then the place you '
                             'hold for $TWISTER_PLATFORM or the one place you hold)')
    parser.add_argument('-l', '--logfile', default=None,
                        help='also append raw console output to this file')
    parser.add_argument('--reset-rts', action='store_true',
                        help='pulse RTS after connecting to reset boards whose '
                             'reset line is wired to RTS (USB-UART ESP32 kits)')
    # Not for users: hardware maps from labgrid-twister-hwmap pass it, so
    # that Twister acquires each place for a test and releases it after.
    parser.add_argument('--acquire', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--acquire-wait', type=float, default=0.0, help=argparse.SUPPRESS)
    return parser


def resolve_place(args):
    """Fill in args.place and args.env (the zephyr_env tag) from one
    coordinator query, and check that the user holds the place."""
    places = common.lab_places(common.coordinator_for_env(args.env))
    if not args.place:
        platform = os.environ.get('TWISTER_PLATFORM')
        if platform:
            args.place = common.select_owned_place(places, platform, platform.split('/')[0])
        else:
            mine = sorted(name for name, info in places.items() if common.owned_by(info))
            if not mine:
                raise common.PlaceSelectError('you hold no place. Take one with: '
                                              'labgrid-client -p PLACE acquire')
            if len(mine) > 1:
                raise common.PlaceSelectError(f'you hold several places ({", ".join(mine)}), '
                                              'pick one with -p')
            args.place = mine[0]
    if not args.acquire:
        common.check_owned(places, args.place)
    tags = places[args.place]['tags']
    args.env = common.resolve_env(args.env, args.place, env_dir=args.env_dir, tags=tags)
    # The lab owner tags boards whose reset line is wired to RTS; the user
    # should not have to know that.
    if '--reset-rts' in str(tags.get('zephyr_pty_args', '')).split(','):
        args.reset_rts = True


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.place and args.env):
        # Twister hardware maps pass both; then the console opens without
        # asking the coordinator first.
        try:
            resolve_place(args)
        except (common.PlaceLookupError, common.PlaceSelectError, ValueError) as e:
            die(str(e), code=2)

    os.environ['LG_PLACE'] = args.place
    try:
        from labgrid import Environment
        from labgrid.exceptions import NoDriverFoundError, NoResourceFoundError
        from pexpect import TIMEOUT
    except ImportError as e:
        die(f'python package missing: {e}')

    common.install_purge_workaround(warn=warn)

    # Twister may terminate us at any time, also while we are still
    # acquiring the place. Handle the signals from the start so that the
    # place is released in every case.
    stop = threading.Event()

    def on_term(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    signal.signal(signal.SIGHUP, on_term)

    # A west flash started together with us (Twister) waits for the console.
    starting = common.mark_console_starting(args.place, common.coordinator_for_env(args.env))

    lock = None
    if args.acquire:
        lock = common.PlaceLock(args.place, common.coordinator_for_env(args.env), log=warn)
        try:
            lock.acquire(wait=args.acquire_wait)
        except common.PlaceLockError as e:
            die(str(e))

    def release():
        if lock:
            try:
                lock.release()
            except common.PlaceLockError as e:
                warn(str(e))

    if stop.is_set():
        release()
        sys.exit(0)

    try:
        env = Environment(config_file=args.env)
        target = env.get_target()
        console = target.get_driver('ConsoleProtocol')
    except NoResourceFoundError as e:
        release()
        die(f'place "{args.place}" has no matching resource: {e}. '
            'Is the place acquired by you and the exporter running?')
    except NoDriverFoundError:
        release()
        die(f'no ConsoleProtocol driver (e.g. SerialDriver) in {args.env}')
    except Exception as e:
        release()
        die(f'could not open console of place "{args.place}": {e}')

    # Fast path: talk to the pyserial object of a SerialDriver directly.
    # ConsoleProtocol.read(timeout=...) sets serial.timeout on every call and
    # pyserial's RFC2217 class renegotiates all port settings with ser2net
    # each time, which costs round trips and can lose bytes at high poll
    # rates. labgrid drivers are also not thread safe, while pyserial's
    # read and write may run from two threads.
    ser = getattr(console, 'serial', None)

    if args.reset_rts:
        if ser is None:
            release()
            die('--reset-rts needs a SerialDriver console')
        try:
            reset_rts(ser)
        except Exception as e:
            release()
            die(f'RTS reset failed: {e}')

    # Tell a west flash --wait-console that the console is open now.
    ready = common.mark_console_ready(args.place, common.coordinator_for_env(args.env))
    common.clear_console_ready(starting)

    failure = []
    out = sys.stdout.buffer
    log = open(args.logfile, 'ab') if args.logfile else None

    if ser is not None:
        ser.timeout = 0.1

        def read_chunk():
            return ser.read(max(1, ser.in_waiting))

        def write_chunk(data):
            ser.write(data)
    else:
        # Generic ConsoleProtocol: serialize access, labgrid drivers keep a
        # global @step stack that breaks when two threads use them.
        console_lock = threading.Lock()

        def read_chunk():
            try:
                with console_lock:
                    return console.read(size=1, timeout=0.1, max_size=4096)
            except TIMEOUT:
                return b''

        def write_chunk(data):
            with console_lock:
                console.write(data)

    def reader():
        while not stop.is_set():
            try:
                data = read_chunk()
            except Exception as e:  # connection lost: stop, do not spin
                failure.append(f'console read failed: {type(e).__name__}: {e}')
                stop.set()
                return
            if not data:
                continue
            try:
                out.write(data)
                out.flush()
            except OSError:  # stdout closed: the other side is gone
                stop.set()
                return
            if log:
                log.write(data)
                log.flush()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    stdin_fd = sys.stdin.fileno()
    write_warned = False
    try:
        while not stop.is_set():
            r, _, _ = select.select([stdin_fd], [], [], 0.2)
            if stdin_fd in r:
                try:
                    data = os.read(stdin_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                try:
                    write_chunk(data)
                except Exception as e:
                    # Keep the console alive: a lost connection shows up in
                    # the reader. Report the first failed write once.
                    if not write_warned:
                        write_warned = True
                        warn(f'console write failed: {type(e).__name__}: {e}')
                        traceback.print_exc(file=sys.stderr)
    finally:
        stop.set()
        common.clear_console_ready(ready)
        # Release first: Twister kills this process 0.5 s after SIGTERM.
        # The release runs in a child that survives that (PlaceLock).
        release()
        t.join(timeout=1.0)
        try:
            target.cleanup()
        except Exception as e:
            warn(f'cleanup failed: {e}')
        if log:
            log.close()

    if failure:
        die(failure[0])


if __name__ == '__main__':
    main()

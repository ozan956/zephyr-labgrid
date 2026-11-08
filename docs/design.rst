.. meta::
   :description: How zephyr-labgrid works inside, for contributors.

.. _design:

Design notes
============

How zephyr-labgrid works inside. For contributors and for anyone debugging
an unusual setup. Users start at :ref:`the documentation index <index>`.

Pieces
------

.. list-table::
   :header-rows: 1
   :widths: 25 40 35

   * - Piece
     - File
     - Role
   * - west runner ``labgrid``
     - ``scripts/labgrid_runner.py``
     - ``west flash``, ``west reset``
   * - module glue
     - ``zephyr/module.yml``, ``CMakeLists.txt``
     - registers the runner for every board
   * - console bridge
     - ``zephyr_labgrid/pty.py`` (``labgrid-pty``)
     - Twister ``serial_pty``, interactive console
   * - hardware map generator
     - ``zephyr_labgrid/hwmap.py``
     - Twister map from place tags
   * - setup check
     - ``zephyr_labgrid/check.py``
     - one line per check
   * - shared helpers
     - ``zephyr_labgrid/common.py``
     - places and owners, env lookup, place locks, purge workaround
   * - place lookup
     - ``zephyr_labgrid/placeinfo.py``
     - child process that reads the places of the coordinator

``CMakeLists.txt`` calls ``board_finalize_runner_args(labgrid)``. Zephyr
processes module CMake before ``cmake/flash``, so the runner shows up in
every build's ``runners.yaml`` without touching any ``board.cmake``. It is not
the default unless the user sets ``BOARD_FLASH_RUNNER=labgrid``. Arguments
from ``BOARD_RUNNER_ARGS_labgrid`` in the CMake cache land in ``runners.yaml``
too.

West loads ``scripts/labgrid_runner.py`` by path. The runner puts the module
checkout first on ``sys.path`` so that the ``zephyr_labgrid`` package from the
same checkout is used, and a pip installed copy only when there is none.

labgrid version
---------------

The module follows labgrid master. It uses features that no labgrid
release has yet, for example the ``timeout`` argument of
``FlashScriptDriver.flash()``. ``pyproject.toml`` asks for ``labgrid>=26.1.dev0``,
which only a master install satisfies until the next release.
``labgrid-twister-check`` tests for the features and names the fix.

labgrid depends on ``pyserial-labgrid``, a fork of pyserial that installs the
same ``serial`` package. Do not add plain ``pyserial`` as a dependency, because it
overwrites the fork.

Places and owners
-----------------

``common.lab_places()`` reads every place of the coordinator with its tags,
owner and allowed users, in one session in a child process
(``zephyr_labgrid.placeinfo``). One query gives the runner and
``labgrid-pty`` all they need.

The owner name of the user is ``host/user``, as labgrid-client builds it
(``LG_HOSTNAME`` and ``LG_USERNAME`` override both parts). A place is the
user's when it is acquired by that name or the name is in its allowed list.

Without a place, the runner takes the one place of the user whose
``zephyr_platform`` tag fits ``CONFIG_BOARD_TARGET`` of the build. A tag
without qualifiers fits every target of the board. With a place it checks
the owner and that the tag fits the build, unless ``--ignore-platform``.
``labgrid-pty`` takes the place of the user for ``$TWISTER_PLATFORM``, which
Twister sets for the ``serial_pty`` command, or else the one place of the
user. It also resets the board through RTS when the place has the
``zephyr_reset_rts`` tag.

Neither tool acquires a place for a user. Only hardware maps make them do
it, see the place locks below.

Finding the environment file
----------------------------

``common.resolve_env()`` tries ``--env``, ``$ZEPHYR_LABGRID_ENV``, ``$LG_ENV``, then the
``zephyr_env`` tag of the place, relative to ``--env-dir`` or
``$ZEPHYR_LABGRID_ENV_DIR``.

The tag is read in a child process (``zephyr_labgrid.placeinfo``). labgrid's
``RemotePlace`` opens its own coordinator session later in the runner
process, and the coordinator accepts one session per process. The child
replaces ``sys.path[0]`` (the current directory) with the module directory,
so a ``labgrid/`` clone in the current directory can not hide the installed
package.

The runner resolves the environment in ``do_run``, not when it is created,
so that argument errors never talk to the coordinator.

Flashing and resetting
----------------------

The runner sets ``LG_PLACE`` (environment files use ``!template $LG_PLACE``),
loads the environment and picks the flasher. That is the driver named by
``--driver``, else the ``BootstrapProtocol`` driver, else a
``FlashScriptDriver``.

-  ``BootstrapProtocol`` gets ``load(image)``. The image is ``--file``, else
   ``zephyr.hex``, ``zephyr.bin``, ``zephyr.elf``. The load commands of
   ``OpenOCDDriver`` have no address, so it gets ``zephyr.elf`` instead of a
   raw ``.bin``, and a ``.bin`` given with ``--file`` is refused.
-  With ``FlashScriptDriver`` the image is copied with ``ManagedFile``, ``{image}``
   in ``args`` becomes its remote path, ``{address}`` the flash offset. Without
   ``{image}`` the path is appended. The offset is
   ``CONFIG_FLASH_BASE_ADDRESS`` + ``CONFIG_FLASH_LOAD_OFFSET`` like Zephyr's
   runners, or for Espressif SoCs (no ``CONFIG_FLASH_BASE_ADDRESS``) the
   ``boot_partition`` with simple boot, else the ``zephyr,code-partition``.

The flash driver is deactivated right after loading so the probe is free.

``west reset`` tries ResetProtocol, then the ``FlashScriptDriver`` named
``reset``, then PowerProtocol (``cycle``), then
``OpenOCDDriver.execute(['init', 'reset run', 'shutdown'])``, and fails
without any of them. ``west flash`` does not reset afterwards, the flasher
resets the board itself. The runner does not declare the ``reset``
capability, west would otherwise add ``--reset`` to every flash and reset
the board twice. The reset script runs with its own ``args``, without an image. Because
of it an environment may have two FlashScriptDrivers, and the flasher is
then the one that is not named ``reset``.

West does not apply ``--dry-run`` itself, so the runner reads it in ``do_create``
and then only logs what it would do, without contacting the coordinator
for anything but the tag lookup.

Place locks
-----------

Acquire and release run the ``labgrid-client`` command (or its entry point
with the current interpreter), not the client API, to keep the process to
one coordinator session. ``LG_ENV`` is removed from its environment, or
labgrid-client would act on every place in the file.

Hardware maps from ``labgrid-twister-hwmap`` pass the hidden ``--acquire``
and ``--acquire-wait`` options to the runner and to ``labgrid-pty``. Twister
starts both at the same time when the board is flashed with the console
open, so both acquire.
The tools on one host coordinate through a lock directory.

::

   $TMPDIR/zephyr-labgrid-<uid>/<coordinator>-<place>/
     lock                 flock() while talking to the coordinator
     <pid>.pid            one per running tool that uses the place
     acquired-by-tools       present while a tool holds the place
     console-<pid>.starting  labgrid-pty is opening the console
     console-<pid>.ready     labgrid-pty has the console open

The first tool acquires and writes the marker. Every tool registers its
pid. The last tool to exit releases. Without the marker (place acquired by
hand) nothing is released. Pid files of dead processes are removed. The
serialisation matters, because labgrid-client's "already acquired" answer comes
before the resources have arrived, and the second tool would otherwise see
a place without resources.

The release itself runs in a short child process (``common._release_main``)
that the tool starts and waits for. The child takes the lock, checks again
that no tool uses the place, runs ``labgrid-client release`` and removes the
marker. Twister stops a tool with SIGTERM and sends SIGKILL 0.5 s later,
and it collects the processes to kill before the SIGTERM. A child started
after that survives the SIGKILL and finishes the release. ``labgrid-pty``
starts the release before it closes the console for the same reason. The
child runs in its own session and ignores SIGTERM, SIGINT and SIGHUP.

When labgrid-client answers that someone else holds the place, the tool
tries again every 5 s for ``--acquire-wait`` seconds. "You have already
acquired place X on HOST" means the user holds it on another host, which
counts as someone else.

A marker without any live tool means a run was killed before it could
release, with SIGKILL alone for example. The place may have been acquired
by hand since, so the next tool removes the marker, keeps the place and
tells the user to release it by hand.

The runner holds the place for the whole west process
(``common.hold_place_for_process``) and releases it from ``atexit``. ``west flash`` runs the runner once per sysbuild image in one process, and releasing
per image would let someone take the place between MCUboot and the
application. On SIGTERM (Twister's flash timeout) the runner ignores further
SIGTERMs, releases and exits.

Tools share a place by user and host only. Two Twister runs of the same
user on the same host therefore share a board instead of waiting for each
other.

Console bridge
--------------

``labgrid-pty`` copies between its stdio (Twister's pty) and the console
driver. With a ``SerialDriver`` it uses the pyserial object directly.
``ConsoleProtocol.read(timeout=...)`` sets ``serial.timeout`` on every call,
and pyserial's RFC2217 class renegotiates all port settings with ser2net
each time. At a high poll rate that lost bytes and swallowed typed shell
commands. Other console drivers go through ``ConsoleProtocol`` with one lock,
because labgrid's ``@step`` decorator keeps a global stack and asserts when
two threads use a driver at once.

Opening a remote console takes seconds (session, ssh, RFC2217). Twister
assumes the pty is ready when the process has started and flashes at once,
so the boot output was lost about one time in five.

``labgrid-pty`` writes ``console-<pid>.starting`` as soon as it knows the
place and ``console-<pid>.ready`` once the console is open, next to the lock
files. Without ``--wait-console`` the runner waits up to 30 s for the ready
marker when a live labgrid-pty for the place is starting or open. Twister
passes nothing to ``west flash`` that says a console is coming, so when the
parent process has ``twister`` in its command line (Linux ``/proc``) the
runner first looks for a starting labgrid-pty for 5 s. With Twister's
``--flash-before`` the console opens after flashing, and the runner does not
look. Hardware maps write ``--wait-console`` explicitly, 30 or 0 for boards
flashed before the console opens. An interactive ``west flash`` does not
wait.

RFC2217 purge
~~~~~~~~~~~~~

ser2net 4.6.0 never answers the RFC2217 PURGE request (labgrid issue
#1396). pyserial sends two purges in ``open()`` and waits 3 s for each, then
fails. ``labgrid-pty`` patches ``serial.rfc2217.Serial`` to send the first
purge of the process with a 1 s timeout. When it is not answered, the
process sends no more purges.

Twister behaviour this relies on
--------------------------------

From ``scripts/pylib/twister/twisterlib/handlers.py``.

-  The flash command is ``west flash --no-rebuild -d BUILD --runner RUNNER -- <--west-flash args> <runner_params>``. ``--west-flash`` args are added
   for every device, ``runner_params`` and ``base_params`` only when the entry
   has an ``id`` or ``probe_id``.
-  The runner comes from the map entry, else ``--west-runner``.
-  ``serial_pty`` is split on commas and spaces and started before the flash,
   or after it with ``flash_before``.
-  A flash failure is a non-zero exit or the flash timeout, there is no
   other signal.

Not there yet
-------------

-  ``west debug``, ``debugserver`` and ``attach`` need a gdb server mode in
   labgrid's ``OpenOCDDriver`` and port forwarding to the client. Planned as
   a labgrid contribution, and the runner will use it when it lands.
-  A real serial port for the pytest ``mcumgr`` fixture, several console
   UARTs per place, ``--erase``.

.. meta::
   :description: What to watch out for when you run Zephyr through labgrid.

.. _best-practices:

Best practices
==============

Things to watch out for when you run Zephyr through labgrid. How the
pieces work inside is in :ref:`design`.

.. _keep-lg-env-unset:

Keep LG_ENV unset
-----------------

Use ``ZEPHYR_LABGRID_ENV``, ``--env`` or the ``zephyr_env`` tag, not ``LG_ENV``.
labgrid ships a pytest plugin that turns itself on when ``LG_ENV`` is set.
Twister's pytest harness runs pytest in a subprocess that inherits your
environment, so ``LG_ENV`` loads the labgrid plugin there and fails on the
``$LG_PLACE`` template. ``LG_COORDINATOR`` is fine to export.

Hardware maps
-------------

-  Always set ``id``. Twister drops ``runner_params`` and ``base_params`` when the
   entry has neither ``id`` nor ``probe_id``.
-  Use ``serial_pty``, not ``serial``. A ``serial:`` device would need the port on
   your machine, while the pty bridge keeps the serial port on the exporter.
-  One environment file per board family, one map entry per place. Generate
   the map from labgrid tags instead of editing it by hand.
-  Give ``flash_timeout`` room. It includes copying the image to the exporter
   and starting the flash tool there. 120 s is a safe start.

Locks and parallel runs
-----------------------

-  Hold the place for interactive work, and run Twister with a map from
   ``labgrid-twister-hwmap`` when the boards are shared. Most Twister "Flash
   error" and "Serial Device Error" reports are a place that belongs to
   someone else, ``device.log`` of the test says who.
-  Run one Twister run per place and user at a time. labgrid knows a place
   owner only as host and user, so two runs of the same user on the same host
   share the board. CI executors that share a host and a user should each set
   their own ``LG_USERNAME``.
-  With a map the place is free for a moment between two tests, and another
   user can take it. The next test then waits. For a dedicated test farm,
   let a CI account hold the places for the whole run instead.
-  Do not lock places with Twister's ``pre_script`` and ``post_script``. They
   get no arguments, and their exit codes are only logged, so a failed
   acquire shows up later as a flash or serial error.
-  Every Twister worker runs its own ``west flash`` and ``labgrid-pty``. In your
   own scripts, do not share one labgrid Target object between threads or
   boards, because labgrid drivers are not thread safe.

Console
-------

-  ``labgrid-pty`` exits when its input closes. By hand, run it in a terminal
   or keep the input open (``sleep 60 | labgrid-pty ...``).
-  Expect the boot banner twice with OpenOCD, because ``reset halt`` and ``reset run``
   each start the board. Harness regexes that count lines should allow it.
-  Ask for ser2net 4.6.1 or newer on exporters. ``labgrid-pty`` works around
   4.6.0 at the cost of one second per console, it does not fix it.
-  In your own labgrid scripts, do not poll a remote console with
   ``ConsoleProtocol.read(timeout=...)`` in a tight loop. Every call
   renegotiates the RFC2217 port settings and bytes get lost.

Flashing
--------

-  Prefer the hex file, because OpenOCD and most tools take the address from it.
   For raw binaries use ``{address}`` in ``FlashScriptDriver`` args, the runner
   reads the offset from the build.
-  Never put a place name into an environment file, use
   ``!template $LG_PLACE``. The runner and ``labgrid-pty`` set it to the
   place they use.
-  With ``FlashScriptDriver``, let the script find the probe from
   ``{device.path}`` on the exporter instead of hard coding serial numbers.
   One script then serves every board of the family.
-  ``FlashScriptDriver.script`` is an image key, not a path. Put the script
   into the ``images:`` section of the environment file.
-  When console and flash share one UART (ESP32 with a USB-UART bridge),
   flash before opening the console (``zephyr_flash_before=true``, Twister
   ``--flash-before``) and reset into the open console (``--reset-rts``).
   Otherwise the boot banner is gone before the console listens.
-  When a board needs a power cycle before it can be flashed (deep sleep,
   locked debug port), add a PowerProtocol driver and use ``--power-cycle``.

Toolchain and host tools
------------------------

-  Twister treats compiler and linker warnings as errors. Toolchains other
   than the Zephyr SDK may warn more (for example ``LOAD segment with RWX permissions`` from newer binutils). Use ``-W`` or the Zephyr SDK.
-  ``gperf`` must be installed for tests with ``CONFIG_USERSPACE``, for example
   ``tests/kernel/common``.
-  Do not run the tools from a directory that contains a ``labgrid`` folder
   (a labgrid clone), because Python would import it instead of the installed
   package.

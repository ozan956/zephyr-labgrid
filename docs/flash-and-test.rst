.. meta::
   :description: Flash, reset and run Twister on a board in a labgrid lab.

.. _flash-and-test:

For Zephyr developers
=====================

You have a Zephyr workspace and want to flash, reset or test on a board in
a labgrid lab. Your daily commands stay almost the same.

.. _daily-routine:

Your routine, next to a board on your desk
------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Task
     - Board on your desk
     - Board in the lab
   * - Get the board
     - plug in the USB cable
     - ``labgrid-client -p PLACE acquire``, and ``release`` when you are done
   * - Build
     - ``west build -b BOARD app``
     - the same
   * - Flash
     - ``west flash``
     - ``west flash -r labgrid``, or ``west flash`` with labgrid as
       :ref:`default runner <default-runner>`
   * - Reset
     - ``west reset`` or the reset button
     - ``west reset -r labgrid``
   * - Console
     - ``minicom -D /dev/ttyACM0``
     - ``labgrid-pty``
   * - Debug
     - ``west debug``
     - ``west debug -r labgrid``, see :ref:`debug`
   * - Twister on your board
     - ``west twister -p BOARD --device-testing --device-serial /dev/ttyACM0 -T tests``
     - ``west twister -p BOARD --device-testing --device-serial-pty labgrid-pty --west-runner labgrid -T tests``
   * - Twister on several boards, write the map once
     - ``west twister --generate-hardware-map map.yml``
     - ``labgrid-twister-hwmap -o map.yml``
   * - Twister on several boards, run
     - ``west twister --device-testing --hardware-map map.yml -T tests``
     - the same

No command needs a place name. The runner and ``labgrid-pty`` use the
place you hold for the board. A hardware map lets each test take a place
and give it back.

What you need
-------------

You get these from your lab owner.

-  the coordinator address, for example ``lab-coordinator:20408``
-  the directory with the lab's labgrid environment files, for example
   ``/shared/labgrid-envs``

Install these on your machine, in the Python environment that runs ``west``
and ``twister``. Python 3.11 or newer is needed.

.. code-block:: console

   $ pip install "labgrid @ git+https://github.com/labgrid-project/labgrid.git"
   $ git clone https://github.com/ozan956/zephyr-labgrid.git
   $ pip install -e ./zephyr-labgrid

No labgrid release has everything the module uses yet, so install labgrid
master. ``pip install`` gives you ``labgrid-pty``,
``labgrid-twister-hwmap`` and ``labgrid-twister-check``. With ``-e`` the
tools and the runner come from the same checkout.

Enable the module
-----------------

Add it to your ``west.yml``, run ``west update`` and install that copy with
``pip install -e modules/lib/zephyr-labgrid`` instead of the clone above.

.. code:: yaml

   manifest:
     projects:
       - name: zephyr-labgrid
         url: https://github.com/ozan956/zephyr-labgrid
         revision: main
         path: modules/lib/zephyr-labgrid

Or point an existing workspace at the checkout.

.. code-block:: console

   $ export ZEPHYR_EXTRA_MODULES=/path/to/zephyr-labgrid

Every new build then has a ``labgrid`` runner in
``build/zephyr/runners.yaml``. Build directories from before need a
pristine build, ``west build -p``.

Point it at the lab
-------------------

.. code-block:: console

   $ export LG_COORDINATOR=lab-coordinator:20408
   $ export ZEPHYR_LABGRID_ENV_DIR=/shared/labgrid-envs

Put both lines into your shell profile. The runner and ``labgrid-pty``
find the environment file of a place in this order.

1. ``--env FILE`` on the command line
2. ``$ZEPHYR_LABGRID_ENV``
3. ``$LG_ENV``
4. the ``zephyr_env`` tag of the place, relative to ``--env-dir`` or
   ``$ZEPHYR_LABGRID_ENV_DIR``

Do not export ``LG_ENV``. It turns on labgrid's pytest plugin, which
Twister's pytest harness then loads too, and the plugin fails on the
``$LG_PLACE`` template.

Hold a board
------------

A labgrid place belongs to one user at a time. Take it before you work
with it and give it back afterwards.

.. code-block:: console

   $ labgrid-client places
   $ labgrid-client -p stm32f746g-disco acquire
   $ labgrid-client -p stm32f746g-disco release

``west flash``, ``west reset``, ``west debug`` and ``labgrid-pty`` never
take a place for you. When you hold none for the board, they say which places are free
and print the ``acquire`` command.

.. _check-output:

Check the setup
---------------

.. code-block:: console

   $ labgrid-twister-check -p stm32f746g-disco --tool openocd

The check covers labgrid, the tools on ``PATH``, the coordinator, the place
and its tags, the environment file, the flash tool on the exporter and the
console. Pass the tool your board flashes with, for example ``--tool
esptool``. The checks of the environment and the console need the place
held by you. Fix the ``FAIL`` lines first. On a working setup it looks like
this.

.. code-block:: text

   ok    python package labgrid 26.1.dev238
   ok    labgrid-pty found at /home/me/.venv/bin/labgrid-pty
   ok    labgrid-client found at /home/me/.venv/bin/labgrid-client
         no --env or ZEPHYR_LABGRID_ENV: the zephyr_env tag of the place is used
   ok    coordinator lab-coordinator:20408: 12 place(s), 9 with zephyr_platform tag
   ok    place stm32f746g-disco is acquired by you (myhost/me)
   ok    tag zephyr_platform=stm32f746g_disco/stm32f746xx
   ok    tag zephyr_env=stm32f746g_disco/labgrid.yaml
   ok    environment file /shared/labgrid-envs/stm32f746g_disco/labgrid.yaml from the zephyr_env tag
   ok    environment file /shared/labgrid-envs/stm32f746g_disco/labgrid.yaml loads
         drivers: SerialDriver, OpenOCDDriver
   ok    console driver present
   ok    flash driver OpenOCDDriver
   ok    resource NetworkUSBDebugger USBDebugger on exporter1: available
   ok    resource NetworkUSBFlashableDevice USBFlashableDevice on exporter1: available
   ok    resource NetworkSerialPort USBSerialPort on exporter1: available
   ok    openocd on exporter exporter1: /usr/bin/openocd
   ok    console opened in 1.3 s
   ok    RFC2217 purge answered
   all checks passed, 0 warning(s)

Flash and reset
---------------

.. code-block:: console

   $ west build -b stm32f746g_disco zephyr/samples/hello_world
   $ west flash -r labgrid
   $ west reset -r labgrid

The runner uses the place you hold whose ``zephyr_platform`` tag fits the
build. When you hold several, pick one with ``--dev-id`` or ``$LG_PLACE``.
A place whose tag does not fit the build is refused, so a native_sim
binary never ends up on an STM32 board.

Runner options go after ``--``, for example ``west flash -r labgrid --
--dev-id PLACE``.

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Option
     - Meaning
   * - ``--dev-id PLACE``
     - labgrid place (default ``$LG_PLACE``, then the place you hold for the board)
   * - ``--env FILE``
     - labgrid environment file (see the lookup order above)
   * - ``--env-dir DIR``
     - directory for a relative ``zephyr_env`` tag (default ``$ZEPHYR_LABGRID_ENV_DIR``)
   * - ``--ignore-platform``
     - flash even when the ``zephyr_platform`` tag does not fit the build
   * - ``--driver NAME``
     - labgrid driver to flash with, when the environment has more than one
   * - ``--power-cycle``
     - power cycle the place before flashing (needs a PowerProtocol driver)
   * - ``--file FILE``, ``--file-type TYPE``
     - flash a file other than the build output
   * - ``--timeout SECONDS``
     - time limit for the flash or reset script of the environment
   * - ``--wait-console SECONDS``
     - wait for a ``labgrid-pty`` on this machine to open the console before
       flashing. By default the runner waits only when one is starting, as
       under Twister. 0 never waits.
   * - ``--dry-run``
     - log what would be done, do nothing. The place must still be yours.

The environment file of the lab owner decides how the board is flashed and
reset. You only choose the image, with ``--file``.

Sysbuild builds, MCUboot with an application or images for several cores,
are flashed one image after the other in one ``west flash`` call. The place
stays yours between the images, and each image goes to its own partition.

A board that flashes over its console port, like an ESP32 dev kit, cannot
be flashed or reset while ``labgrid-pty`` has its console open. Close the
console first.

.. _debug:

Debug
~~~~~

``west debug`` writes the image and stops the board at its entry point, in
the GDB of your toolchain. ``west attach`` connects to the board without
writing anything. The environment file of the lab owner decides whether the
board is reset first.

.. code:: console

   $ west debug -r labgrid
   $ west attach -r labgrid

The debug probe stays on the exporter. labgrid starts the debug server there
and forwards its ports to your machine through SSH. CTRL+C in GDB interrupts
the board, as usual. When GDB exits, the debug server stops.

``west debugserver`` only starts the debug server and prints its ports, for
an IDE or a GDB that you start yourself. It runs until CTRL+C.

.. code:: console

   $ west debugserver -r labgrid -- --telnet-port 4444
   -- west debugserver: using runner labgrid
   debugging via labgrid place stm32f746g-disco
   gdb server of place stm32f746g-disco on localhost:3333
   telnet server of place stm32f746g-disco on localhost:4444
   stop it with CTRL+C

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Option
     - Meaning
   * - ``--gdb-port PORT``
     - the port on your machine. ``west debugserver`` uses 3333, the other
       commands a free port.
   * - ``--telnet-port PORT``, ``--tcl-port PORT``
     - also start the telnet or the TCL server of OpenOCD, on that port of
       your machine
   * - ``--driver NAME``
     - the labgrid driver with the debug server, when the environment file
       has several

The debug server keeps the debug probe busy. Do not flash or reset the place
in the meantime, OpenOCD would fail without saying why. Write a new image
with ``load`` in GDB instead, and reset the board with ``monitor reset halt``.

Debugging needs an environment file whose driver has a debug server, see
:ref:`debug-driver`.

.. _default-runner:

Make labgrid the default runner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

So that a plain ``west flash`` goes to the lab, set the runner when you
build.

.. code-block:: console

   $ west build -b stm32f746g_disco zephyr/samples/hello_world -- -DBOARD_FLASH_RUNNER=labgrid
   $ west flash

``-DBOARD_DEBUG_RUNNER=labgrid`` does the same for ``west debug``,
``west attach`` and ``west debugserver``.

For sysbuild builds keep passing ``-r labgrid``, because the option does
not reach the images of a sysbuild build.

Watch the console
-----------------

.. code-block:: console

   $ labgrid-pty

``labgrid-pty`` opens the console of the one place you hold. Pass ``-p
PLACE`` when you hold several. In a terminal it works like picocom. Every
key goes to the board, Tab, the arrow keys and Ctrl-C too. Ctrl-] exits,
and ``-l FILE`` also writes the output to a file.

Under Twister, in the background or with a pipe as input it passes the
bytes through unchanged and exits when its input closes, for example
``sleep 60 | labgrid-pty``. Boards that reset through RTS, like ESP32 dev
kits, are reset when it connects, so you see the boot banner.

Run Twister on your board
-------------------------

Where you would pass ``--device-serial /dev/ttyACM0`` for a board on your
desk, pass ``--device-serial-pty labgrid-pty --west-runner labgrid``.

.. code-block:: console

   $ west twister -p stm32f746g_disco/stm32f746xx --device-testing \
       --device-serial-pty labgrid-pty --west-runner labgrid \
       -T zephyr/tests/kernel/common

Twister starts ``labgrid-pty`` for the console and ``west flash -r
labgrid`` for every test. Both use the place you hold for the platform.
The flash waits until the console is open, so no boot output is lost.

For a board that flashes over its console port, add ``--flash-before`` so
that Twister flashes before it opens the console. Without it
``labgrid-pty`` refuses such a place and the test fails, instead of the old
firmware passing it.

.. code-block:: console

   $ west twister -p esp32_devkitc/esp32/procpu --device-testing --flash-before \
       --device-serial-pty labgrid-pty --west-runner labgrid -T zephyr/samples/hello_world

Run Twister on any free board
-----------------------------

For several boards, CI and shared boards, write a hardware map once and
run Twister with it as usual.

.. code-block:: console

   $ labgrid-twister-hwmap -p stm32f746g_disco -o map.yml
   $ west twister --device-testing --hardware-map map.yml -T zephyr/tests/kernel/common

You do not need to hold the places. Each test takes its place when it
starts and gives it back when it ends, and a place you hold already stays
yours. When someone else has the place, the test waits for it, 300 seconds
by default (``labgrid-twister-hwmap --wait SECONDS``). Twister runs one
worker per entry, so several boards of the same platform are tested in
parallel.

Without ``-p PLATFORM`` or ``--place NAME`` the map lists every board of
the lab, also those of your colleagues. Write the map again when the lab
gets new boards. How runs share boards is in :ref:`lab-twister`.

If something goes wrong
-----------------------

-  ``you hold no place for BOARD``. Take one of the free places the
   message lists, ``labgrid-client -p PLACE acquire``.
-  ``you hold several places for BOARD``. Pick one with ``--dev-id`` (or
   ``-p`` for ``labgrid-pty``).
-  ``place ... is acquired by ...``. Someone else holds it.
   ``labgrid-client places`` shows who.
-  ``place ... is for ..., the build is for ...``. The place has another
   board. Use the right place, or ``--ignore-platform``.
-  ``place ... has zephyr_env=..., a relative path``. Set
   ``ZEPHYR_LABGRID_ENV_DIR``, or pass ``--env``.
-  ``no flash driver (BootstrapProtocol or FlashScriptDriver)``. The
   environment file has no flash driver, or the place lacks the probe
   resource. Ask the lab owner.
-  ``no debug driver in ...``. The environment file has no driver that can
   debug, or several and you must pick one with ``--driver``, see
   :ref:`debug-driver`.
-  ``no debug server for place ...`` with the output of OpenOCD. When that
   output ends without an error, another program holds the debug probe,
   often a debug session that is still open.
-  ``the serial server did not answer the RFC2217 purge request``. The
   exporter runs ser2net 4.6.0, and ``labgrid-pty`` continues without
   purge, see :ref:`check-exporter-host`.
-  Twister reports ``Serial Device Error`` when ``labgrid-pty`` could not
   start. Run ``labgrid-pty`` by hand to see why.
-  Twister reports ``Timeout during flashing`` or
   ``Device issue (Flash error?)``. The cause is in ``device.log`` of the test. With
   ``unknown arguments`` there, ``--west-runner labgrid`` is missing.
-  ``cannot import name 'Environment' from 'labgrid'``. The current
   directory contains a labgrid clone. Run from another directory.
-  ``No matching distribution found for labgrid>=26.1.dev0``. Install
   labgrid master first, as shown above.
-  ``board ... does not support runner labgrid``. The build directory is
   older than the module, build again with ``west build -p``.

.. _supported:

What is supported
-----------------

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Feature
     - Status
   * - ``west flash``, with ``--file``, ``--dry-run`` and sysbuild
     - yes. OpenOCD gets the ``.hex`` or ``.elf``, never a raw ``.bin``.
       Sysbuild with MCUboot is tested on an ESP32-DevKitC.
   * - ``west reset``
     - yes, through ResetProtocol, a reset script, PowerProtocol or OpenOCD
   * - ``west debug``, ``debugserver``, ``attach``
     - yes, with ``OpenOCDDriver``. Tested on an STM32F746G-DISCO.
   * - ``west rtt``
     - no
   * - ``west flash --erase``
     - no
   * - Flash drivers
     - ``OpenOCDDriver``, other ``BootstrapProtocol`` drivers, and any tool
       through ``FlashScriptDriver`` (pyocd, dfu-util, nrfutil, esptool,
       J-Link)
   * - Interactive console
     - ``labgrid-pty`` in a terminal, or ``labgrid-client console``
   * - Twister console, ztest, gtest, pytest and shell harnesses
     - yes
   * - Twister with or without a hardware map, parallel boards, fixtures,
       ``--flash-before``, ``--retry-failed``
     - yes
   * - Waiting for a busy place
     - yes, with hardware maps, 300 s by default
   * - pytest ``mcumgr`` fixture, tools that open a serial device
     - no, the console is a pty bridge
   * - Several console UARTs per place, Twister ``required_devices``
     - no, one console per place
   * - Host operating system
     - Linux

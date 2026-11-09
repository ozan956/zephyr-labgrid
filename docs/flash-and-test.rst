.. meta::
   :description: Flash, reset and run Twister on a board in a labgrid lab.

.. _flash-and-test:

For Zephyr developers
=====================

You have a Zephyr workspace and want to flash, reset or test on a board
that is not on your desk but on a labgrid exporter in the lab. Your daily
commands stay almost the same.

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
     - not yet
   * - Twister on your board
     - ``twister -p BOARD --device-testing --device-serial /dev/ttyACM0 -T tests``
     - ``twister -p BOARD --device-testing --device-serial-pty labgrid-pty --west-runner labgrid -T tests``
   * - Twister on several boards, write the map once
     - ``twister --generate-hardware-map map.yml``
     - ``labgrid-twister-hwmap -o map.yml``
   * - Twister on several boards, run
     - ``twister --device-testing --hardware-map map.yml -T tests``
     - the same

No command needs a place name. The runner and ``labgrid-pty`` use the
place you hold for the board, and hardware maps take each place for one
test and give it back.

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

The module needs labgrid master, because no labgrid release has everything
it uses yet. ``pip install`` gives you ``labgrid-pty``,
``labgrid-twister-hwmap`` and ``labgrid-twister-check``. With ``-e`` the
tools and the runner always come from the same checkout.

Enable the module
-----------------

Add it to your ``west.yml`` and run ``west update``.

.. code:: yaml

   manifest:
     projects:
       - name: zephyr-labgrid
         url: https://github.com/ozan956/zephyr-labgrid
         revision: main
         path: modules/lib/zephyr-labgrid

or point an existing workspace at the checkout.

.. code-block:: console

   $ export ZEPHYR_EXTRA_MODULES=/path/to/zephyr-labgrid

Every build then has a ``labgrid`` runner in ``build/zephyr/runners.yaml``.

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

A labgrid place belongs to one user at a time, like a board on a desk.
Take it before you work with it and give it back afterwards.

.. code-block:: console

   $ labgrid-client places
   $ labgrid-client -p stm32f746g-disco-1 acquire
   $ labgrid-client -p stm32f746g-disco-1 release

``west flash``, ``west reset`` and ``labgrid-pty`` never take a place for
you. When you hold none for the board, they say which places are free
and print the ``acquire`` command.

.. _check-output:

Check the setup
---------------

.. code-block:: console

   $ labgrid-twister-check -p stm32f746g-disco-1 --tool openocd

prints one line per check. It covers labgrid, tools on ``PATH``,
environment variables, coordinator, place and tags, environment file,
flash tool on the exporter (``--tool esptool`` for script based flashing)
and the console. The last checks need the place held by you. Fix the
``FAIL`` lines first. On a working setup it looks like this.

.. code-block:: text

   ok    python package labgrid 26.1.dev238
   ok    labgrid-pty found at /home/me/.venv/bin/labgrid-pty
   ok    labgrid-client found at /home/me/.venv/bin/labgrid-client
         no --env or ZEPHYR_LABGRID_ENV: the zephyr_env tag of the place is used
   ok    coordinator lab:20408: 12 place(s), 9 with zephyr_platform tag
   ok    place stm32f746g-disco-1 is acquired by you (myhost/me)
   ok    tag zephyr_platform=stm32f746g_disco/stm32f746xx
   ok    tag zephyr_env=stm32f746g_disco/labgrid.yaml
   ok    environment file /shared/labgrid-envs/stm32f746g_disco/labgrid.yaml from the zephyr_env tag
   ok    environment file /shared/labgrid-envs/stm32f746g_disco/labgrid.yaml loads
         drivers: SerialDriver, OpenOCDDriver
   ok    console driver present
   ok    flash driver OpenOCDDriver
   ok    resource NetworkUSBDebugger USBDebugger on localhost: available
   ok    resource NetworkUSBFlashableDevice USBFlashableDevice on localhost: available
   ok    resource NetworkSerialPort USBSerialPort on localhost: available
   ok    openocd on exporter localhost: /usr/bin/openocd
   ok    console opened in 1.3 s
   ok    RFC2217 purge answered
   all checks passed, 0 warning(s)

Flash and reset
---------------

.. code-block:: console

   $ west build -b stm32f746g_disco samples/hello_world
   $ west flash -r labgrid
   $ west reset -r labgrid

The runner uses the place you hold whose ``zephyr_platform`` tag fits the
build. When you hold several, pick one with ``--dev-id`` or ``$LG_PLACE``.
A place whose tag does not fit the build is refused, so a native_sim
binary never ends up on an STM32 board. ``--dry-run`` prints what would
happen without flashing.

Runner options after ``--``.

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
     - flash another file than the build output
   * - ``--timeout SECONDS``
     - time limit for the flash or reset script of the environment
   * - ``--wait-console SECONDS``
     - wait for a ``labgrid-pty`` on this machine to open the console before
       flashing. By default the runner waits only when one is starting, as
       under Twister. 0 never waits.
   * - ``--dry-run``
     - log what would be done, do nothing

The runner flashes ``zephyr.hex`` if it exists, else ``zephyr.bin``, else
``zephyr.elf``. The environment file decides how, with a
``BootstrapProtocol`` driver such as OpenOCD, or with a
``FlashScriptDriver`` that runs a vendor tool on the exporter. Pick one
with ``--driver`` if the file has both.

``west reset`` uses a ResetProtocol driver, else the reset script of the lab
owner, else a PowerProtocol driver (power cycle), else OpenOCD
(``reset run``).

Sysbuild builds (MCUboot and application, several cores) are flashed one
image after the other in one ``west flash`` call, all on the same place.
The place stays yours between the images. Each image goes to its own
partition, MCUboot to the boot partition and the signed application to
slot 0. Twister builds with sysbuild when the test asks for it, as
``samples/sysbuild/with_mcuboot`` does.

For boards flashed over their console UART (ESP32 dev kits), close the
console (``labgrid-pty``, ``labgrid-client console``) before ``west flash``,
or the flash tool and the console fight over the port.

.. _default-runner:

Make labgrid the default runner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

So that a plain ``west flash`` goes to the lab, set the runner when you
build.

.. code-block:: console

   $ west build -b stm32f746g_disco samples/hello_world -- -DBOARD_FLASH_RUNNER=labgrid
   $ west flash

For sysbuild builds keep passing ``-r labgrid``, because the option does
not reach the images of a sysbuild build.

Watch the console
-----------------

.. code-block:: console

   $ labgrid-pty

``labgrid-pty`` opens the console of the one place you hold. Pass ``-p
PLACE`` when you hold several. For boards whose reset line is wired to RTS
(ESP32 dev kits) the lab owner tags the place, and ``labgrid-pty`` then
resets the board after connecting so that you see the boot banner.

In a terminal it works like picocom. Every key goes to the board, Tab,
the arrow keys and Ctrl-C too, and Ctrl-] exits. ``-l FILE`` also writes
the output to a file. Started by Twister, in the background or with a
pipe as input, it passes the bytes through unchanged and exits when its
input closes (``sleep 60 | labgrid-pty``). ``labgrid-client -p PLACE
console`` works too and needs ``microcom`` or ``telnet``.

Run Twister on your board
-------------------------

Where you would pass ``--device-serial /dev/ttyACM0`` for a board on your
desk, pass ``--device-serial-pty labgrid-pty --west-runner labgrid``.

.. code-block:: console

   $ ./scripts/twister -p stm32f746g_disco/stm32f746xx --device-testing \
       --device-serial-pty labgrid-pty --west-runner labgrid \
       -T tests/kernel/common

Twister starts ``labgrid-pty`` for the console and ``west flash -r
labgrid`` for every test. Both use the place you hold for the platform,
and the flash waits until the console is open, so no boot output is lost.

For a board whose console port is also its flash port (ESP32 with a
USB-UART bridge), add ``--flash-before``, so that Twister flashes before it
opens the console. Without it ``labgrid-pty`` refuses to open the console
of such a place, and the test fails. Otherwise the flash would fail on the
open port while the old firmware could still pass the test. A ``west
flash`` on such a place stops the same way while a ``labgrid-pty`` has its
console open.

.. code-block:: console

   $ ./scripts/twister -p esp32_devkitc/esp32/procpu --device-testing --flash-before \
       --device-serial-pty labgrid-pty --west-runner labgrid -T samples/hello_world

Run Twister on any free board
-----------------------------

For several boards, CI and shared setups, write a hardware map once, as
``twister --generate-hardware-map`` does for boards on your desk. Then run
Twister with it as usual.

.. code-block:: console

   $ labgrid-twister-hwmap -o map.yml
   $ ./scripts/twister --device-testing --hardware-map map.yml -T tests/kernel/common

You do not need to hold the places. Each test takes its place when it
starts and gives it back when it ends, and a place you hold already stays
yours. When someone else has the place, the test waits for it, 300 seconds
by default (``labgrid-twister-hwmap --wait SECONDS``). Twister runs one
worker per entry, so several boards of the same platform are tested in
parallel.

``-p PLATFORM`` and ``--place NAME`` limit the map to some places. The map
names the places, so write it again when the lab gets new boards.

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
-  ``the serial server did not answer the RFC2217 purge request``. The
   exporter runs ser2net 4.6.0, and ``labgrid-pty`` continues without
   purge, see :ref:`check-exporter-host`.
-  Twister reports ``Serial Device Error`` when ``labgrid-pty`` could not
   start. Run ``labgrid-pty`` by hand to see why.
-  Twister reports ``Timeout during flashing`` or
   ``Device issue (Flash error?)``. The cause is in ``device.log`` of the test. With
   ``unknown arguments`` there, ``--west-runner labgrid`` is missing.
-  ``cannot import name 'Environment' from 'labgrid'``. The current
   directory contains a ``labgrid`` folder (a labgrid clone). Run from
   another directory.

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
       Sysbuild with MCUboot is tried on an ESP32-DevKitC.
   * - ``west reset``
     - yes, through ResetProtocol, a reset script, PowerProtocol or OpenOCD
   * - ``west debug``, ``debugserver``, ``attach``, ``rtt``
     - not yet, it needs a GDB server in labgrid
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

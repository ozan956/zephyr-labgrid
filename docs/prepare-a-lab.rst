.. meta::
   :description: Prepare labgrid places, environment files and tags for Zephyr users.

.. _prepare-a-lab:

For lab owners
==============

You run a labgrid coordinator and exporters, and Zephyr users want to flash
and test on your boards. For every board you do six things.

1. :ref:`Export the probe and the serial port <lab-export>`.
2. :ref:`Write an environment file <lab-env>` that says how the board is
   flashed.
3. :ref:`Create a place and tag it <lab-place>`.
4. :ref:`Share the environment files <lab-share>` with your users.
5. :ref:`Check the exporter host <check-exporter-host>`.
6. :ref:`Test the place yourself <lab-test>`.

Your users then need the coordinator address and the directory with the
environment files, nothing else. The last section explains how they
:ref:`share the boards in Twister runs <lab-twister>`. To try all of this
on one machine first, see :ref:`quickstart`.

.. _lab-export:

1. Export the probe and the serial port
---------------------------------------

Most Zephyr boards have an on-board debug probe that also provides the
serial console, so one USB device gives two resources. Match both on the
serial number of the probe, so that they stay together. Find it with
``udevadm info -q property -n /dev/ttyACM0``.

.. code:: yaml

   # exporter.yaml
   stm32f746g-disco-1:
     USBDebugger:
       match:
         ID_SERIAL_SHORT: '066CFF505356867767051752'
     USBSerialPort:
       match:
         ID_SERIAL_SHORT: '066CFF505356867767051752'
         ID_USB_INTERFACE_NUM: '02'
       speed: 115200

``USBDebugger`` knows ST-Link, J-Link, CMSIS-DAP, FTDI and Olimex probes,
which OpenOCD uses. A flash script instead needs the device as a
``USBFlashableDevice``, with the same match plus the device type.

.. code:: yaml

     USBFlashableDevice:
       match:
         ID_SERIAL_SHORT: '066CFF505356867767051752'
         SUBSYSTEM: 'usb'
         DEVTYPE: 'usb_device'

Add a power switch of the board (USB hub port, relay, PDU) when you have
one. Users can then power cycle a board that hangs.

.. _lab-env:

2. Write an environment file
----------------------------

The environment file says how a board is flashed and where its console
is. Write one per board family. The place name comes from ``LG_PLACE``,
which the runner sets, so the same file serves every board of the family.

.. code:: yaml

   # stm32f7/labgrid.yaml
   targets:
     main:
       resources:
         RemotePlace:
           name: !template $LG_PLACE
       drivers:
         SerialDriver: {}
         OpenOCDDriver:
           board_config: stm32f746g-disco.cfg
           load_commands:
             - init
             - reset halt
             - flash write_image erase {filename}
             - verify_image {filename}
             - reset run
             - shutdown

Pick the flash driver by how the board is flashed.

.. list-table::
   :header-rows: 1
   :widths: 30 25 45

   * - The board is flashed
     - Driver
     - What to do
   * - by a probe that OpenOCD supports
     - ``OpenOCDDriver``
     - Set ``board_config`` or ``config``, as above. OpenOCD picks the probe
       by its USB path, so several probes on one exporter are fine.
   * - by a vendor tool (STM32CubeProgrammer, J-Link Commander, nrfutil,
       pyocd, dfu-util)
     - ``FlashScriptDriver``
     - Write a small script that runs the tool, see below.
   * - over its console UART (ESP32 dev kits)
     - ``FlashScriptDriver``
     - A script as above, plus the tags ``zephyr_flash_before`` and
       ``zephyr_reset_rts`` on the place, see step 3.

Keep the ``SerialDriver``, ``labgrid-pty`` uses it for the console.

Flash scripts
~~~~~~~~~~~~~

labgrid copies the script and the Zephyr image to the exporter and runs the
script there, so the tool only needs to exist on the exporter. Put the
script next to the environment file and name it in ``images``. The runner
fills in ``{image}``, the path of the image on the exporter, and
``{address}``, the flash address from the build. labgrid fills in
``{device.path}``, the USB path of the probe, from which the script reads
the serial number, and ``{device.devnode}``, the device node.

.. code:: yaml

   images:
     flash-script: stm32cubeprog-flash.sh     # relative to this file
   targets:
     main:
       resources:
         RemotePlace:
           name: !template $LG_PLACE
       drivers:
         SerialDriver: {}
         FlashScriptDriver:
           script: flash-script
           args: ["{device.path}", "{image}"]

labgrid runs the script over ssh with a small ``PATH``. Install the tool
on that ``PATH``, or let the script look for it in the usual places, as the
example scripts do.

Reset without flashing
~~~~~~~~~~~~~~~~~~~~~~

``west reset -r labgrid`` uses a ``ResetProtocol`` driver, an OpenOCD driver
or a power switch. When only a vendor tool can reset the board, add the
command as a second ``FlashScriptDriver`` named ``reset``. Two drivers of
the same class need the list form of ``drivers``.

.. code:: yaml

   drivers:
     - SerialDriver: {}
     - FlashScriptDriver:
         script: flash-script
         args: ["{device.path}", "{address}", "{image}"]
     - FlashScriptDriver:
         name: reset
         script: reset-script
         args: ["{device.path}"]

Examples in the repository
~~~~~~~~~~~~~~~~~~~~~~~~~~

``examples/`` has complete environment files and scripts for these boards.

.. list-table::
   :header-rows: 1
   :widths: 22 22 56

   * - Board
     - Flashed with
     - Good to know
   * - STM32F746G-DISCO
     - OpenOCD, or STM32CubeProgrammer through a script
     - Nothing special. ``labgrid.yaml`` and ``labgrid-stm32cubeprog.yaml``
       are the two ways.
   * - ESP32-DevKitC
     - esptool through a script, over the console UART
     - Export the tty a second time as ``USBFlashableDevice`` matched on
       ``SUBSYSTEM: tty``, and tag the place with
       ``zephyr_flash_before=true`` and ``zephyr_reset_rts=true``. Without
       them the console blocks the flash, or the boot banner is gone before
       the console opens.
   * - Alif Ensemble E8 DevKit
     - J-Link Commander through ``jlink.sh``, with a reset script
     - Install the SEGGER J-Link software on the exporter, and leave SW4 in
       the UART4 position for the console. Once per board, write a table
       of images that boots the M55 HP core from MRAM, with the Alif
       Security Toolkit over the SE-UART (SW4 in the SE-UART position).
       Without it the core does not run and the J-Link can not attach.
       Copy ``zephyr.bin`` of any build to ``build/images/`` and
       ``zephyr-hp.json`` to ``build/config/`` of the toolkit, then run
       ``app-gen-toc -f build/config/zephyr-hp.json`` and
       ``app-write-mram -c /dev/ttyACM1``.

.. _lab-place:

3. Create a place and tag it
----------------------------

.. code-block:: console

   $ labgrid-client -p stm32f746g-disco-1 create
   $ labgrid-client -p stm32f746g-disco-1 add-match "exporter1/stm32f746g-disco-1/*"
   $ labgrid-client -p stm32f746g-disco-1 set-tags \
       zephyr_platform=stm32f746g_disco/stm32f746xx \
       zephyr_env=stm32f7/labgrid.yaml

labgrid ignores these tags, the zephyr-labgrid tools read them. The first
two are needed, the others when the board needs them.

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Tag
     - Meaning
   * - ``zephyr_platform``
     - Zephyr board target with the SoC qualifier. The runner picks the
       place of a user by it and refuses a build for another board.
   * - ``zephyr_env``
     - environment file of the place, relative to the directory you share
       in step 4
   * - ``zephyr_flash_before``
     - ``true`` when the console port is also the flash port, so that
       Twister flashes before it opens the console
   * - ``zephyr_reset_rts``
     - ``true`` when the reset line is wired to RTS, so that
       ``labgrid-pty`` resets the board after connecting
   * - ``zephyr_fixtures``
     - comma separated Twister fixtures (loopback wires, sensors)
   * - ``zephyr_flash_timeout``
     - seconds for one flash, when Twister's default is too short

.. _lab-share:

4. Share the environment files
------------------------------

Put the environment files and their scripts in one directory tree and let
your users read it, as a git repository they clone, an NFS share or a copy
in the CI image. Users point ``ZEPHYR_LABGRID_ENV_DIR`` at it, and the
relative ``zephyr_env`` tags then work wherever each user has the copy.

.. _check-exporter-host:

5. Check the exporter host
--------------------------

-  ser2net 4.6.1 or newer. ser2net 4.6.0 (Ubuntu 24.04) never answers the
   RFC2217 purge request. ``labgrid-pty`` notices it and continues without
   purge, at the cost of one second per console. See labgrid issue #1396.
-  openocd 0.11 or newer, so that USB path selection works with several
   probes on one host.
-  udev rules that give the exporter user access to the probes, the
   ``plugdev`` group or the rules of the vendor.
-  No ModemManager probing of the serial ports, it sends AT commands into the
   board console. Disable it, or blacklist the vendor and product ID of the
   probe.

.. _lab-test:

6. Test the place yourself
--------------------------

Before you hand the place out, go through the loop of a user once.

.. code-block:: console

   $ export LG_COORDINATOR=lab:20408 ZEPHYR_LABGRID_ENV_DIR=/shared/labgrid-envs
   $ labgrid-client -p stm32f746g-disco-1 acquire
   $ labgrid-twister-check -p stm32f746g-disco-1 --tool openocd
   $ west build -b stm32f746g_disco samples/hello_world
   $ west flash -r labgrid
   $ labgrid-pty &
   $ west reset -r labgrid
   $ kill %1
   $ labgrid-client -p stm32f746g-disco-1 release

The check should print no ``FAIL``, and the console should show
``Hello World!`` after the reset. Then run ``samples/hello_world`` and
``samples/subsys/testsuite/pytest/shell`` with Twister. The second one
checks that typing into the console works too.

.. _lab-twister:

Sharing the boards in Twister runs
----------------------------------

A labgrid place belongs to one user at a time. There are three ways to
share the boards, pick one per group of places.

1. **Users hold places for their own work.** A developer acquires a place,
   uses it with ``west`` and Twister, and releases it. Good for interactive
   work.
2. **Twister takes places per test.** Write a hardware map once with
   ``labgrid-twister-hwmap -o map.yml``. Each test takes its place when it
   starts and gives it back when it ends, and waits up to 300 seconds when
   someone else has it (``--wait SECONDS``). Good for shared boards and CI.
3. **A CI account holds the places.** It acquires all places once and runs
   Twister with a map. The tests never release a place that was held
   before, so the places stay with the account. Good for a test farm.

The map tool reads the tags of step 3, finds the environment files as the
runner does, and ``-p PLATFORM`` or ``--place NAME`` limit it to some places.
Write the map again when the lab gets new boards. One entry looks like this.

.. code:: yaml

   - connected: true
     id: stm32f746g-disco-1
     platform: stm32f746g_disco/stm32f746xx
     product: labgrid
     runner: labgrid
     runner_params:
       - --dev-id=stm32f746g-disco-1
       - --env=/shared/labgrid-envs/stm32f7/labgrid.yaml
       - --acquire
       - --acquire-wait=300
     serial_pty: "labgrid-pty,-p,stm32f746g-disco-1,-e,/shared/labgrid-envs/stm32f7/labgrid.yaml,--acquire,--acquire-wait=300"
     flash_timeout: 360

``--acquire`` and ``--acquire-wait`` are meant for generated maps, users never
type them. ``flash_timeout`` includes the wait for a busy place.

labgrid knows the owner of a place only as host and user, so two Twister
runs of the same user on the same host share a board instead of waiting
for each other. CI executors on one host and user should each set their
own ``LG_USERNAME``.

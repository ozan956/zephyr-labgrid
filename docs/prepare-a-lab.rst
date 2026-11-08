.. meta::
   :description: Prepare labgrid places, environment files and tags for Zephyr users.

.. _prepare-a-lab:

For lab owners
==============

You run a labgrid coordinator and exporters. Zephyr users want to flash and
run Twister on your boards. This page explains what to prepare for them.

In short, give every Zephyr board a place with a probe resource and
a serial resource, write one labgrid environment file per board family with
a flash driver, put the files in a directory your users can read, and tag
each place with ``zephyr_platform`` and ``zephyr_env``. Users then need only
the coordinator address, the place name and that directory.

To try all of this on one machine first, see :ref:`quickstart`.

1. Export the probe and the serial port
---------------------------------------

Most Zephyr boards have an on-board debug probe (ST-Link, J-Link OB,
CMSIS-DAP) that also provides the serial console. One USB device gives two
resources. Match both on the probe serial number so they stay together.

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

``USBDebugger`` knows ST-Link, J-Link, CMSIS-DAP (KitProg3), FTDI and Olimex
probes. For other probes check ``labgrid/resource/udev.py`` or use a generic
``USBResource`` with your own match.

Find the values with ``udevadm info -q property -n /dev/ttyACM0``.

If you want to flash with a vendor tool instead of OpenOCD (see step 3),
also export the probe as a generic ``USBFlashableDevice``. It is the same USB
device, so use the same match plus the device type.

.. code:: yaml

     USBFlashableDevice:
       match:
         ID_SERIAL_SHORT: '066CFF505356867767051752'
         SUBSYSTEM: 'usb'
         DEVTYPE: 'usb_device'

If the board has a separate power switch (USB hub port, relay, PDU) add it
too. Zephyr users benefit from ``--power-cycle`` and from ``labgrid-client power cycle`` when a board hangs.

2. Create the place and tag it
------------------------------

.. code-block:: console

   $ labgrid-client -p stm32f746g-disco-1 create
   $ labgrid-client -p stm32f746g-disco-1 add-match "exporter1/stm32f746g-disco-1/*"
   $ labgrid-client -p stm32f746g-disco-1 set-tags \
       zephyr_platform=stm32f746g_disco/stm32f746xx \
       zephyr_env=stm32f7/labgrid.yaml

labgrid itself ignores these tags. The zephyr-labgrid tools read them.

.. list-table::
   :header-rows: 1
   :widths: 25 25 50

   * - Tag
     - Used by
     - Meaning
   * - ``zephyr_platform``
     - runner, ``labgrid-pty``, hwmap
     - full Zephyr board target, with the SoC qualifier. The runner picks the
       user's place for a build by it and refuses a build for another
       board. ``labgrid-pty`` picks the place for a Twister platform by it.
   * - ``zephyr_env``
     - runner, ``labgrid-pty``, check, hwmap
     - environment file of the place, a relative path is resolved against
       the user's ``ZEPHYR_LABGRID_ENV_DIR``
   * - ``zephyr_fixtures``
     - hwmap
     - comma separated Twister fixtures (loopback wires, sensors)
   * - ``zephyr_flash_before``
     - hwmap
     - ``true`` when the console port is also the flash port (step 3)
   * - ``zephyr_pty_args``
     - ``labgrid-pty``, hwmap
     - comma separated extra ``labgrid-pty`` arguments, for example
       ``--reset-rts``
   * - ``zephyr_flash_timeout``
     - hwmap
     - seconds for one flash. Without it Twister's
       ``--device-flash-timeout`` applies.

With these tags set, the runner and ``labgrid-pty`` find the place and its
environment file by themselves. Users only need the coordinator address.

Share the environment files
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Put the environment files, and the flash scripts they reference, in one
directory tree and give users read access, for example as a git repository they clone, an
NFS share, or a copy in the CI image. Users point ``ZEPHYR_LABGRID_ENV_DIR``
at it. Relative ``zephyr_env`` tags keep the places independent of where each
user has the directory.

3. Write a labgrid environment file per board family
----------------------------------------------------

The environment file tells the runner how to flash and how to reach the
console. The place name is taken from ``LG_PLACE``, which the runner sets
from ``--dev-id``, so one file serves all boards of the same family.

.. code:: yaml

   # labgrid-stm32f7.yaml
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

The flash driver is either a driver that implements labgrid's
``BootstrapProtocol`` or a ``FlashScriptDriver``. Options today.

+----------------------+----------------------+----------------------+
| Driver               | Tool on the exporter | Notes                |
+======================+======================+======================+
| ``OpenOCDDriver``    | openocd >= 0.11      | Works for ST-Link,   |
|                      |                      | CMSIS-DAP, J-Link    |
|                      |                      | with OpenOCD         |
|                      |                      | support. Uses the    |
|                      |                      | USB path, so several |
|                      |                      | probes on one        |
|                      |                      | exporter are fine.   |
|                      |                      | Tested.              |
+----------------------+----------------------+----------------------+
| `                    | anything             | Runs your script on  |
| `FlashScriptDriver`` |                      | the exporter. Use it |
|                      |                      | for pyocd, dfu-util, |
|                      |                      | nrfutil, esptool,    |
|                      |                      | STM32CubeProgrammer, |
|                      |                      | J-Link Commander and |
|                      |                      | other vendor tools.  |
|                      |                      | Tested with          |
|                      |                      | STM32CubeProgrammer  |
|                      |                      | and esptool, see     |
|                      |                      | below.               |
+----------------------+----------------------+----------------------+

The image file is copied to the exporter by labgrid before the tool runs,
so the tool only needs to exist on the exporter.

Vendor tools through FlashScriptDriver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``FlashScriptDriver`` copies a script of yours to the exporter and runs it
there. The runner copies the Zephyr image as well and replaces ``{image}`` in
``args`` with its path on the exporter. labgrid fills in ``{device.path}``, the
sysfs USB path of the probe, which the script can turn into a serial number.

.. code:: yaml

   # labgrid-stm32cubeprog.yaml
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
           args:
             - "{device.path}"
             - "{image}"

``examples/stm32f746g_disco/stm32cubeprog-flash.sh`` is a complete example.
It reads the ST-Link serial from ``/sys/bus/usb/devices/<path>/serial``, finds
``STM32_Programmer_CLI`` and runs it with ``-c port=SWD sn=... -w <image> -v -rst``. Write the same kind of script for nrfutil, esptool or J-Link. Keep
the script next to the environment file and put the tool on the exporter.

Keep ``SerialDriver`` in the file. ``labgrid-pty`` uses the ConsoleProtocol
driver it finds, and the runner does not touch it.

If you add a ``PowerProtocol`` or ``ResetProtocol`` driver, ``--reset`` and
``--power-cycle`` start to work.

When only a vendor tool can reset the board, add the command as a second
``FlashScriptDriver`` named ``reset``, and ``west reset -r labgrid`` runs it.
labgrid needs the list form of ``drivers`` for two drivers of the same
class. ``examples/ensemble_e8_dk/labgrid-hp.yaml`` does this with the reset
pin of a J-Link.

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

Boards flashed over the console UART (ESP32 and friends)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

ESP32 dev kits with a USB-UART bridge have no debug probe. esptool flashes
over the same serial port that is the console, and the bridge's DTR/RTS
lines drive boot mode and reset. Three things follow.

-  Export the tty twice, as ``USBSerialPort`` for the console and as
   ``USBFlashableDevice`` matched on ``SUBSYSTEM: tty``, so the flash script
   gets the device node as ``{device.devnode}``.
-  The console must be closed while flashing. Tag the place with
   ``zephyr_flash_before=true``. Twister then flashes first and opens the
   console afterwards.
-  After the console is opened the board has already booted, so the banner
   would be lost. Tag the place with ``zephyr_pty_args=--reset-rts``.
   ``labgrid-pty`` then pulses RTS over RFC2217 right after connecting and the
   board boots again into the open console.

The image is a raw ``.bin``, so the script also needs the flash offset. The
runner fills ``{address}`` from the build, ``CONFIG_FLASH_BASE_ADDRESS`` plus
``CONFIG_FLASH_LOAD_OFFSET`` where those exist, otherwise the devicetree
partition Zephyr's own esp32 runner uses. See
``examples/esp32_devkitc/labgrid-esp32.yaml`` and ``esptool-flash.sh``.

labgrid runs the script over ssh with a small PATH. Install esptool where
the script can find it, on ``PATH``, in ``~/.local/bin``, or as a module of the
system ``python3``.

Alif Ensemble boards with the on-board J-Link
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Ensemble E8 DevKit shows up on USB as a SEGGER J-Link (``1366:1024``)
with one serial port. The J-Link writes the image into MRAM over SWD, and
the serial port carries the console. Four things differ from the boards
above.

-  The M55 cores only run when the Secure Enclave starts them from its
   table of images (ATOC), and the J-Link can not attach to a core that does
   not run. Write an ATOC that boots the core from MRAM once per board with
   the Alif Security Toolkit (SETOOLS) over the SE-UART. Put SW4 in the
   SE-UART position, copy ``zephyr.bin`` of any build to ``build/images/``
   and ``examples/ensemble_e8_dk/zephyr-hp.json`` to ``build/config/`` of
   the SETOOLS directory, then run the two commands below. After that the
   J-Link writes every new image to the same MRAM address, and the Secure
   Enclave boots it without checking it, because the entry is unsigned.

   .. code-block:: console

      $ ./app-gen-toc -f build/config/zephyr-hp.json
      $ ./app-write-mram -c /dev/ttyACM1

-  The serial port reaches one UART at a time, set by SW4. Leave SW4 in the
   UART4 position, the console of the M55 HP core. The boot messages of the
   Secure Enclave appear on that port too, before the Zephyr banner.
-  Install the SEGGER J-Link software on the exporter. ``jlink-flash.sh``
   looks for ``JLinkExe`` on ``PATH``, in ``/opt/SEGGER/JLink`` and in
   ``~/opt/SEGGER-JLink``.
-  A core reset does not start the new image. ``jlink-flash.sh`` pulls the
   reset pin after writing, so the Secure Enclave restarts and boots it.
   ``jlink-reset.sh``, the reset script of the environment, does the same
   for ``west reset``.

Export the J-Link twice, as ``USBFlashableDevice`` for the flash script and
as ``USBSerialPort`` for the console, both matched on its serial number.

.. code:: yaml

   ensemble-e8-dk:
     USBSerialPort:
       match:
         ID_SERIAL_SHORT: '001219407405'
         ID_USB_INTERFACE_NUM: '00'
       speed: 115200
     USBFlashableDevice:
       match:
         ID_SERIAL_SHORT: '001219407405'
         SUBSYSTEM: 'usb'
         DEVTYPE: 'usb_device'

Tag the place with ``zephyr_platform=ensemble_e8_dk/ae822fa0e5597ls0/rtss_hp``
and ``zephyr_env=ensemble_e8_dk/labgrid-hp.yaml``. The environment file
passes the J-Link device name of the core to the flash script.

4. Hand out hardware map entries
--------------------------------

Each place needs one entry. ``labgrid-twister-hwmap`` writes them from the
tags of step 2.

.. code-block:: console

   $ labgrid-twister-hwmap -x lab-coordinator:20408 --env-dir /shared/labgrid-envs -o hwmap.yaml

It reads the tags from the table in step 2 and skips places without
``zephyr_platform``. It finds the environment files as the runner does, so
``--env FILE`` sets one file for every place, and ``-p PLATFORM`` or
``--place NAME`` limit the map to some places. ``--env-dir`` defaults to
``$ZEPHYR_LABGRID_ENV_DIR``.

Every entry makes a test take its place when it starts and give it back
when it ends, so users run Twister with the map without holding the places.
A place the user holds already stays theirs. When someone else holds a
place, the test waits for it up to ``--wait SECONDS`` (default 300), and
``flash_timeout`` grows by that time. Places in use when the map is written
stay in it with a note. For a single board that the user holds, no map is
needed, see :ref:`flash-and-test`.

The result looks like this.

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
       - --wait-console=30
     serial_pty: "labgrid-pty,-p,stm32f746g-disco-1,-e,/shared/labgrid-envs/stm32f7/labgrid.yaml,--acquire,--acquire-wait=300"
     flash_timeout: 360

``--acquire`` and ``--acquire-wait`` are not in the help of the runner and of
``labgrid-pty``. They are meant for generated maps, users never type them.

Things to keep in mind about the entries.

-  ``id`` must be set. Twister ignores ``runner_params`` when it is empty.
-  ``flash_timeout`` counts the whole ``west flash`` call, including the
   wait for a busy place and the file copy to the exporter.
-  ``fixtures`` describe extra hardware (loopback wires, sensors). They map
   well to labgrid tags, so add them when you generate the map.

5. Decide who owns the lock
---------------------------

labgrid and Twister both have locks and do not know about each other.

-  Twister locks a DUT inside one Twister run. It protects against its own
   parallel workers only.
-  labgrid locks a place for one user across the whole lab.

Three ways to share the boards.

1. **Users hold places for their own work.** A developer takes a place with
   ``labgrid-client acquire``, works with ``west flash -r labgrid`` and
   Twister on it, and releases it afterwards. Good for interactive use.
2. **Hardware maps take places per test.** Twister runs with a map from
   ``labgrid-twister-hwmap``, each test takes its place and gives it back.
   The tools on one host coordinate through a small lock directory
   (``$TMPDIR/zephyr-labgrid-<uid>/``), so the flash does not release the
   place while the console is still open. Between two tests the place is
   free for a moment, so another user can take it, and the next test then
   waits for it. Good for shared boards and for CI.
3. **A CI account holds the places.** It acquires all Zephyr places once,
   and Twister runs under that account with a map. The tests keep the
   places, because they never release a place that was held before. Other
   users see the places as busy. Good for a dedicated test farm.

labgrid knows a place owner only as host and user. Two Twister runs of the
same user on the same host therefore share a board instead of waiting for
each other. CI executors that share a host and a user should each set their
own ``LG_USERNAME``.

.. _check-exporter-host:

6. Check the exporter host
--------------------------

-  ser2net 4.6.1 or newer. ser2net 4.6.0 (Ubuntu 24.04) never answers the
   RFC2217 purge request, and plain pyserial times out on open. ``labgrid-pty``
   detects this and continues without purge, at the cost of one second
   per console. See labgrid issue #1396.
-  openocd 0.11 or newer so that USB path selection works with several
   probes on one host.
-  udev rules that give the exporter user access to the probes
   (``plugdev`` group or the vendor rules).
-  Disable ModemManager probing of the USB serial ports, or blacklist the
   probe vendor and product ID. It sends AT commands into the board console.

7. Test the place yourself
--------------------------

Before handing a place to users, do the full loop once.

.. code-block:: console

   $ export LG_COORDINATOR=... ZEPHYR_LABGRID_ENV_DIR=/shared/labgrid-envs
   $ labgrid-client -p stm32f746g-disco-1 acquire
   $ labgrid-twister-check -p stm32f746g-disco-1 --tool openocd   # every line ok
   $ west build -b stm32f746g_disco samples/hello_world
   $ west flash -r labgrid
   $ labgrid-pty &                    # console
   $ west reset -r labgrid            # expect "Hello World!"
   $ kill %1
   $ labgrid-client -p stm32f746g-disco-1 release

Then run one Twister suite, with or without the hardware map entry. ``samples/hello_world``
checks the console path, ``samples/subsys/testsuite/pytest/shell`` checks that
writing into the console works too.

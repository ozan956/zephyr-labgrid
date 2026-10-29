# For lab owners

You run a labgrid coordinator and exporters. Zephyr users want to flash and
run Twister on your boards. This page explains what to prepare for them.

The short version: give every Zephyr board a place with a probe resource and
a serial resource, write one labgrid environment file per board family with
a flash driver, and hand out hardware map entries.

## 1. Export the probe and the serial port

Most Zephyr boards have an on-board debug probe (ST-Link, J-Link OB,
CMSIS-DAP) that also provides the serial console. One USB device gives two
resources. Match both on the probe serial number so they stay together.

```yaml
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
```

`USBDebugger` knows ST-Link, J-Link, CMSIS-DAP (KitProg3), FTDI and Olimex
probes. For other probes check `labgrid/resource/udev.py` or use a generic
`USBResource` with your own match.

Find the values with `udevadm info -q property -n /dev/ttyACM0`.

If you want to flash with a vendor tool instead of OpenOCD (see step 3),
also export the probe as a generic `USBFlashableDevice`. It is the same USB
device, so use the same match plus the device type:

```yaml
  USBFlashableDevice:
    match:
      ID_SERIAL_SHORT: '066CFF505356867767051752'
      SUBSYSTEM: 'usb'
      DEVTYPE: 'usb_device'
```

If the board has a separate power switch (USB hub port, relay, PDU) add it
too. Zephyr users benefit from `--power-cycle` and from `labgrid-client
power cycle` when a board hangs.

## 2. Create the place and tag it

```sh
labgrid-client -p stm32f746g-disco-1 create
labgrid-client -p stm32f746g-disco-1 add-match "exporter1/stm32f746g-disco-1/*"
labgrid-client -p stm32f746g-disco-1 set-tags \
    zephyr_platform=stm32f746g_disco/stm32f746xx \
    zephyr_env=stm32f7
```

The tags are not used by labgrid itself. They let you generate Twister
hardware maps later and tell users which environment file fits the board.
Use the full Zephyr board target name, with the SoC qualifier.

## 3. Write a labgrid environment file per board family

The environment file tells the runner how to flash and how to reach the
console. The place name is taken from `LG_PLACE`, which the runner sets
from `--dev-id`, so one file serves all boards of the same family.

```yaml
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
```

The flash driver must implement labgrid's `BootstrapProtocol`. Options
today:

| Driver | Tool on the exporter | Notes |
|---|---|---|
| `OpenOCDDriver` | openocd >= 0.11 | Works for ST-Link, CMSIS-DAP, J-Link with OpenOCD support. Uses the USB path, so several probes on one exporter are fine. Tested. |
| `DFUDriver` | dfu-util | Boards with a DFU bootloader. |
| `FlashScriptDriver` | anything | Runs your script on the exporter. Use it for nrfutil, esptool, STM32CubeProgrammer, J-Link Commander and other vendor tools. Tested with STM32CubeProgrammer, see below. |
| `PyOCDDriver` | pyocd | Pending in labgrid PR #1944. |

The image file is copied to the exporter by labgrid before the tool runs,
so the tool only needs to exist on the exporter.

### Vendor tools through FlashScriptDriver

`FlashScriptDriver` copies a script of yours to the exporter and runs it
there. The runner copies the Zephyr image as well and replaces `{image}` in
`args` with its path on the exporter. labgrid fills in `{device.path}`, the
sysfs USB path of the probe, which the script can turn into a serial number.

```yaml
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
```

`examples/stm32f746g_disco/stm32cubeprog-flash.sh` is a complete example.
It reads the ST-Link serial from `/sys/bus/usb/devices/<path>/serial`, finds
`STM32_Programmer_CLI` and runs it with `-c port=SWD sn=... -w <image> -v
-rst`. Write the same kind of script for nrfutil, esptool or J-Link. Keep
the script next to the environment file and put the tool on the exporter.

Keep `SerialDriver` in the file. `labgrid-pty` uses the ConsoleProtocol
driver it finds, and the runner does not touch it.

If you add a `PowerProtocol` or `ResetProtocol` driver, `--reset` and
`--power-cycle` start to work.

### Boards flashed over the console UART (ESP32 and friends)

ESP32 dev kits with a USB-UART bridge have no debug probe. esptool flashes
over the same serial port that is the console, and the bridge's DTR/RTS
lines drive boot mode and reset. Three things follow:

- Export the tty twice: as `USBSerialPort` for the console and as
  `USBFlashableDevice` matched on `SUBSYSTEM: tty`, so the flash script
  gets the device node as `{device.devnode}`.
- The console must be closed while flashing. Tag the place with
  `zephyr_flash_before=true`; Twister then flashes first and opens the
  console afterwards.
- After the console is opened the board has already booted, so the banner
  would be lost. Tag the place with `zephyr_pty_args=--reset-rts`;
  `labgrid-pty` then pulses RTS over RFC2217 right after connecting and the
  board boots again into the open console.

The image is a raw `.bin`, so the script also needs the flash offset. The
runner fills `{address}` from the build: `CONFIG_FLASH_BASE_ADDRESS` plus
`CONFIG_FLASH_LOAD_OFFSET` where those exist, otherwise the devicetree
partition Zephyr's own esp32 runner uses. See
`examples/esp32_devkitc/labgrid-esp32.yaml` and `esptool-flash.sh`.

labgrid runs the script over ssh with a small PATH. Install esptool where
the script can find it: on `PATH`, in `~/.local/bin`, or as a module of the
system `python3`.

## 4. Hand out hardware map entries

Each place needs one entry. `labgrid-twister-hwmap` writes them from the
tags of step 2:

```sh
labgrid-twister-hwmap -x lab-coordinator:20408 --env-dir /shared/labgrid-envs -o hwmap.yaml
```

Tags it reads: `zephyr_platform` (required), `zephyr_env` (file name,
resolved against `--env-dir`), `zephyr_fixtures` (comma separated),
`zephyr_flash_timeout`, `zephyr_flash_before` (true/false) and
`zephyr_pty_args` (comma separated extra arguments for `labgrid-pty`). `--env FILE` is the fallback for places without a
`zephyr_env` tag, `--force-env FILE` overrides the tag for every place. With `--hooks DIR` it also writes one acquire and
one release script per place and references them as `pre_script` and
`post_script`. Places that are acquired by someone get a `notes` line.

The result looks like this:

```yaml
- connected: true
  id: stm32f746g-disco-1
  platform: stm32f746g_disco/stm32f746xx
  product: labgrid
  runner: labgrid
  runner_params:
    - --dev-id=stm32f746g-disco-1
    - --env=/shared/labgrid-stm32f7.yaml
  serial_pty: "labgrid-pty,-p,stm32f746g-disco-1,-e,/shared/labgrid-stm32f7.yaml"
  flash_timeout: 120
  fixtures: []
```

Notes:

- `id` must be set. Twister ignores `runner_params` when it is empty.
- `flash_timeout` counts the whole `west flash` call including the file copy
  to the exporter. 120 s is a safe start.
- Twister passes no arguments and no extra environment to `pre_script`,
  `post_script` and `post_flash_script`. If you want them to acquire and
  release the place, write one tiny script per place or read the place name
  from a file next to the script.
- `fixtures` describe extra hardware (loopback wires, sensors). They map
  well to labgrid tags; add them when you generate the map.

## 5. Decide who owns the lock

labgrid and Twister both have locks and do not know about each other.

- Twister locks a DUT inside one Twister run. It protects against its own
  parallel workers only.
- labgrid locks a place for one user across the whole lab.

Two simple models that work:

1. **Users acquire by hand.** The developer runs `labgrid-client acquire`
   before Twister and `release` after. Good for interactive use.
2. **CI user holds the places.** A CI account acquires all Zephyr places
   once; Twister runs under that account. Other users see the places as
   busy. Good for a dedicated test farm.

Mixing both on the same places leads to `Flash error` or `Serial Device
Error` in Twister when the place is taken. Reservations
(`labgrid-client reserve`) can bridge the two models but need scripting.

## 6. Check the exporter host

- ser2net 4.6.1 or newer. ser2net 4.6.0 (Ubuntu 24.04) never answers the
  RFC2217 purge request, and pyserial times out on open. Until you upgrade,
  tell users to set `LG_PTY_NO_PURGE=1`. See labgrid issue #1396.
- openocd 0.11 or newer so that USB path selection works with several
  probes on one host.
- udev rules that give the exporter user access to the probes
  (`plugdev` group or the vendor rules).
- Disable ModemManager probing of the USB serial ports, or blacklist the
  probe VID:PID. It sends AT commands into the board console.

## 7. Test the place yourself

Before handing a place to users, do the full loop once:

```sh
export LG_COORDINATOR=...; export ZEPHYR_LABGRID_ENV=/shared/labgrid-stm32f7.yaml
labgrid-client -p stm32f746g-disco-1 acquire
west build -b stm32f746g_disco samples/hello_world
west flash -r labgrid -- --dev-id=stm32f746g-disco-1
labgrid-pty -p stm32f746g-disco-1          # expect "Hello World!" after a reset
labgrid-client -p stm32f746g-disco-1 release
```

Then run one Twister suite with the hardware map entry. `samples/hello_world`
checks the console path, `samples/subsys/testsuite/pytest/shell` checks that
writing into the console works too.

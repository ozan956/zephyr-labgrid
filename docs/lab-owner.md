# For lab owners

You run a labgrid coordinator and exporters. Zephyr users want to flash and
run Twister on your boards. This page explains what to prepare for them.

In short, give every Zephyr board a place with a probe resource and
a serial resource, write one labgrid environment file per board family with
a flash driver, put the files in a directory your users can read, and tag
each place with `zephyr_platform` and `zephyr_env`. Users then need only
the coordinator address, the place name and that directory.

To try all of this on one machine first, see [quickstart.md](quickstart.md).

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
device, so use the same match plus the device type.

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
    zephyr_env=stm32f7/labgrid.yaml
```

labgrid itself ignores these tags. The zephyr-labgrid tools read them.

| Tag | Used by | Meaning |
|---|---|---|
| `zephyr_platform` | `labgrid-twister-hwmap` (required) | full Zephyr board target, with the SoC qualifier |
| `zephyr_env` | runner, `labgrid-pty`, check, hwmap | environment file of the place, a relative path is resolved against the user's `ZEPHYR_LABGRID_ENV_DIR` |
| `zephyr_fixtures` | hwmap | comma separated Twister fixtures (loopback wires, sensors) |
| `zephyr_flash_before` | hwmap | `true` when the console port is also the flash port (step 3) |
| `zephyr_pty_args` | hwmap | comma separated extra `labgrid-pty` arguments, e.g. `--reset-rts` |
| `zephyr_flash_timeout` | hwmap | seconds, default 120 |

With `zephyr_env` set, `west flash -r labgrid -- --dev-id=PLACE` finds the
environment file by itself.

### Share the environment files

Put the environment files, and the flash scripts they reference, in one
directory tree and give users read access, for example as a git repository they clone, an
NFS share, or a copy in the CI image. Users point `ZEPHYR_LABGRID_ENV_DIR`
at it. Relative `zephyr_env` tags keep the places independent of where each
user has the directory.

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

The flash driver is either a driver that implements labgrid's
`BootstrapProtocol` or a `FlashScriptDriver`. Options today.

| Driver | Tool on the exporter | Notes |
|---|---|---|
| `OpenOCDDriver` | openocd >= 0.11 | Works for ST-Link, CMSIS-DAP, J-Link with OpenOCD support. Uses the USB path, so several probes on one exporter are fine. Tested. |
| `FlashScriptDriver` | anything | Runs your script on the exporter. Use it for pyocd, dfu-util, nrfutil, esptool, STM32CubeProgrammer, J-Link Commander and other vendor tools. Tested with STM32CubeProgrammer and esptool, see below. |

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
lines drive boot mode and reset. Three things follow.

- Export the tty twice, as `USBSerialPort` for the console and as
  `USBFlashableDevice` matched on `SUBSYSTEM: tty`, so the flash script
  gets the device node as `{device.devnode}`.
- The console must be closed while flashing. Tag the place with
  `zephyr_flash_before=true`. Twister then flashes first and opens the
  console afterwards.
- After the console is opened the board has already booted, so the banner
  would be lost. Tag the place with `zephyr_pty_args=--reset-rts`.
  `labgrid-pty` then pulses RTS over RFC2217 right after connecting and the
  board boots again into the open console.

The image is a raw `.bin`, so the script also needs the flash offset. The
runner fills `{address}` from the build, `CONFIG_FLASH_BASE_ADDRESS` plus
`CONFIG_FLASH_LOAD_OFFSET` where those exist, otherwise the devicetree
partition Zephyr's own esp32 runner uses. See
`examples/esp32_devkitc/labgrid-esp32.yaml` and `esptool-flash.sh`.

labgrid runs the script over ssh with a small PATH. Install esptool where
the script can find it, on `PATH`, in `~/.local/bin`, or as a module of the
system `python3`.

## 4. Hand out hardware map entries

Each place needs one entry. `labgrid-twister-hwmap` writes them from the
tags of step 2.

```sh
labgrid-twister-hwmap -x lab-coordinator:20408 --env-dir /shared/labgrid-envs -o hwmap.yaml
```

It reads the tags from the table in step 2 and skips places without
`zephyr_platform`. `--env FILE` is the fallback for places without a
`zephyr_env` tag, `--force-env FILE` overrides the tag for every place.
With `--acquire` the runner and `labgrid-pty` get `--acquire` and lock the
place per test (see step 5). With `--hooks DIR` it instead writes one
acquire and one release script per place and references them as
`pre_script` and `post_script`. Places that are acquired by someone get a
`notes` line. `--wait-console SECONDS` (default 30) is added to the runner
for places that are flashed while the console is open, so the flash waits
until `labgrid-pty` has the console.

For a single board users do not need a map, see "Run Twister without a
hardware map" in [zephyr-developer.md](zephyr-developer.md). Maps pay off
for several boards and CI. `--env-dir` defaults to `$ZEPHYR_LABGRID_ENV_DIR`.

The result looks like this.

```yaml
- connected: true
  id: stm32f746g-disco-1
  platform: stm32f746g_disco/stm32f746xx
  product: labgrid
  runner: labgrid
  runner_params:
    - --dev-id=stm32f746g-disco-1
    - --env=/shared/labgrid-stm32f7.yaml
    - --wait-console=30
  serial_pty: "labgrid-pty,-p,stm32f746g-disco-1,-e,/shared/labgrid-stm32f7.yaml"
  flash_timeout: 120
  fixtures: []
```

Things to keep in mind about the entries.

- `id` must be set. Twister ignores `runner_params` when it is empty.
- `flash_timeout` counts the whole `west flash` call including the file copy
  to the exporter. 120 s is a safe start.
- Twister passes no arguments and no extra environment to `pre_script`,
  `post_script` and `post_flash_script`. If you want them to acquire and
  release the place, write one tiny script per place or read the place name
  from a file next to the script.
- `fixtures` describe extra hardware (loopback wires, sensors). They map
  well to labgrid tags, so add them when you generate the map.

## 5. Decide who owns the lock

labgrid and Twister both have locks and do not know about each other.

- Twister locks a DUT inside one Twister run. It protects against its own
  parallel workers only.
- labgrid locks a place for one user across the whole lab.

Three models that work.

1. **Users acquire by hand.** The developer runs `labgrid-client acquire`
   before Twister and `release` after. Good for interactive use.
2. **CI user holds the places.** A CI account acquires all Zephyr places
   once, and Twister runs under that account. Other users see the places as
   busy. Good for a dedicated test farm.
3. **The tools lock per test.** Generate the map with
   `labgrid-twister-hwmap --acquire`. `west flash` and `labgrid-pty` then
   acquire the place when they start and release it when the last of them
   exits. The tools on one host coordinate through a small lock directory
   (`$TMPDIR/zephyr-labgrid-<uid>/`), so the flash does not release the
   place while the console is still open. A place that a user acquired by
   hand is never released by the tools. Between two tests the place is free
   for a moment, so another user can take it, and Twister then reports a flash
   error for that test.

Mixing the first two on the same places leads to `Flash error` or `Serial
Device Error` in Twister when the place is taken. Reservations
(`labgrid-client reserve`) can bridge the models but need scripting.

## 6. Check the exporter host

- ser2net 4.6.1 or newer. ser2net 4.6.0 (Ubuntu 24.04) never answers the
  RFC2217 purge request, and plain pyserial times out on open. `labgrid-pty`
  detects this and continues without purge, at the cost of a one second
  probe per host and day, and `LG_PTY_NO_PURGE=1` skips the probe. See labgrid
  issue #1396.
- openocd 0.11 or newer so that USB path selection works with several
  probes on one host.
- udev rules that give the exporter user access to the probes
  (`plugdev` group or the vendor rules).
- Disable ModemManager probing of the USB serial ports, or blacklist the
  probe vendor and product ID. It sends AT commands into the board console.

## 7. Test the place yourself

Before handing a place to users, do the full loop once.

```sh
export LG_COORDINATOR=... ZEPHYR_LABGRID_ENV_DIR=/shared/labgrid-envs
labgrid-client -p stm32f746g-disco-1 acquire
labgrid-twister-check -p stm32f746g-disco-1 --tool openocd   # every line ok
west build -b stm32f746g_disco samples/hello_world
west flash -r labgrid -- --dev-id=stm32f746g-disco-1
labgrid-pty -p stm32f746g-disco-1 &        # console
west reset -r labgrid -- --dev-id=stm32f746g-disco-1   # expect "Hello World!"
kill %1
labgrid-client -p stm32f746g-disco-1 release
```

Then run one Twister suite, with or without the hardware map entry. `samples/hello_world`
checks the console path, `samples/subsys/testsuite/pytest/shell` checks that
writing into the console works too.

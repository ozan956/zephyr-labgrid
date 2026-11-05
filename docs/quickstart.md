# One board on your desk

This page builds a complete labgrid lab on one Linux machine with one
board, so you can try the module before you have a real lab. The same
steps, split over two machines, give you a remote lab.

The example is an STM32F746G-DISCO with its on-board ST-Link. For other
boards, change the exporter entry and the environment file (see
[lab-owner.md](lab-owner.md)).

## 1. Install

You need a Zephyr workspace that builds `samples/hello_world` for your
board, and these tools on the same machine.

- `openocd` 0.11 or newer and `ser2net` (4.6.1 or newer if you can, see
  [lab-owner.md](lab-owner.md#6-check-the-exporter-host))
- ssh to `localhost` without a password prompt. labgrid reaches exported
  resources over ssh, also when the exporter is on the same machine.

Install the Python packages in the environment that runs west.

```sh
pip install "labgrid @ git+https://github.com/labgrid-project/labgrid.git"
git clone https://github.com/ozan956/zephyr-labgrid.git
pip install ./zephyr-labgrid
export ZEPHYR_EXTRA_MODULES=$PWD/zephyr-labgrid
```

## 2. Describe the board for the exporter

Find the serial number of the probe.

```sh
udevadm info -q property -n /dev/ttyACM0 | grep ID_SERIAL_SHORT
```

Write `exporter.yaml`. The ST-Link provides both the debug probe and the
console UART, so match both on the same serial number.

```yaml
stm32f746g-disco:
  USBDebugger:
    match:
      ID_SERIAL_SHORT: '066CFF505356867767051752'
  USBSerialPort:
    match:
      ID_SERIAL_SHORT: '066CFF505356867767051752'
      ID_USB_INTERFACE_NUM: '02'
    speed: 115200
```

## 3. Start the coordinator and the exporter

Run them in their own terminals, or in the background. The coordinator
keeps its places in `places.yaml` in its working directory, so start it
from the same directory every time.

```sh
labgrid-coordinator -l 127.0.0.1:20408
labgrid-exporter -c 127.0.0.1:20408 -n lab --hostname localhost exporter.yaml
```

## 4. Create the place

```sh
export LG_COORDINATOR=127.0.0.1:20408
labgrid-client -p stm32f746g-disco create
labgrid-client -p stm32f746g-disco add-match "lab/stm32f746g-disco/*"
labgrid-client -p stm32f746g-disco set-tags \
    zephyr_platform=stm32f746g_disco/stm32f746xx \
    zephyr_env=stm32f746g_disco/labgrid.yaml
```

`zephyr_env` names the labgrid environment file for the board, relative to
`ZEPHYR_LABGRID_ENV_DIR`. The module ships one for this board in
`examples/`.

```sh
export ZEPHYR_LABGRID_ENV_DIR=$PWD/zephyr-labgrid/examples
```

## 5. Check, flash, test

```sh
labgrid-twister-check -p stm32f746g-disco
```

This prints one line per check. A warning that the place is not acquired
is fine because the commands below use `--acquire`. Fix any `FAIL` lines first.

```sh
west build -b stm32f746g_disco samples/hello_world
west flash -r labgrid -- --dev-id=stm32f746g-disco --acquire
```

Watch the console in a second terminal and reset the board.

```sh
labgrid-pty -p stm32f746g-disco --acquire       # Ctrl-C to stop
west reset -r labgrid -- --dev-id=stm32f746g-disco --acquire
```

You should see `Hello World! stm32f746g_disco/stm32f746xx`.

Run Twister on the board.

```sh
./scripts/twister -p stm32f746g_disco/stm32f746xx --device-testing \
    --device-serial-pty "labgrid-pty,-p,stm32f746g-disco,--acquire" \
    --west-runner labgrid \
    --west-flash="--dev-id=stm32f746g-disco,--acquire,--wait-console=30" \
    -T samples/hello_world -T samples/subsys/testsuite/pytest/shell
```

## Next

- Move the exporter to the machine the boards are plugged into and point
  `LG_COORDINATOR` and `-c` at the coordinator host. Nothing else changes.
- To add more boards, see [lab-owner.md](lab-owner.md).
- For day-to-day use, see [zephyr-developer.md](zephyr-developer.md).

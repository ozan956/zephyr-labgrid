# zephyr-labgrid

Flash, reset and test Zephyr on boards in a [labgrid](https://github.com/labgrid-project/labgrid)
lab as if they were on your desk. `west flash` and Twister work unchanged.
The module adds a `labgrid` west runner and a `labgrid-pty` console bridge.
The flash tool (OpenOCD, esptool, STM32CubeProgrammer, ...) runs on the
exporter next to the board.

**This is an experimental release (0.1).** Tested with Zephyr 4.5 and labgrid master
on an STM32F746G-DISCO (OpenOCD and STM32CubeProgrammer) and an
ESP32-DevKitC (esptool), with Twister's console, ztest and pytest harnesses.
Feedback and reports from other labs and boards are very welcome.

## Requirements

- Linux or macOS (Twister's `--device-serial-pty` does not exist on Windows)
- A Zephyr workspace (tested with Zephyr 4.5)
- **labgrid master**, because no labgrid release has everything this module uses yet
- A labgrid coordinator and exporter with your boards. Without a lab, start
  with [One board on your desk](https://ozan956.github.io/zephyr-labgrid/quickstart/).

## Install

```sh
git clone https://github.com/ozan956/zephyr-labgrid.git

# in the Python environment that runs west and twister
pip install "labgrid @ git+https://github.com/labgrid-project/labgrid.git"
pip install ./zephyr-labgrid

# Zephyr loads the runner from the checkout, so add it to west.yml (see docs) or
export ZEPHYR_EXTRA_MODULES=$PWD/zephyr-labgrid
```

## Use it

Your lab owner tells you the coordinator address and the place name. The
place carries a `zephyr_env` tag that points to the labgrid environment
file for the board, and `ZEPHYR_LABGRID_ENV_DIR` is the directory those files
live in.

```sh
export LG_COORDINATOR=lab-coordinator:20408
export ZEPHYR_LABGRID_ENV_DIR=/shared/labgrid-envs
labgrid-twister-check -p stm32f746g-disco          # finds setup problems

# flash and reset
west build -b stm32f746g_disco samples/hello_world
west flash -r labgrid -- --dev-id=stm32f746g-disco --acquire
west reset -r labgrid -- --dev-id=stm32f746g-disco --acquire

# Twister, like --device-serial for a local board; no hardware map needed
./scripts/twister -p stm32f746g_disco/stm32f746xx --device-testing \
    --device-serial-pty "labgrid-pty,-p,stm32f746g-disco,--acquire" \
    --west-runner labgrid \
    --west-flash="--dev-id=stm32f746g-disco,--acquire,--wait-console=30" \
    -T samples/hello_world
```

To make plain `west flash` use the lab, build with
`-- -DBOARD_FLASH_RUNNER=labgrid '-DBOARD_RUNNER_ARGS_labgrid=--dev-id=stm32f746g-disco;--acquire'`.
For several boards and CI, generate a Twister hardware map with
`labgrid-twister-hwmap`. The details are in [For Zephyr developers](https://ozan956.github.io/zephyr-labgrid/flash-and-test/).

## What works and what does not

| | |
|---|---|
| `west flash` (`--file`, `--reset`, `--dry-run`, sysbuild) | yes |
| `west reset` | yes (ResetProtocol, PowerProtocol or OpenOCD) |
| `west debug`, `debugserver`, `attach`, `rtt` | not yet, needs OpenOCD gdb server support in labgrid, planned |
| `--erase` | no |
| Flash drivers | `OpenOCDDriver`, other `BootstrapProtocol` drivers, any tool through `FlashScriptDriver` (pyocd, dfu-util, nrfutil, esptool, J-Link, ...) |
| Twister console, ztest, gtest, pytest and shell harnesses | yes |
| Twister with or without a hardware map, parallel boards, fixtures, `--flash-before`, `--retry-failed` | yes |
| pytest `mcumgr` fixture | no, it needs a real serial port and the console is a pty |
| Boards with several console UARTs, Twister `required_devices` | no, one console per place |
| Waiting for a busy place | no, a test fails when someone else holds the place |
| Sysbuild on hardware | the place lock is held across images (unit tested), not yet tried on a board |

## Documentation

The documentation is published at https://ozan956.github.io/zephyr-labgrid/. Build it locally with
`pip install -r docs/requirements.txt` and `make -C docs dirhtml`.

- [One board on your desk](https://ozan956.github.io/zephyr-labgrid/quickstart/) gives you a complete lab on one machine to try the module
- [For Zephyr developers](https://ozan956.github.io/zephyr-labgrid/flash-and-test/) explains how to flash, reset and run Twister on lab boards
- [For lab owners](https://ozan956.github.io/zephyr-labgrid/prepare-a-lab/) explains how to prepare places, environment files and tags
- [Best practices](https://ozan956.github.io/zephyr-labgrid/best-practices/) lists what to watch out for
- [Design notes](https://ozan956.github.io/zephyr-labgrid/design/) describe how the pieces work inside, for contributors

## License

Apache-2.0

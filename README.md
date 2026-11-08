# zephyr-labgrid

Flash, reset and test Zephyr on boards in a [labgrid](https://github.com/labgrid-project/labgrid)
lab as if they were on your desk. `west flash` and Twister work unchanged.
The module adds a `labgrid` west runner and a `labgrid-pty` console bridge.
The flash tool (OpenOCD, esptool, STM32CubeProgrammer, ...) runs on the
exporter next to the board.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/pieces-dark.svg">
  <img alt="The runner and labgrid-pty on the developer host reach the flash tool and ser2net on the exporter host. Both hosts keep a session with the labgrid coordinator." src="docs/images/pieces-light.svg">
</picture>

**This is an experimental release (0.1).** Tested with Zephyr 4.5 and labgrid master
on an STM32F746G-DISCO (OpenOCD and STM32CubeProgrammer), an
ESP32-DevKitC (esptool) and an Alif Ensemble E8 DevKit (J-Link), with
Twister's console, ztest and pytest harnesses.
Feedback and reports from other labs and boards are very welcome.

## Requirements

- Linux or macOS (Twister's `--device-serial-pty` does not exist on Windows)
- Zephyr 4.4 or newer (tested with 4.5). Zephyr 3.7 and 4.0 can not load
  runners from modules and reject the module for the whole workspace, 4.1 to
  4.3 lack runner features it uses.
- Python 3.11 or newer
- **labgrid master**, because no labgrid release has everything this module uses yet
- A labgrid coordinator and exporter with your boards. Without a lab, start
  with [One board on your desk](https://ozan956.github.io/zephyr-labgrid/quickstart/).

## Install

```sh
git clone https://github.com/ozan956/zephyr-labgrid.git

# in the Python environment that runs west and twister
pip install "labgrid @ git+https://github.com/labgrid-project/labgrid.git"
pip install -e ./zephyr-labgrid

# Zephyr loads the runner from the checkout, so add it to west.yml (see docs) or
export ZEPHYR_EXTRA_MODULES=$PWD/zephyr-labgrid
```

## Use it

Your daily commands stay almost the same as with a board on your desk.

| Task | Board on your desk | Board in the lab |
|---|---|---|
| Get the board | plug in the USB cable | `labgrid-client -p PLACE acquire`, and `release` when you are done |
| Flash | `west flash` | `west flash -r labgrid` |
| Reset | `west reset` | `west reset -r labgrid` |
| Console | `minicom -D /dev/ttyACM0` | `labgrid-pty` |
| Twister on your board | `twister -p BOARD --device-testing --device-serial /dev/ttyACM0` | `twister -p BOARD --device-testing --device-serial-pty labgrid-pty --west-runner labgrid` |
| Twister on several boards, write the map once | `twister --generate-hardware-map map.yml` | `labgrid-twister-hwmap -o map.yml` |
| Twister on several boards, run | `twister --device-testing --hardware-map map.yml` | the same |

No command needs a place name. The runner and `labgrid-pty` use the place
you hold for the board. With a hardware map, each test takes a free place
and gives it back, and waits when someone else has it. Your lab owner tells
you the coordinator address and the directory with the labgrid environment
files.

```sh
export LG_COORDINATOR=lab-coordinator:20408
export ZEPHYR_LABGRID_ENV_DIR=/shared/labgrid-envs
labgrid-twister-check -p stm32f746g-disco          # finds setup problems
```

To make plain `west flash` use the lab, build with
`-- -DBOARD_FLASH_RUNNER=labgrid`. The details are in
[For Zephyr developers](https://ozan956.github.io/zephyr-labgrid/flash-and-test/).

## What works and what does not

| | |
|---|---|
| `west flash` (`--file`, `--dry-run`, sysbuild) | yes |
| `west reset` | yes (ResetProtocol, a reset script, PowerProtocol or OpenOCD) |
| `west debug`, `debugserver`, `attach`, `rtt` | not yet, needs OpenOCD gdb server support in labgrid, planned |
| `--erase` | no |
| Flash drivers | `OpenOCDDriver`, other `BootstrapProtocol` drivers, any tool through `FlashScriptDriver` (pyocd, dfu-util, nrfutil, esptool, J-Link, ...) |
| Twister console, ztest, gtest, pytest and shell harnesses | yes |
| Twister with or without a hardware map, parallel boards, fixtures, `--flash-before`, `--retry-failed` | yes |
| pytest `mcumgr` fixture | no, it needs a real serial port and the console is a pty |
| Boards with several console UARTs, Twister `required_devices` | no, one console per place |
| Waiting for a busy place | yes, with hardware maps (300 s by default) |
| Sysbuild on hardware | all images go to the same place (unit tested), not yet tried on a board |

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

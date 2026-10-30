# zephyr-labgrid

zephyr-labgrid is an experimental Zephyr module that lets `west flash` and
Twister use boards connected to a [labgrid](https://github.com/labgrid-project/labgrid)
exporter. It adds a `labgrid` west runner and a `labgrid-pty` console bridge.
No changes to Zephyr or labgrid are needed.

Status: experimental. Tested with Zephyr main (October 2026) and labgrid
master on an STM32F746G-DISCO (on-board ST-Link, flashed with OpenOCD and
with STM32CubeProgrammer) and on an ESP32-DevKitC (USB-UART bridge, flashed
with esptool), using Twister's console, ztest and pytest harnesses.

Documentation: [docs/](docs/README.md)

- [For Zephyr developers](docs/zephyr-developer.md)
- [For lab owners](docs/lab-owner.md)
- [Best practices](docs/best-practices.md)

Parts:

- `scripts/labgrid_runner.py`: `west flash -r labgrid -- --dev-id <place> [--env labgrid.yaml]`.
  Resolves a labgrid environment, picks the place and asks its BootstrapProtocol
  driver (OpenOCD, pyOCD, FlashScript, ...) to load the image. Flashing runs on
  the exporter side.
- `scripts/labgrid-pty`: console bridge for Twister's `serial_pty` /
  pytest-twister-harness `--device-serial-pty`.
- `scripts/labgrid-twister-hwmap`: writes a Twister hardware map from the
  `zephyr_*` tags of your labgrid places.
- `scripts/labgrid-twister-check`: checks a setup (packages, PATH, variables,
  coordinator, place, environment file, exporter tools, console, hardware
  map) and prints one line per check.
- `zephyr_labgrid/`: the Python package behind the three tools. `pip install`
  of this directory gives you the same commands without touching `PATH`.
- `tests/`: unit tests (`pytest`; the runner tests need `ZEPHYR_BASE`).
- `CMakeLists.txt`: registers the `labgrid` runner in every build's
  `runners.yaml` (module CMake runs before `cmake/flash`).
- `examples/stm32f746g_disco/`: labgrid environments (OpenOCD and
  STM32CubeProgrammer), flash script, Twister hardware map.
- `examples/esp32_devkitc/`: labgrid environment and esptool flash script
  for a board whose console port is also the flash port.

Usage:

```sh
export ZEPHYR_EXTRA_MODULES=/path/to/zephyr-labgrid
export LG_COORDINATOR=host:20408
export ZEPHYR_LABGRID_ENV=/path/to/zephyr-labgrid/examples/stm32f746g_disco/labgrid.yaml  # not LG_ENV, see below
export PATH=/path/to/zephyr-labgrid/scripts:$PATH   # or: pip install /path/to/zephyr-labgrid

labgrid-twister-check -p stm32f746g-disco           # optional, finds setup problems

west build -b stm32f746g_disco samples/hello_world
west flash -r labgrid -- --dev-id=stm32f746g-disco

twister -T tests/kernel/common --device-testing \
        --hardware-map examples/stm32f746g_disco/hwmap.yaml
```

The place must be acquired by you (`labgrid-client -p PLACE acquire`), or
pass `--acquire` to the runner and to `labgrid-pty` (hardware maps from
`labgrid-twister-hwmap --acquire` do that) to lock it per test.

ser2net 4.6.0 (Ubuntu 24.04) never answers the RFC2217 purge request
(labgrid issue #1396). `labgrid-pty` detects this and continues without
purge; set `LG_PTY_NO_PURGE=1` to skip the one second probe.

Why `ZEPHYR_LABGRID_ENV` and not `LG_ENV`: labgrid ships a pytest plugin that
activates itself whenever `LG_ENV` is set. Twister's `harness: pytest` suites
run pytest in a subprocess that inherits the environment, so `LG_ENV` would
make labgrid's plugin load the environment file there too (and fail on the
`$LG_PLACE` template). The runner and the bridge accept `--env` as well.

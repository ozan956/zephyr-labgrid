# zephyr-labgrid

Experimental Zephyr module that lets `west flash` and Twister use a board
behind a [labgrid](https://github.com/labgrid-project/labgrid) exporter.

Parts:

- `scripts/labgrid_runner.py`: `west flash -r labgrid -- --dev-id <place> [--env labgrid.yaml]`.
  Resolves a labgrid environment, picks the place and asks its BootstrapProtocol
  driver (OpenOCD, pyOCD, FlashScript, ...) to load the image. Flashing runs on
  the exporter side.
- `scripts/labgrid-pty`: console bridge for Twister's `serial_pty` /
  pytest-twister-harness `--device-serial-pty`.
- `CMakeLists.txt`: registers the `labgrid` runner in every build's
  `runners.yaml` (module CMake runs before `cmake/flash`).
- `examples/stm32f746g_disco/`: labgrid environment, Twister hardware map.

Usage:

```sh
export ZEPHYR_EXTRA_MODULES=/path/to/zephyr-labgrid
export LG_COORDINATOR=host:20408
export ZEPHYR_LABGRID_ENV=/path/to/zephyr-labgrid/examples/stm32f746g_disco/labgrid.yaml  # not LG_ENV, see below
export PATH=/path/to/zephyr-labgrid/scripts:$PATH

west build -b stm32f746g_disco samples/hello_world
west flash -r labgrid -- --dev-id=stm32f746g-disco

twister -T tests/kernel/common --device-testing \
        --hardware-map examples/stm32f746g_disco/hwmap.yaml
```

Known workaround: `LG_PTY_NO_PURGE=1` disables the RFC2217 purge request in
`labgrid-pty` for ser2net 4.6.0 (Ubuntu 24.04), see labgrid issue #1396.

Why `ZEPHYR_LABGRID_ENV` and not `LG_ENV`: labgrid ships a pytest plugin that
activates itself whenever `LG_ENV` is set. Twister's `harness: pytest` suites
run pytest in a subprocess that inherits the environment, so `LG_ENV` would
make labgrid's plugin load the environment file there too (and fail on the
`$LG_PLACE` template). The runner and the bridge accept `--env` as well.

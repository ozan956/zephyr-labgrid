# Best practices

Things we learned while running Twister through labgrid. Most of them come
from reading the Twister and pytest-twister-harness sources and from one
STM32F746G-DISCO on a local exporter.

## Keep the environment variables apart

- Use `ZEPHYR_LABGRID_ENV`, not `LG_ENV`, for the environment file. labgrid
  ships a pytest plugin that turns itself on when `LG_ENV` is set. Twister's
  pytest harness runs pytest in a subprocess that inherits your environment,
  so `LG_ENV` would load the labgrid plugin there and fail on the
  `$LG_PLACE` template.
- Even better, pass `--env` in `runner_params` and `-e` in `serial_pty`.
  Then the hardware map is self-contained and works from any shell.
- `LG_COORDINATOR` is fine to export. Nothing else reacts to it.

## Hardware map rules

- Always set `id`. Twister's DeviceHandler drops `runner_params` and
  `base_params` when the DUT has neither `id` nor `probe_id`. The pytest
  harness does not have this gate, so the two paths behave differently
  without an id.
- Use `serial_pty`, not `serial`. A real `serial:` device would need the
  port on the developer's machine. The pty bridge keeps the serial on the
  exporter.
- One environment file per board family, one hardware map entry per place.
  Generate the map from labgrid tags instead of editing it by hand.
- Give `flash_timeout` room. It includes copying the image to the exporter
  and starting the flash tool there.

## Locks and parallel runs

- Decide up front who holds the labgrid lock (the user or a CI account) and
  write it down. Most "Flash error" reports in Twister are a place that
  belongs to someone else.
- Twister forks one worker per DUT. Every worker runs its own `west flash`
  and its own `labgrid-pty`, so every DUT gets its own labgrid connections.
  Do not share one labgrid Target object across DUTs in custom scripts.
- Twister's `pre_script` and `post_script` get no arguments and no extra
  environment. If you use them for acquire and release, keep them tiny and
  per place. Their exit codes are only logged, so a failed acquire shows up
  later as a flash or serial error. Check the Twister log, not the script.

## Console bridge

- `labgrid-pty` exits when its stdin closes. When you test it by hand,
  keep stdin open (for example `sleep 60 | labgrid-pty ...`) or run it in a
  terminal. Twister keeps the pty open for the whole test.
- Expect the first boot banner twice with OpenOCD: `reset halt` and `reset
  run` each start the board. Harness regexes that count lines should allow
  for that.
- Ask for ser2net 4.6.1 or newer on exporters. `LG_PTY_NO_PURGE=1` is a
  workaround, not a fix.

## Flashing

- Prefer the hex file. OpenOCD and most tools take the address from it.
  For raw binaries, set the flash address in `load_commands` or use
  `--file` with the right tool.
- Select the right place only with `--dev-id`. Never put the place name
  into the environment file.
- When a board needs a power cycle before it can be flashed (stuck in a low
  power state, locked debug port), add a PowerProtocol driver to the place
  and use `--power-cycle` in `runner_params`.
- The runner releases the flash driver (`deactivate`) right after loading,
  so the probe is free again for the next command.

## Toolchain and host tools

- Twister treats compiler and linker warnings as errors. Toolchains outside
  the Zephyr SDK may emit extra warnings (for example `LOAD segment with
  RWX permissions` from newer binutils). Use `-W` or the Zephyr SDK.
- `gperf` must be on the host for any test with `CONFIG_USERSPACE`.
  `tests/kernel/common` and `tests/kernel/sleep` are examples.
- Scenario filters (`-s`) apply to every `-T` directory you pass. Run suites
  separately if you need different filters.

## What this module does not do yet

- Only `flash` is implemented. `west debug` and `west attach` through
  labgrid are not supported.
- No hardware map generator from labgrid tags yet.
- Only `OpenOCDDriver` has been tested as the flash driver.
- Twister's own DUT lock and labgrid's place lock are not connected.

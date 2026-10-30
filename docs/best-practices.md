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
- `--acquire` on the runner and on `labgrid-pty` is the simpler way. Twister
  starts both at the same time for boards that are flashed with the console
  open, so the two tools share one lock: whoever acquires first writes a
  marker in `$TMPDIR/zephyr-labgrid-<uid>/<coordinator>-<place>/`, every
  tool registers its pid there, and the last one to exit releases the
  place. labgrid-client's "already acquired" check runs before the
  resources have arrived, so without this serialisation the second tool
  saw a place with no resources.
- Acquire and release go through the `labgrid-client` command, not the
  client API. The coordinator accepts one session per process, and the
  `RemotePlace` resource already opens one.

## Console bridge

- `labgrid-pty` reads and writes the pyserial object of the SerialDriver
  directly instead of calling `ConsoleProtocol.read(timeout=...)`. Every
  such call sets `serial.timeout`, and pyserial's RFC2217 class then
  renegotiates all port settings with ser2net. At a high poll rate this
  costs round trips and loses bytes; it also made typed shell commands
  disappear on both test boards. Keep this in mind for your own labgrid
  scripts that poll a remote console in a tight loop.
- labgrid drivers are not thread safe. The `@step` decorator keeps a
  global stack and asserts when two threads use a driver at the same time.
  Do not call a driver from a reader thread and a writer thread at once.
- Opening a remote console takes seconds (labgrid session, ssh, RFC2217
  negotiation), and more under build load. Twister assumes the pty is
  ready as soon as the process has started and flashes right away, so the
  boot output was lost in a 1 in 5 case. `labgrid-pty` writes a ready
  marker next to the lock files once the console is open, and
  `west flash -r labgrid -- --wait-console=30` waits for it. The generated
  hardware maps include the option.
- The RFC2217 purge probe: pyserial sends two purge requests in `open()`
  and waits 3 s for each answer. `labgrid-pty` sends the first one with a
  1 s timeout; when it is not answered the host is remembered for a day
  in the lock directory and no more purges are sent. `--purge on` restores
  plain pyserial behaviour, `--purge off` (or `LG_PTY_NO_PURGE=1`) never
  sends one.

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
- With `FlashScriptDriver`, let the script find the probe from
  `{device.path}` on the exporter instead of hard coding serial numbers.
  One script then serves every board of the family.
- `FlashScriptDriver.script` is an image key, not a path. Put the script
  into the `images:` section of the environment file.
- Use `{address}` in the script args for raw `.bin` images. The runner
  reads the offset from the build, so one environment file works for
  simple boot and MCUboot layouts.
- When console and flash share one UART (ESP32 with USB-UART), tag the
  place with `zephyr_flash_before=true` and `zephyr_pty_args=--reset-rts`.
  Without the RTS reset the boot banner is printed before the console is
  open and console harness tests fail.
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
- Flash drivers tested so far: `OpenOCDDriver`, `FlashScriptDriver` with
  STM32CubeProgrammer and with esptool.
- Twister's own DUT lock and labgrid's place lock are only connected
  through `--acquire`; the place is free between two tests.

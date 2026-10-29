# For Zephyr developers

You have a Zephyr workspace and want to flash or test on a board that is not
on your desk but on a labgrid exporter somewhere in the lab.

## What you need

- A Zephyr workspace with west (Zephyr 4.x main was used for testing).
- The `labgrid` Python package in the same Python environment that runs
  `west` and `twister`:
  ```sh
  pip install labgrid
  ```
- Network access to the labgrid coordinator. Your lab owner gives you:
  - the coordinator address, for example `lab-coordinator:20408`
  - the name of your place, for example `stm32f746g-disco-1`
  - a labgrid environment file for the board family, for example
    `labgrid-stm32f7.yaml` (see [lab-owner.md](lab-owner.md))
- This module checked out somewhere, for example next to your workspace.

## Enable the module

Either add it to your `west.yml`:

```yaml
manifest:
  projects:
    - name: zephyr-labgrid
      url: https://github.com/<user>/zephyr-labgrid
      revision: main
      path: modules/zephyr-labgrid
```

and run `west update`, or point Zephyr at the checkout with an environment
variable, which also works for an existing workspace:

```sh
export ZEPHYR_EXTRA_MODULES=/path/to/zephyr-labgrid
```

Also put the scripts on your `PATH` so Twister can find `labgrid-pty`:

```sh
export PATH=/path/to/zephyr-labgrid/scripts:$PATH
```

## Set the labgrid environment

```sh
export LG_COORDINATOR=lab-coordinator:20408
export ZEPHYR_LABGRID_ENV=/path/to/labgrid-stm32f7.yaml
```

Use `ZEPHYR_LABGRID_ENV`, not `LG_ENV`. `LG_ENV` would also switch on
labgrid's own pytest plugin inside Twister's pytest runs. You can also pass
the file with `--env` on every command instead of using the variable.

Take the place before you use it, and give it back when you are done:

```sh
labgrid-client -p stm32f746g-disco-1 acquire
...
labgrid-client -p stm32f746g-disco-1 release
```

## Flash a build

Build as usual. Because the module is enabled, every build gets a `labgrid`
runner in `build/zephyr/runners.yaml`. It is never the default, so pick it
with `-r`:

```sh
west build -b stm32f746g_disco samples/hello_world
west flash -r labgrid -- --dev-id=stm32f746g-disco-1
```

`--dev-id` is the place name. If `LG_PLACE` is set you can leave it out.

Runner options after `--`:

| Option | Meaning |
|---|---|
| `--dev-id PLACE` | labgrid place name (default `$LG_PLACE`) |
| `--env FILE` | labgrid environment file (default `$ZEPHYR_LABGRID_ENV`, then `$LG_ENV`) |
| `--driver NAME` | labgrid driver name to flash with, when the environment has more than one |
| `--power-cycle` | power cycle the place before flashing (needs a PowerProtocol driver) |
| `--reset` / `--no-reset` | reset after flashing; best effort, see below |
| `--file FILE`, `--file-type` | flash a different file than the build output |
| `--timeout SECONDS` | wait time for labgrid resources |

The runner picks `zephyr.hex` if it exists, then `zephyr.bin`, then
`zephyr.elf`. What the flashing tool accepts depends on the driver in the
environment file. OpenOCD and STM32CubeProgrammer take all three.

Which labgrid driver does the flashing is decided by the environment file:
a `BootstrapProtocol` driver (OpenOCDDriver, DFUDriver, ...) is used when
present, otherwise a `FlashScriptDriver` that runs a vendor tool on the
exporter. You do not need to care unless the file has both; then pick one
with `--driver`.

Reset after flashing is best effort. The runner tries a ResetProtocol
driver, then a PowerProtocol driver. If the place has neither, it relies on
the flasher to reset the board. The example OpenOCD configuration ends with
`reset run`, so this is fine in practice.

## Watch the console

```sh
labgrid-client -p stm32f746g-disco-1 console
```

This needs `microcom` or `telnet` on your machine. `labgrid-pty` is also
usable by hand when you only want to see output:

```sh
labgrid-pty -p stm32f746g-disco-1 | tee console.log
```

Stop it with Ctrl-C.

## Run Twister on the board

Twister needs a hardware map entry for the place. Generate it from the
labgrid tags, if your lab owner has set them:

```sh
labgrid-twister-hwmap -x lab-coordinator:20408 --env-dir /shared/labgrid-envs -o hwmap.yaml
```

Or write it by hand. The minimum is:

```yaml
- connected: true
  id: stm32f746g-disco-1
  platform: stm32f746g_disco/stm32f746xx
  product: labgrid
  runner: labgrid
  runner_params:
    - --dev-id=stm32f746g-disco-1
    - --env=/path/to/labgrid-stm32f7.yaml
  serial_pty: "labgrid-pty,-p,stm32f746g-disco-1,-e,/path/to/labgrid-stm32f7.yaml"
  flash_timeout: 120
```

Keep `id` set. Twister silently drops `runner_params` when `id` is empty.

Then run Twister as you would with a local board:

```sh
./scripts/twister -p stm32f746g_disco/stm32f746xx --device-testing \
    --hardware-map hwmap.yaml -T tests/kernel/common
```

Twister calls `west flash --runner labgrid` and starts `labgrid-pty` for the
console. Console, ztest and pytest harness suites all work this way. The
pytest harness (`harness: pytest`) reads the same hardware map fields, so
nothing extra is needed for it.

## If something goes wrong

- `labgrid runner needs --env or ...`: set `ZEPHYR_LABGRID_ENV` or pass
  `--env`.
- `no BootstrapProtocol driver found`: the environment file has no flash
  driver, or the place has no probe resource. Ask the lab owner.
- `timeout while waiting for option 'purge'` from `labgrid-pty`: the exporter
  runs ser2net 4.6.0 (Ubuntu 24.04), which does not answer the RFC2217 purge
  request. Set `LG_PTY_NO_PURGE=1` as a workaround, or ask for a ser2net
  upgrade. See labgrid issue #1396.
- Twister reports `Serial Device Error`: `labgrid-pty` could not start.
  Check that it is on `PATH` and that the place is acquired by you.
- Twister reports `Device issue (Flash error?)`: run the same `west flash`
  command from the Twister log by hand; the OpenOCD output will tell you
  more.
- Import errors like `cannot import name 'Environment' from 'labgrid'`: your
  current directory contains a folder named `labgrid` (for example a clone of
  the labgrid repository). Run from another directory.

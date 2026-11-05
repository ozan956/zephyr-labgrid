# For Zephyr developers

You have a Zephyr workspace and want to flash, reset or test on a board
that is not on your desk but on a labgrid exporter in the lab.

## What you need

You get these from your lab owner.

- the coordinator address, for example `lab-coordinator:20408`
- the place name of your board, for example `stm32f746g-disco-1`
- the directory with the lab's labgrid environment files, for example
  `/shared/labgrid-envs` (or a single environment file for your board)

Install these on your machine, in the Python environment that runs `west` and `twister`.

```sh
pip install "labgrid @ git+https://github.com/labgrid-project/labgrid.git"
git clone https://github.com/ozan956/zephyr-labgrid.git
pip install ./zephyr-labgrid
```

The module needs labgrid master, because no labgrid release has everything it uses
yet. `pip install` gives you `labgrid-pty`, `labgrid-twister-hwmap` and
`labgrid-twister-check`.

## Enable the module

Add it to your `west.yml` and run `west update`.

```yaml
manifest:
  projects:
    - name: zephyr-labgrid
      url: https://github.com/ozan956/zephyr-labgrid
      revision: main
      path: modules/lib/zephyr-labgrid
```

or point an existing workspace at the checkout.

```sh
export ZEPHYR_EXTRA_MODULES=/path/to/zephyr-labgrid
```

Every build then has a `labgrid` runner in `build/zephyr/runners.yaml`.

## Point it at the lab

```sh
export LG_COORDINATOR=lab-coordinator:20408
export ZEPHYR_LABGRID_ENV_DIR=/shared/labgrid-envs
```

The runner and `labgrid-pty` find the environment file of a place in this
order.

1. `--env FILE` on the command line
2. `$ZEPHYR_LABGRID_ENV`
3. `$LG_ENV` (avoid it, see [best practices](best-practices.md#keep-lg_env-unset))
4. the `zephyr_env` tag of the place, relative to `--env-dir` or
   `$ZEPHYR_LABGRID_ENV_DIR`

With tagged places you only need to know the place name.

## Who holds the place

A labgrid place belongs to one user at a time. Either take it by hand.

```sh
labgrid-client -p stm32f746g-disco-1 acquire
...
labgrid-client -p stm32f746g-disco-1 release
```

or pass `--acquire` to the runner and to `labgrid-pty`. They take the
place while they run and give it back afterwards. A runner and a
`labgrid-pty` running at the same time on your machine share the place,
and a place you acquired by hand is never released by them. Do not start
two Twister runs on the same place from the same user and host at once.
They would share the board instead of waiting for each other.

## Check the setup

```sh
labgrid-twister-check -p stm32f746g-disco-1
```

prints one line per check. It covers Python packages, tools on `PATH`, environment
variables, coordinator, place and tags, environment file, flash tool on the
exporter (`--tool esptool` for script based flashing) and the console. Add
`--hwmap hwmap.yaml` to check a Twister hardware map too. Fix the `FAIL`
lines first.

## Flash and reset

```sh
west build -b stm32f746g_disco samples/hello_world
west flash -r labgrid -- --dev-id=stm32f746g-disco-1 --acquire
west reset -r labgrid -- --dev-id=stm32f746g-disco-1 --acquire
```

`--dev-id` is the place name. If `LG_PLACE` is set you can leave it out.
`--dry-run` prints what would happen without touching the lab.

Runner options after `--`.

| Option | Meaning |
|---|---|
| `--dev-id PLACE` | labgrid place (default `$LG_PLACE`) |
| `--env FILE` | labgrid environment file (see the lookup order above) |
| `--env-dir DIR` | directory for a relative `zephyr_env` tag (default `$ZEPHYR_LABGRID_ENV_DIR`) |
| `--acquire` | acquire the place and release it when west exits |
| `--driver NAME` | labgrid driver to flash with, when the environment has more than one |
| `--power-cycle` | power cycle the place before flashing (needs a PowerProtocol driver) |
| `--reset` / `--no-reset` | reset after flashing |
| `--file FILE`, `--file-type TYPE` | flash another file than the build output |
| `--timeout SECONDS` | time limit for labgrid resources and flash scripts |
| `--wait-console SECONDS` | wait for a `labgrid-pty` on this machine to have the console open before flashing (Twister) |
| `--dry-run` | log what would be done, do nothing |

The runner flashes `zephyr.hex` if it exists, else `zephyr.bin`, else
`zephyr.elf`. The environment file decides how, with a `BootstrapProtocol`
driver such as OpenOCD, or with a `FlashScriptDriver` that runs a vendor
tool on the exporter. Pick one with `--driver` if the file has both.

`west reset` uses a ResetProtocol driver, else a PowerProtocol driver
(power cycle), else OpenOCD (`reset run`). After flashing, `--reset` tries
the same list but does not fail when there is none, since OpenOCD and most flash
tools reset the board themselves.

Sysbuild builds (MCUboot and application, several cores) are flashed one
image after the other in one `west flash` call. With `--acquire` the place
stays acquired from the first image to the last.

For boards flashed over their console UART (ESP32 dev kits), close the console
(`labgrid-pty`, `labgrid-client console`) before `west flash`, or the
flash tool and the console fight over the port.

### Make labgrid the default runner

So that a plain `west flash` (and `west build -t flash`) goes to the lab,
set the runner and its arguments when you build.

```sh
west build -b stm32f746g_disco samples/hello_world -- \
    -DBOARD_FLASH_RUNNER=labgrid \
    '-DBOARD_RUNNER_ARGS_labgrid=--dev-id=stm32f746g-disco-1;--acquire'
west flash
```

## Watch the console

```sh
labgrid-pty -p stm32f746g-disco-1 --acquire     # Ctrl-C to stop
```

`--reset-rts` pulses the RTS line after connecting, which resets ESP32
style boards so you see the boot banner. `labgrid-client -p PLACE console`
works too and needs `microcom` or `telnet`.

`labgrid-pty` exits when its input closes. Run it in a terminal, or keep
the input open (`sleep 60 | labgrid-pty ...`).

## Run Twister without a hardware map

For one board this works like `--device-serial` with a local board.

```sh
./scripts/twister -p stm32f746g_disco/stm32f746xx --device-testing \
    --device-serial-pty "labgrid-pty,-p,stm32f746g-disco-1,--acquire" \
    --west-runner labgrid \
    --west-flash="--dev-id=stm32f746g-disco-1,--acquire,--wait-console=30" \
    -T tests/kernel/common
```

- `--device-serial-pty` starts `labgrid-pty` for the console. Commas
  separate its arguments.
- `--west-runner labgrid` and `--west-flash` make every flash go through
  the place.
- `--wait-console=30` makes the flash wait until the console is open.
  Twister starts both at the same time, and the board would otherwise boot
  before anyone listens.

For a board whose console port is also its flash port (ESP32 with a
USB-UART bridge), add `--flash-before` to Twister, drop `--wait-console`
and add `--reset-rts` to the `labgrid-pty` arguments.

```sh
./scripts/twister -p esp32_devkitc/esp32/procpu --device-testing --flash-before \
    --device-serial-pty "labgrid-pty,-p,esp32-devkitc,--acquire,--reset-rts" \
    --west-runner labgrid --west-flash="--dev-id=esp32-devkitc,--acquire" \
    -T samples/hello_world
```

## Run Twister with a hardware map

For several boards, CI and shared setups, write the places into a Twister
hardware map. If the places are tagged, generate it.

```sh
labgrid-twister-hwmap --acquire -o hwmap.yaml
./scripts/twister --device-testing --hardware-map hwmap.yaml -T tests/kernel/common
```

One entry looks like this.

```yaml
- connected: true
  id: stm32f746g-disco-1
  platform: stm32f746g_disco/stm32f746xx
  product: labgrid
  runner: labgrid
  runner_params:
    - --dev-id=stm32f746g-disco-1
    - --env=/shared/labgrid-envs/stm32f746g_disco/labgrid.yaml
    - --wait-console=30
    - --acquire
  serial_pty: "labgrid-pty,-p,stm32f746g-disco-1,-e,/shared/labgrid-envs/stm32f746g_disco/labgrid.yaml,--acquire"
  flash_timeout: 120
```

Keep `id` set, because Twister drops `runner_params` when it is empty. Twister runs
one worker per entry, so several boards of the same platform are tested in
parallel. The pytest harness (`harness: pytest`) reads the same fields.

## If something goes wrong

- `labgrid runner needs --dev-id or $LG_PLACE`. Pass the place name.
- `place ... has zephyr_env=..., a relative path`. Set
  `ZEPHYR_LABGRID_ENV_DIR`, or pass `--env`.
- `could not acquire place`. Someone else holds it. `labgrid-client places`
  shows who. Twister reports this as a flash or serial error.
- `place ... is not acquired`. Acquire it, or add `--acquire`.
- `no flash driver (BootstrapProtocol or FlashScriptDriver)`. The
  environment file has no flash driver, or the place lacks the probe
  resource. Ask the lab owner.
- `the serial server did not answer the RFC2217 purge request`. The
  exporter runs ser2net 4.6.0, and `labgrid-pty` continues without purge. Set
  `LG_PTY_NO_PURGE=1` to skip the one second probe. See
  [lab-owner.md](lab-owner.md#6-check-the-exporter-host).
- Twister reports `Serial Device Error` when `labgrid-pty` could not start.
  Run the `serial_pty` command from the Twister log by hand.
- Twister reports `Device issue (Flash error?)`. Run the `west flash`
  command from the Twister log by hand, the flash tool output tells more.
- `cannot import name 'Environment' from 'labgrid'`. The current directory
  contains a `labgrid` folder (a labgrid clone). Run from another directory.

#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Flash or reset an ESP32 with esptool. Runs on the labgrid exporter through
# FlashScriptDriver.
#
# usage: esptool-flash.sh <serial-device> <address> <image> [extra esptool args]
#        esptool-flash.sh reset <serial-device>
#   serial-device  e.g. /dev/ttyUSB0 (labgrid: {device.devnode})
#   address        flash offset of the image, e.g. 0x1000 (runner: {address})
#   image          .bin produced by the Zephyr build
#
# Needs esptool >= 5 (dash style commands) on the exporter, same as Zephyr's
# own esp32 runner. Settings follow Zephyr's defaults: dio, 40m, size detect.
set -eu

# labgrid runs this over ssh with a minimal PATH, so also look in the usual
# per-user install locations and fall back to the python module.
cli=$(command -v esptool 2>/dev/null || command -v esptool.py 2>/dev/null || true)
if [ -z "$cli" ]; then
    for c in "$HOME/.local/bin/esptool" "$HOME/.local/bin/esptool.py" \
             /usr/local/bin/esptool /usr/local/bin/esptool.py; do
        if [ -x "$c" ]; then
            cli=$c
            break
        fi
    done
fi
if [ -z "$cli" ] && python3 -c 'import esptool' 2>/dev/null; then
    cli="python3 -m esptool"
fi
if [ -z "$cli" ]; then
    echo "esptool not found on the exporter (PATH, ~/.local/bin, python3 -m esptool)" >&2
    exit 1
fi

if [ "$1" = reset ]; then
    # esptool connects, then resets the board through RTS
    # shellcheck disable=SC2086
    exec $cli --port "$2" --before default-reset --after hard-reset chip-id
fi

port=$1
address=$2
image=$3
shift 3

# shellcheck disable=SC2086
exec $cli --port "$port" --baud "${ESPTOOL_BAUD:-921600}" \
    --before default-reset --after hard-reset \
    write-flash -u --flash-mode dio --flash-freq 40m --flash-size detect \
    "$@" "$address" "$image"

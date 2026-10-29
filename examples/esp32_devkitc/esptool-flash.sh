#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Flash an ESP32 image with esptool. Runs on the labgrid exporter through
# FlashScriptDriver.
#
# usage: esptool-flash.sh <serial-device> <address> <image> [extra esptool args]
#   serial-device  e.g. /dev/ttyUSB0 (labgrid: {device.devnode})
#   address        flash offset of the image, e.g. 0x1000 (runner: {address})
#   image          .bin produced by the Zephyr build
#
# Needs esptool >= 5 (dash style commands) on the exporter, same as Zephyr's
# own esp32 runner. Settings follow Zephyr's defaults: dio, 40m, size detect.
set -eu

port=$1
address=$2
image=$3
shift 3

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

# shellcheck disable=SC2086
exec $cli --port "$port" --baud "${ESPTOOL_BAUD:-921600}" \
    --before default-reset --after hard-reset \
    write-flash -u --flash-mode dio --flash-freq 40m --flash-size detect \
    "$@" "$address" "$image"

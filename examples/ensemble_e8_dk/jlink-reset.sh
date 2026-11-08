#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Reset an Alif Ensemble board through the reset pin of the on-board J-Link:
# the Secure Enclave restarts and boots the cores as after power on. Runs on
# the labgrid exporter as the FlashScriptDriver named "reset", which
# west reset -r labgrid uses.
#
# usage: jlink-reset.sh <usb-path>
#   usb-path  sysfs USB path of the J-Link, e.g. 1-1 (labgrid: {device.path})
set -eu

sn=$(cat "/sys/bus/usb/devices/$1/serial")

jlink=$(command -v JLinkExe 2>/dev/null || true)
if [ -z "$jlink" ]; then
    for d in /opt/SEGGER/JLink "$HOME/opt/SEGGER-JLink"; do
        if [ -x "$d/JLinkExe" ]; then
            jlink="$d/JLinkExe"
            break
        fi
    done
fi
if [ -z "$jlink" ]; then
    echo "JLinkExe not found on the exporter" >&2
    exit 1
fi

script=$(mktemp)
trap 'rm -f "$script"' EXIT
printf 'r0\nsleep 100\nr1\nq\n' > "$script"

# no -device and no autoconnect: the pin reset needs no core
exec "$jlink" -NoGui 1 -ExitOnError 1 -USB "$sn" -autoconnect 0 -CommandFile "$script"

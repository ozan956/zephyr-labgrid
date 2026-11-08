#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Write an image into the MRAM of an Alif Ensemble core with the on-board
# J-Link, then pin reset the board so that the Secure Enclave boots it.
# Runs on the labgrid exporter through FlashScriptDriver.
#
# usage: jlink-flash.sh <usb-path> <address> <image> <device>
#   usb-path  sysfs USB path of the J-Link, e.g. 1-1 (labgrid: {device.path})
#   address   MRAM address of the image (labgrid runner: {address})
#   image     zephyr.bin
#   device    J-Link device name, e.g. AE822FA0E5597LS0_M55_HP
#
# The board needs an ATOC that boots the core from this address, written
# once with SETOOLS (see zephyr-hp.json next to this script).
set -eu

usb_path=$1
address=$2
image=$3
device=$4

sn=$(cat "/sys/bus/usb/devices/$usb_path/serial")

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
# r0/r1 pull the reset pin: the Secure Enclave restarts and boots the new
# image, as after power on. A core reset alone would not run it.
cat > "$script" <<EOF
loadbin $image $address
verifybin $image $address
r0
sleep 100
r1
q
EOF

exec "$jlink" -NoGui 1 -ExitOnError 1 -USB "$sn" -device "$device" -if SWD \
    -speed 4000 -autoconnect 1 -CommandFile "$script"

#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Flash or reset an Alif Ensemble board with the on-board J-Link. Runs on
# the labgrid exporter through FlashScriptDriver.
#
# usage: jlink.sh flash <usb-path> <address> <image> <device>
#        jlink.sh reset <usb-path>
#   usb-path  sysfs USB path of the J-Link (labgrid: {device.path})
#   address   MRAM address of the image (labgrid runner: {address})
#   image     zephyr.bin
#   device    J-Link device name, e.g. AE822FA0E5597LS0_M55_HP
#
# Both end with a pull on the reset pin: the Secure Enclave restarts and
# boots the image, a core reset would not run it. Flashing needs an ATOC
# that boots the core from the address, see zephyr-hp.json.
set -eu

mode=$1
sn=$(cat "/sys/bus/usb/devices/$2/serial")

jlink=$(command -v JLinkExe 2>/dev/null || true)
for d in /opt/SEGGER/JLink "$HOME/opt/SEGGER-JLink"; do
    [ -n "$jlink" ] && break
    [ -x "$d/JLinkExe" ] && jlink="$d/JLinkExe"
done
if [ -z "$jlink" ]; then
    echo "JLinkExe not found on the exporter" >&2
    exit 1
fi

script=$(mktemp)
trap 'rm -f "$script"' EXIT
case "$mode" in
    flash)
        printf 'loadbin %s %s\nverifybin %s %s\n' "$4" "$3" "$4" "$3" > "$script"
        connect="-device $5 -if SWD -speed 4000 -autoconnect 1"
        ;;
    reset)
        connect="-autoconnect 0"    # the reset pin needs no core
        ;;
    *)
        echo "usage: $0 flash|reset ..." >&2
        exit 2
        ;;
esac
printf 'r0\nsleep 100\nr1\nq\n' >> "$script"

# shellcheck disable=SC2086
exec "$jlink" -NoGui 1 -ExitOnError 1 -USB "$sn" $connect -CommandFile "$script"

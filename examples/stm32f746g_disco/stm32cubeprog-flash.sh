#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Flash an image with STM32CubeProgrammer. Runs on the labgrid exporter
# through FlashScriptDriver.
#
# usage: stm32cubeprog-flash.sh <usb-path> <image> [extra STM32_Programmer_CLI args]
#   usb-path  sysfs USB path of the ST-Link, e.g. 1-1 (labgrid: {device.path})
#   image     .hex or .elf (address inside) or .bin (flashed at 0x08000000)
set -eu

usb_path=$1
image=$2
shift 2

sn=$(cat "/sys/bus/usb/devices/$usb_path/serial")

cli=$(command -v STM32_Programmer_CLI 2>/dev/null || true)
if [ -z "$cli" ]; then
    for d in /opt/st/stm32cubeclt*/STM32CubeProgrammer/bin \
             /opt/st/stm32cubeide*/plugins/com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.*/tools/bin \
             "$HOME/STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin"; do
        if [ -x "$d/STM32_Programmer_CLI" ]; then
            cli="$d/STM32_Programmer_CLI"
            break
        fi
    done
fi
if [ -z "$cli" ]; then
    echo "STM32_Programmer_CLI not found on the exporter" >&2
    exit 1
fi

case "$image" in
    *.bin) write="-w $image 0x08000000" ;;
    *)     write="-w $image" ;;
esac

# shellcheck disable=SC2086
exec "$cli" -c port=SWD sn="$sn" mode=UR reset=HWrst $write -v -rst "$@"

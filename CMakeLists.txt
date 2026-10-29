# SPDX-License-Identifier: Apache-2.0
#
# Register the "labgrid" west runner for every board.
#
# Zephyr processes module CMake before cmake/flash, so appending the runner
# here makes it appear in <build>/zephyr/runners.yaml without touching any
# board.cmake. It never becomes the default flash runner; select it with
# `west flash -r labgrid` or `runner: labgrid` in a Twister hardware map.
board_finalize_runner_args(labgrid)

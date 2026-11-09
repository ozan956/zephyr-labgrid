# SPDX-License-Identifier: Apache-2.0
#
# Register the "labgrid" west runner for every board.
#
# Zephyr processes module CMake before cmake/flash, so appending the runner
# here makes it appear in <build>/zephyr/runners.yaml without touching any
# board.cmake. It is not the default flash runner unless the build sets
# BOARD_FLASH_RUNNER=labgrid.
board_finalize_runner_args(labgrid)

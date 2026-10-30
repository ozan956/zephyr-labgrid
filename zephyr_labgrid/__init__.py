# SPDX-License-Identifier: Apache-2.0
"""Helpers shared by the zephyr-labgrid command line tools.

The west runner itself lives in ``scripts/labgrid_runner.py`` because west
loads runner files by path. The console bridge, the hardware map generator
and the check tool live here so they can be installed with pip as well as
run from ``scripts/``.
"""

__version__ = '0.1.0'

# SPDX-License-Identifier: Apache-2.0
"""Print the places of a labgrid coordinator as JSON.

Internal helper of common.lab_places(), which runs it as a child process:
``python -m zephyr_labgrid.placeinfo -x COORDINATOR``. Prints
``{name: {"tags": {...}, "acquired": "host/user" or null, "allowed": [...]}}``.
Exit codes: 0 done, 1 coordinator error.
"""

import argparse
import json
import sys

from . import common


def main(argv=None):
    parser = argparse.ArgumentParser(prog='zephyr_labgrid.placeinfo')
    parser.add_argument('-x', '--coordinator', default=common.default_coordinator())
    args = parser.parse_args(argv)

    try:
        from labgrid.remote.client import start_session
        session = start_session(args.coordinator)
    except Exception as e:
        print(f'coordinator {args.coordinator} not reachable: {e}', file=sys.stderr)
        return 1
    try:
        places = {name: {'tags': dict(place.tags),
                         'acquired': place.acquired or None,
                         'allowed': sorted(getattr(place, 'allowed', None) or [])}
                  for name, place in session.places.items()}
        json.dump(places, sys.stdout)
        return 0
    finally:
        common.close_session(session)


if __name__ == '__main__':
    sys.exit(main())

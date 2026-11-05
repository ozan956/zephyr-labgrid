# SPDX-License-Identifier: Apache-2.0
"""Print the tags of a labgrid place as JSON.

Internal helper of common.place_tags(), which runs it as a child process:
``python -m zephyr_labgrid.placeinfo -x COORDINATOR PLACE``.
Exit codes: 0 found, 1 coordinator error, 2 unknown place.
"""

import argparse
import json
import sys

from . import common


def main(argv=None):
    parser = argparse.ArgumentParser(prog='zephyr_labgrid.placeinfo')
    parser.add_argument('-x', '--coordinator', default=common.default_coordinator())
    parser.add_argument('place')
    args = parser.parse_args(argv)

    try:
        from labgrid.remote.client import start_session
        session = start_session(args.coordinator)
    except Exception as e:
        print(f'coordinator {args.coordinator} not reachable: {e}', file=sys.stderr)
        return 1
    try:
        place = session.places.get(args.place)
        if place is None:
            print(f'place {args.place} does not exist on {args.coordinator}', file=sys.stderr)
            return 2
        json.dump(dict(place.tags), sys.stdout)
        return 0
    finally:
        common.close_session(session)


if __name__ == '__main__':
    sys.exit(main())

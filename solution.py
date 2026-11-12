#!/usr/bin/env python3
"""Usage: python3 solution.py INPUT_DIRECTORY OUTPUT_JSON"""
import sys
from coldstart.pipeline import main

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    try:
        main(sys.argv[1], sys.argv[2])
    except (ValueError, RuntimeError, OSError) as exc:
        print("Cold Start failed: " + str(exc), file=sys.stderr)
        sys.exit(1)

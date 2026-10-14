"""Real child-process fixtures for isolation tests (not parser mocks)."""

import json
import os
import sys
import time

if sys.argv[1] == "allocate":
    allocation = bytearray(64 * 1024**2)
if sys.argv[1] == "environment":
    with open(sys.argv[2], "w", encoding="utf-8") as target:
        json.dump(dict(os.environ), target)
    sys.exit(0)
if sys.argv[1] == "noisy":
    sys.stderr.write("x" * 2_000_000 + "END-OF-DIAGNOSTIC")
    sys.exit(1)
time.sleep(10)

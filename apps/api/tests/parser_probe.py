"""Real child-process fixtures for isolation tests (not parser mocks)."""

import sys
import time

if sys.argv[1] == "allocate":
    allocation = bytearray(64 * 1024**2)
time.sleep(10)

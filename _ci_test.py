#!/usr/bin/env python3
import sys
print(f"Python {sys.version}", flush=True)
mods = ["urllib.request","ssl","xml.etree.ElementTree","email.utils","json","re",
        "os","argparse","subprocess","concurrent.futures",
        "datetime","time"]
for m in mods:
    try:
        __import__(m)
        print(f"  OK: {m}", flush=True)
    except ImportError as e:
        print(f"  FAIL: {m} -> {e}", flush=True)
print("ALL IMPORTS DONE", flush=True)
sys.exit(0)

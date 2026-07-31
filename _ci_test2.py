#!/usr/bin/env python3
import os, sys
print(f"Python {sys.version}", flush=True)
print(f"CWD: {os.getcwd()}", flush=True)
# 测试读文件
try:
    with open("outputs/update_news.py") as f:
        lines = f.readlines()
    print(f"OK: read update_news.py ({len(lines)} lines)", flush=True)
except Exception as e:
    print(f"FAIL: read -> {e}", flush=True)
    sys.exit(1)
# 测试写文件
try:
    with open("outputs/_test_write.txt", "w") as f:
        f.write("test")
    print("OK: wrote file", flush=True)
except Exception as e:
    print(f"FAIL: write -> {e}", flush=True)
    sys.exit(2)
print("ALL OK", flush=True)

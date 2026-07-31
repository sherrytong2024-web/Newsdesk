#!/usr/bin/env python3
import sys, os, traceback
os.chdir(os.path.dirname(os.path.abspath(__file__)))
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ci_debug.log')
try:
    with open(log_path, 'w') as lf:
        lf.write(f"Python: {sys.version}\n")
        lf.write(f"CWD: {os.getcwd()}\n")
        lf.write(f"Args: {sys.argv}\n")
        lf.write(f"outputs/ exists: {os.path.exists('outputs')}\n")
        # 尝试导入并运行
        sys.path.insert(0, 'outputs')
        import update_news
        lf.write("Import OK\n")
        update_news.main()
        lf.write("main() completed OK\n")
except SystemExit as e:
    with open(log_path, 'a') as lf:
        lf.write(f"SystemExit: {e.code}\n")
    raise
except Exception as e:
    with open(log_path, 'a') as lf:
        lf.write(f"ERROR: {type(e).__name__}: {e}\n")
        traceback.print_exc(file=lf)
    sys.exit(1)

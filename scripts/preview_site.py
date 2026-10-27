"""Open the current full frontend preview, optionally at the share page."""
import argparse
import subprocess
import time
import urllib.request
import webbrowser
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from project_paths import FRONTEND as FRONT
from node_runtime import resolve_node, node_environment


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--share', action='store_true')
    args = ap.parse_args()
    if not (FRONT / 'dist/index.html').exists():
        raise SystemExit('Build first: Run-Python.cmd scripts/build_release.py --sync')
    node, _version = resolve_node()
    base = 'http://127.0.0.1:5180'
    def ready():
        try:
            with urllib.request.urlopen(base + '/api/manifest.json', timeout=1) as r:
                return r.status == 200
        except OSError:
            return False
    process = None
    if not ready():
        process = subprocess.Popen([node, 'server.mjs'], cwd=FRONT, env=node_environment(node))
        for _ in range(50):
            if ready():
                break
            if process.poll() is not None:
                raise SystemExit('Preview failed to start (check port 5180).')
            time.sleep(.1)
        else:
            process.terminate()
            raise SystemExit('Preview not ready')
    webbrowser.open(base + ('/share/' if args.share else '/'))
    if process:
        print('Preview is running. Close this window or press Ctrl+C to stop it.')
        try:
            process.wait()
        except KeyboardInterrupt:
            process.terminate()


if __name__ == '__main__':
    main()

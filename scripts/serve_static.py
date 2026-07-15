"""Tiny static file server for local preview -- avoids Python's stdlib
`python3 -m http.server` CLI, whose argparse default (`default=os.getcwd()`)
crashes in this sandboxed environment even when --directory is passed,
because os.getcwd() itself is unavailable here. This script hardcodes the
directory instead of ever calling getcwd()."""

import functools
import http.server
import os

PORT = 8000
# Repo root (parent of scripts/), so /heat/ paths work from any checkout.
DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIRECTORY)

if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving {DIRECTORY} at http://0.0.0.0:{PORT}")
        httpd.serve_forever()

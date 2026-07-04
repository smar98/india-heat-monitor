"""Tiny static file server for local preview -- avoids Python's stdlib
`python3 -m http.server` CLI, whose argparse default (`default=os.getcwd()`)
crashes in this sandboxed environment even when --directory is passed,
because os.getcwd() itself is unavailable here. This script hardcodes the
directory instead of ever calling getcwd()."""

import functools
import http.server

PORT = 8000
DIRECTORY = "/Users/sanch/Desktop/Data Viz Project 1"

Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIRECTORY)

if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving {DIRECTORY} at http://0.0.0.0:{PORT}")
        httpd.serve_forever()

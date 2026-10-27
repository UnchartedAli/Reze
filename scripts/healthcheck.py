#!/usr/bin/env python3
"""
Container/platform health probe for Reze.

Checks the local web panel's public /healthz endpoint. Uses the platform PORT
variable (Render, Railway, Koyeb, Fly, ...) or REZE_WEB_PORT, defaulting to 8080.

Developer: UnchartedAli · Channel: @yamods
"""

import argparse
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Reze health check")
    parser.add_argument(
        "--port",
        default=os.getenv("PORT") or os.getenv("REZE_WEB_PORT") or "8080",
        help="Local panel port (default: PORT or REZE_WEB_PORT or 8080)",
    )
    parser.add_argument("--timeout", type=float, default=4.0)
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=args.timeout) as response:
            if 200 <= response.status < 300:
                print(f"OK: {url}")
                return 0
            print(f"UNHEALTHY: {url} returned {response.status}", file=sys.stderr)
            return 1
    except urllib.error.URLError as exc:
        print(f"UNHEALTHY: {url} - {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        print(f"UNHEALTHY: {url} - {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

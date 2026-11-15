"""End-to-end smoke test for a running REZE panel.

Start the bot (for example ``python -m reze.app``) with the panel on a known port, then run:

    REZE_PANEL_PASSWORD=... python scripts/smoke_panel.py http://127.0.0.1:8080 admin

It checks /healthz, signs in, then loads every page listed in the navigation. A page fails
if the status is not 200, or if the body contains a traceback. Exit status is 1 on any failure.
Developer: UnchartedAli · Channel: @yamods
"""

import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def nav_paths():
    from reze.web import theme

    paths = []
    for _section, items in theme.NAV_SECTIONS:
        for _key, _label, path in items:
            if path not in paths:
                paths.append(path)
    return paths


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    base, username = argv[1].rstrip("/"), argv[2]
    password = os.environ.get("REZE_PANEL_PASSWORD", "")
    if not password:
        print("Set REZE_PANEL_PASSWORD in the environment.")
        return 2
    jar = CookieJar()

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    no_redirect = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(jar))

    failures = []
    health = opener.open(base + "/healthz", timeout=10).status
    print(f"healthz            {health}")
    if health != 200:
        failures.append("healthz")

    body = urllib.parse.urlencode({"username": username, "password": password}).encode()
    try:
        response = no_redirect.open(urllib.request.Request(base + "/login", data=body, method="POST"), timeout=10)
        status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    print(f"login              {status}")
    if status not in (302, 303):
        failures.append("login")

    for path in nav_paths():
        try:
            response = opener.open(base + path, timeout=15)
            status, html = response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            status, html = error.code, ""
        bad = status != 200 or bool(re.search(r"Traceback|Internal Server Error", html))
        print(f"{path:<18} {status}{'  <-- FAIL' if bad else ''}")
        if bad:
            failures.append(path)

    if failures:
        print(f"\n{len(failures)} failure(s): {', '.join(failures)}")
        return 1
    print("\nAll pages loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

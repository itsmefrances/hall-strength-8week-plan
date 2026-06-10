#!/usr/bin/env python3
"""One-time helper to obtain a Concept2 Logbook refresh token.

Prerequisite: create an API application at https://log.concept2.com/developers/keys
with redirect URI exactly:  http://localhost:8676/callback

Usage:
    python3 scripts/concept2_auth.py CLIENT_ID CLIENT_SECRET

Opens the Concept2 authorization page, catches the redirect on localhost,
exchanges the code, and prints the refresh token to store as the
C2_REFRESH_TOKEN repository secret.
"""

import http.server
import json
import sys
import urllib.parse
import urllib.request
import webbrowser

BASE = "https://log.concept2.com"
PORT = 8676
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPE = "user:read,results:read"


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    client_id, client_secret = sys.argv[1], sys.argv[2]

    auth_url = f"{BASE}/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "scope": SCOPE,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
    })
    print(f"\nOpen this URL in your browser and authorize:\n\n  {auth_url}\n")
    webbrowser.open(auth_url)

    code_holder = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code_holder["code"] = (query.get("code") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Authorized — you can close this tab and return to the terminal.</h2>")

        def log_message(self, *args):
            pass

    with http.server.HTTPServer(("localhost", PORT), Handler) as server:
        print(f"Waiting for the redirect on {REDIRECT_URI} ...")
        while "code" not in code_holder:
            server.handle_request()

    if not code_holder["code"]:
        raise SystemExit("No authorization code received — try again.")

    payload = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code_holder["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/oauth/access_token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))

    print("\nSuccess! Add these as GitHub repository secrets (Settings → Secrets → Actions):\n")
    print(f"  C2_CLIENT_ID      = {client_id}")
    print(f"  C2_CLIENT_SECRET  = {client_secret}")
    print(f"  C2_REFRESH_TOKEN  = {tokens['refresh_token']}\n")


if __name__ == "__main__":
    main()

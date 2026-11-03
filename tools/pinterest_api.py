#!/usr/bin/env python3
"""Pinterest API v5: crea pin dai CSV del repo, gestisce OAuth.

Solo libreria standard. I segreti si leggono SOLO da variabili d'ambiente
e non vengono mai stampati.

  PINTEREST_APP_ID, PINTEREST_APP_SECRET   app sviluppatore
  PINTEREST_SANDBOX_TOKEN                  token sandbox (--sandbox)
  PINTEREST_ACCESS_TOKEN                   token OAuth produzione
  PINTEREST_REFRESH_TOKEN                  per rinnovare il token produzione

Comandi:
  whoami                         account collegato al token
  boards                         elenco bacheche (id e nome)
  create-board NOME              crea una bacheca
  pin-csv FILE.csv [--only N] [--dry-run] [--board-id ID]
                                 crea i pin del CSV (formato bulk Pinterest).
                                 --board-id forza una bacheca (utile in sandbox,
                                 dove l'elenco bacheche torna vuoto).
                                 La colonna "Publish date" viene ignorata:
                                 l'API pubblica subito.
  auth-url                       link di autorizzazione OAuth da aprire
  exchange CODE                  scambia il code del callback con i token
  refresh                        rinnova il token produzione

Esempio collaudo:  python tools/pinterest_api.py --sandbox create-board "Sandbox Test"
                   python tools/pinterest_api.py --sandbox pin-csv csv/pin-nuovi-9.csv --only 1 --board-id ID
"""
import argparse
import base64
import csv
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

PROD = "https://api.pinterest.com/v5"
SANDBOX = "https://api-sandbox.pinterest.com/v5"
REDIRECT_URI = "https://www.fabriziomazzei.it/pinterest-callback"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"


def env(name):
    val = os.environ.get(name)
    if not val:
        sys.exit(f"Manca la variabile d'ambiente {name}")
    return val


def call(base, token, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"Errore API {e.code} su {method} {path}: {e.read().decode(errors='replace')[:500]}")
    except urllib.error.URLError as e:
        sys.exit(f"Rete: impossibile raggiungere {base} ({e.reason})")


def oauth_token(form):
    auth = base64.b64encode(f"{env('PINTEREST_APP_ID')}:{env('PINTEREST_APP_SECRET')}".encode()).decode()
    req = urllib.request.Request(PROD + "/oauth/token", data=urllib.parse.urlencode(form).encode(), method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Errore OAuth {e.code}: {e.read().decode(errors='replace')[:500]}")


def save_tokens(tok, path):
    # Scrive i token in un file locale (mai in git, mai stampati).
    with open(path, "w") as f:
        json.dump(tok, f)
    os.chmod(path, 0o600)
    print(f"Token salvati in {path} (scope: {tok.get('scope')}, scade tra {tok.get('expires_in')} s)")


def all_boards(base, token):
    out, bookmark = [], None
    while True:
        q = "/boards?page_size=100" + (f"&bookmark={bookmark}" if bookmark else "")
        res = call(base, token, "GET", q)
        out += res.get("items", [])
        bookmark = res.get("bookmark")
        if not bookmark:
            return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sandbox", action="store_true", help="usa api-sandbox e PINTEREST_SANDBOX_TOKEN")
    p.add_argument("--token-file", default=os.path.expanduser("~/.pinterest_tokens.json"))
    p.add_argument("cmd")
    p.add_argument("arg", nargs="?")
    p.add_argument("--only", type=int, help="crea solo i primi N pin")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--board-id", help="usa questa bacheca per tutti i pin")
    a = p.parse_args()

    if a.cmd == "auth-url":
        state = secrets.token_urlsafe(16)
        q = urllib.parse.urlencode({"client_id": env("PINTEREST_APP_ID"), "redirect_uri": REDIRECT_URI,
                                    "response_type": "code", "scope": SCOPES, "state": state})
        print("https://www.pinterest.com/oauth/?" + q)
        return
    if a.cmd == "exchange":
        if not a.arg:
            sys.exit("Serve il code")
        save_tokens(oauth_token({"grant_type": "authorization_code", "code": a.arg,
                                 "redirect_uri": REDIRECT_URI}), a.token_file)
        return
    if a.cmd == "refresh":
        rt = os.environ.get("PINTEREST_REFRESH_TOKEN")
        if not rt and os.path.exists(a.token_file):
            rt = json.load(open(a.token_file)).get("refresh_token")
        if not rt:
            sys.exit("Manca il refresh token")
        save_tokens(oauth_token({"grant_type": "refresh_token", "refresh_token": rt}), a.token_file)
        return

    base = SANDBOX if a.sandbox else PROD
    if a.sandbox:
        token = env("PINTEREST_SANDBOX_TOKEN")
    else:
        token = os.environ.get("PINTEREST_ACCESS_TOKEN")
        if not token and os.path.exists(a.token_file):
            token = json.load(open(a.token_file)).get("access_token")
        if not token:
            sys.exit("Manca PINTEREST_ACCESS_TOKEN (fai prima auth-url + exchange)")

    if a.cmd == "whoami":
        u = call(base, token, "GET", "/user_account")
        print(f"{u.get('username')} ({u.get('account_type')})")
    elif a.cmd == "boards":
        for b in all_boards(base, token):
            print(f"{b['id']}\t{b['name']}")
    elif a.cmd == "create-board":
        b = call(base, token, "POST", "/boards", {"name": a.arg, "privacy": "PUBLIC"})
        print(f"Creata: {b['id']}\t{b['name']}")
    elif a.cmd == "pin-csv":
        rows = list(csv.DictReader(open(a.arg, encoding="utf-8")))[: a.only or None]
        boards = {} if a.board_id else {b["name"]: b["id"] for b in all_boards(base, token)}
        for r in rows:
            name = r["Pinterest board"]
            if a.board_id:
                boards[name] = a.board_id
            elif name not in boards:
                if a.dry_run:
                    boards[name] = "(da creare)"
                else:
                    boards[name] = call(base, token, "POST", "/boards", {"name": name, "privacy": "PUBLIC"})["id"]
                    print(f"Bacheca creata: {name}")
            body = {"board_id": boards[name], "title": r["Title"][:100], "description": r["Description"][:800],
                    "link": r["Link"], "alt_text": r["Title"][:500],
                    "media_source": {"source_type": "image_url", "url": r["Media URL"]}}
            if a.dry_run:
                print("DRY", json.dumps(body, ensure_ascii=False))
                continue
            pin = call(base, token, "POST", "/pins", body)
            print(f"Pin creato {pin.get('id')}: {r['Title']}")
    else:
        sys.exit(f"Comando sconosciuto: {a.cmd}")


if __name__ == "__main__":
    main()

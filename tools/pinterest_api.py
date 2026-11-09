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
  publish-due CODA.csv [...] [--log FILE] [--max N] [--dry-run]
                                 pubblica i pin con "Publish date" (UTC) gia'
                                 arrivata e non ancora nel log (pubblicati.csv);
                                 max N per giro (default 2). Per la GitHub Action.
  auth-url                       link di autorizzazione OAuth da aprire
  exchange CODE                  scambia il code del callback con i token
  refresh                        rinnova il token produzione
  demo                           video per l'accesso Standard, tutto in uno:
                                 apre OAuth, chiede l'indirizzo della pagina di
                                 ritorno, scambia il code, crea bacheca e pin

Esempio collaudo:  python tools/pinterest_api.py --sandbox create-board "Sandbox Test"
                   python tools/pinterest_api.py --sandbox pin-csv csv/pin-nuovi-9.csv --only 1 --board-id ID
"""
import argparse
import datetime
import glob
import getpass
import time
import webbrowser
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


FILES = {"PINTEREST_APP_SECRET": "app-secret.txt", "PINTEREST_SANDBOX_TOKEN": "sandbox-token.txt"}


def env(name):
    val = (os.environ.get(name) or "").strip()
    if not val and name in FILES and os.path.exists(FILES[name]):
        # File locale nella cartella corrente: il valore non passa dallo schermo.
        val = open(FILES[name], encoding="utf-8-sig").read().strip()
        os.environ[name] = val
    if not val and name in ("PINTEREST_APP_ID", "PINTEREST_APP_SECRET") and sys.stdin.isatty():
        # Input nascosto: il valore non compare a schermo.
        val = getpass.getpass(f"{name} (non viene mostrato): ").strip()
        os.environ[name] = val
    if not val:
        sys.exit(f"Manca la variabile d'ambiente {name}")
    return val


DEMO_PIN = {"title": "Excel formulas without memorizing syntax",
            "description": "Describe what you need in plain English and let ChatGPT, Claude or Gemini write the Excel "
                           "or Google Sheets formula. A 4-part brief, error fixes and 16 everyday formulas on a "
                           "printable cheat sheet.",
            "link": "https://www.etsy.com/listing/4608386910",
            "alt_text": "Excel formulas without memorizing syntax",
            "media_source": {"source_type": "image_url",
                             "url": "https://raw.githubusercontent.com/fabriziomazzei/pinterest-pins/main/pin/pin-excel-1.png"}}


def demo(token_file):
    env("PINTEREST_APP_ID"), env("PINTEREST_APP_SECRET")
    state = secrets.token_urlsafe(16)
    url = "https://www.pinterest.com/oauth/?" + urllib.parse.urlencode(
        {"client_id": env("PINTEREST_APP_ID"), "redirect_uri": REDIRECT_URI,
         "response_type": "code", "scope": SCOPES, "state": state})
    print("1. Collego FM Pin Publisher al tuo account Pinterest (OAuth). Apro il browser...")
    webbrowser.open(url)
    back = input("2. Dopo 'Consenti', incolla qui l'indirizzo della pagina 'Pinterest connected': ").strip()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    if q.get("state", [""])[0] != state or not q.get("code"):
        sys.exit("Indirizzo non valido: rifai 'demo' e incolla l'indirizzo completo.")
    print("3. Scambio il code con il token (il token non viene mostrato)...")
    tok = oauth_token({"grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": REDIRECT_URI})
    save_tokens(tok, token_file)
    token = tok["access_token"]
    u = call(PROD, token, "GET", "/user_account")
    print(f"4. Account collegato: {u.get('username')}")
    # Produzione con il token OAuth: in Trial solo letture affidabili (le scritture danno 403 code 29).
    boards = all_boards(PROD, token)
    print(f"5. Bacheche lette via API: {len(boards)}")
    pins = call(PROD, token, "GET", "/pins?page_size=5").get("items", [])
    print(f"6. Pin letti via API: {len(pins)} (ultimi)")
    name = "API Demo " + time.strftime("%Y-%m-%d %H%M")
    # In Trial i pin si creano solo su api-sandbox, che accetta solo il token sandbox del portale.
    sb = (os.environ.get("PINTEREST_SANDBOX_TOKEN") or "").strip()
    if not sb and os.path.exists(FILES["PINTEREST_SANDBOX_TOKEN"]):
        sb = env("PINTEREST_SANDBOX_TOKEN")
    if not sb and sys.stdin.isatty():
        sb = getpass.getpass("7. Token sandbox per creare il pin (non viene mostrato, Invio per saltare): ").strip()
    if not sb:
        print("Fine (pin saltato).")
        return
    sbb = call(SANDBOX, sb, "POST", "/boards", {"name": name, "privacy": "PUBLIC"})
    pin = call(SANDBOX, sb, "POST", "/pins", dict(DEMO_PIN, board_id=sbb["id"]))
    p = call(SANDBOX, sb, "GET", f"/pins/{pin['id']}")
    print(f"8. Pin creato via API (sandbox, accesso Trial): id {pin['id']}")
    print(f"   Titolo: {p.get('title')}\n   Link:   {p.get('link')}")
    img = ((p.get("media") or {}).get("images") or {}).get("1200x", {}).get("url", "")
    if img:
        print(f"   Immagine elaborata da Pinterest: {img}")
        webbrowser.open(img)


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


LOG_FIELDS = ["published_at_utc", "pin_id", "Media URL", "Publish date", "Title", "Link"]


def pin_body(r, board_id):
    return {"board_id": board_id, "title": r["Title"][:100], "description": r["Description"][:800],
            "link": r["Link"], "alt_text": r["Title"][:500],
            "media_source": {"source_type": "image_url", "url": r["Media URL"]}}


def publish_due(base, token, patterns, log_path, max_n, dry_run):
    # Chiave anti-doppione: immagine + data prevista. Il log e' la verita' su cosa e' gia' uscito.
    done = set()
    if os.path.exists(log_path):
        done = {(r["Media URL"], r["Publish date"]) for r in csv.DictReader(open(log_path, encoding="utf-8"))}
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    rows = []
    for path in sorted({p for pat in patterns for p in glob.glob(pat)}):
        rows += list(csv.DictReader(open(path, encoding="utf-8")))
    due = sorted((r for r in rows if r["Publish date"]
                  and datetime.datetime.fromisoformat(r["Publish date"]) <= now
                  and (r["Media URL"], r["Publish date"]) not in done), key=lambda r: r["Publish date"])
    print(f"In coda: {len(rows)}, da pubblicare ora: {len(due)}, in questo giro: {min(len(due), max_n)}")
    # Controllo bacheche su tutta la coda futura, cosi' la prova a vuoto segnala subito quelle mancanti.
    boards = {b["name"]: b["id"] for b in all_boards(base, token)}
    pending = {r["Pinterest board"] for r in rows if (r["Media URL"], r["Publish date"]) not in done}
    missing = sorted(pending - set(boards))
    print("Bacheche della coda: " + ", ".join(f"{n} {'OK' if n in boards else 'MANCA'}" for n in sorted(pending)))
    if not due:
        if missing:
            sys.exit(f"Bacheche da creare sul profilo: {', '.join(missing)}")
        return
    new_log = not os.path.exists(log_path)
    for r in due[:max_n]:
        name = r["Pinterest board"]
        if name not in boards:
            sys.exit(f"Bacheca inesistente: {name} (creala a mano, niente bacheche create in automatico)")
        if dry_run:
            print(f"DRY {r['Publish date']} {r['Title']} -> {name}")
            continue
        pin = call(base, token, "POST", "/pins", pin_body(r, boards[name]))
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            if new_log:
                w.writeheader()
                new_log = False
            w.writerow({"published_at_utc": now.strftime("%Y-%m-%dT%H:%M:%S"), "pin_id": pin.get("id"),
                        **{k: r[k] for k in LOG_FIELDS[2:]}})
        print(f"Pin pubblicato {pin.get('id')}: {r['Title']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sandbox", action="store_true", help="usa api-sandbox e PINTEREST_SANDBOX_TOKEN")
    p.add_argument("--token-file", default=os.path.expanduser("~/.pinterest_tokens.json"))
    p.add_argument("cmd")
    p.add_argument("arg", nargs="?")
    p.add_argument("--only", type=int, help="crea solo i primi N pin")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--board-id", help="usa questa bacheca per tutti i pin")
    p.add_argument("files", nargs="*", help="altri CSV per publish-due")
    p.add_argument("--log", default="pubblicati.csv")
    p.add_argument("--max", type=int, default=2)
    a = p.parse_args()

    if a.cmd == "demo":
        demo(a.token_file)
        return
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
    elif a.cmd == "publish-due":
        publish_due(base, token, [a.arg] + a.files, a.log, a.max, a.dry_run)
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

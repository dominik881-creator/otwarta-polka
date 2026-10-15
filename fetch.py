#!/usr/bin/env python3
"""
Otwarta Półka — zbieracz danych.

Pobiera aplikacje open source z Flathub (Linux) i F-Droid (Android),
opisuje je prostym polskim językiem przez Groq i zapisuje docs/data.json,
który czyta strona (docs/index.html).

Opisy trafiają do cache/opisy.json, więc każda apka jest opisywana tylko raz.

Zmienne środowiskowe:
  GROQ_API_KEY   – klucz Groq (bez niego zostają oryginalne angielskie opisy)
  GROQ_MODEL     – domyślnie openai/gpt-oss-20b
  GITHUB_TOKEN   – opcjonalny; służy do pobrania gwiazdek GitHub dla apek z F-Droid
  MAX_NEW        – ile nowych apek opisać w jednym uruchomieniu (domyślnie 400)
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs" / "data.json"
CACHE = ROOT / "cache" / "opisy.json"

GROQ_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GH_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
MAX_NEW = int(os.getenv("MAX_NEW", "400"))
BATCH = 8  # ile apek w jednym zapytaniu do Groq

# Ile apek brać z każdego źródła
FLATHUB_POPULAR = 300
FLATHUB_TRENDING = 80
FLATHUB_NEW = 60
FDROID_LIMIT = 300
FDROID_MAX_AGE_DAYS = 365  # pomijaj porzucone apki

FLATHUB_API = "https://flathub.org/api/v2"
FDROID_REPO = "https://f-droid.org/repo"

CATEGORIES = [
    "Internet i przeglądarki",
    "Komunikacja",
    "Muzyka i wideo",
    "Grafika i zdjęcia",
    "Biuro i notatki",
    "Gry",
    "Prywatność i bezpieczeństwo",
    "Narzędzia",
    "System",
    "Nauka i edukacja",
    "Programowanie",
    "Mapy i podróże",
    "Zdrowie i sport",
    "Finanse",
    "Czytanie",
]

# Awaryjne przypisanie kategorii (gdy nie ma Groq)
FALLBACK_MAP = {
    "webbrowser": "Internet i przeglądarki", "network": "Internet i przeglądarki",
    "internet": "Internet i przeglądarki", "filetransfer": "Internet i przeglądarki",
    "instantmessaging": "Komunikacja", "chat": "Komunikacja", "email": "Komunikacja",
    "phone & sms": "Komunikacja", "telephony": "Komunikacja",
    "audiovideo": "Muzyka i wideo", "multimedia": "Muzyka i wideo", "audio": "Muzyka i wideo",
    "video": "Muzyka i wideo", "player": "Muzyka i wideo",
    "graphics": "Grafika i zdjęcia", "photography": "Grafika i zdjęcia",
    "office": "Biuro i notatki", "writing": "Biuro i notatki", "time": "Biuro i notatki",
    "game": "Gry", "games": "Gry", "emulator": "Gry",
    "security": "Prywatność i bezpieczeństwo",
    "utility": "Narzędzia", "connectivity": "Narzędzia", "theming": "Narzędzia",
    "system": "System",
    "education": "Nauka i edukacja", "science": "Nauka i edukacja",
    "science & education": "Nauka i edukacja",
    "development": "Programowanie",
    "navigation": "Mapy i podróże", "maps": "Mapy i podróże",
    "sports & health": "Zdrowie i sport",
    "money": "Finanse", "finance": "Finanse",
    "reading": "Czytanie",
}

session = requests.Session()
session.headers["User-Agent"] = "OtwartaPolka/1.0 (+https://github.com)"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def strip_markup(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"[*_`#]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def get_json(url, **kw):
    for attempt in range(4):
        try:
            r = session.get(url, timeout=60, **kw)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log(f"  błąd {url} ({e}), próba {attempt + 1}")
            time.sleep(2 * (attempt + 1))
    return None


# ---------------------------------------------------------------- Flathub

def flathub_collection(name, limit):
    hits, page = [], 1
    while len(hits) < limit:
        data = get_json(f"{FLATHUB_API}/collection/{name}", params={"page": page, "per_page": 50})
        if not data or not data.get("hits"):
            break
        hits += data["hits"]
        if page >= data.get("totalPages", 1):
            break
        page += 1
    return hits


def pick_screens(screenshots, n=4):
    """Wybiera z każdego zrzutu rozmiar najbliższy 624 px szerokości.
    Flathub podaje rozmiary jako listę {src, width, height} albo (starszy format) słownik {"624x351": url}."""
    def as_int(v):
        try:
            return int(str(v).split("x")[0])
        except ValueError:
            return 0

    out = []
    for s in screenshots or []:
        if not isinstance(s, dict):
            continue
        sizes = s.get("sizes") or []
        if isinstance(sizes, dict):
            sizes = [{"src": url, "width": key} for key, url in sizes.items()]
        sizes = [x for x in sizes if isinstance(x, dict) and x.get("src")]
        if not sizes:
            continue
        best = min(sizes, key=lambda x: abs(as_int(x.get("width")) - 624))
        out.append(best["src"])
        if len(out) >= n:
            break
    return out


def collect_flathub(cache):
    log("Flathub…")
    apps = {}
    lists = {
        "popular": flathub_collection("popular", FLATHUB_POPULAR),
        "trending": flathub_collection("trending", FLATHUB_TRENDING),
        "recently-added": flathub_collection("recently-added", FLATHUB_NEW),
    }
    for list_name, hits in lists.items():
        rank = 0
        for h in hits:
            if not h.get("is_free_license"):
                continue  # tylko open source
            if h.get("type") not in ("desktop-application", "console-application", "desktop"):
                continue
            rank += 1
            app_id = h["app_id"]
            key = "flathub:" + app_id
            a = apps.get(key)
            if not a:
                mc = h.get("main_categories") or []
                if isinstance(mc, str):
                    mc = [mc]
                a = {
                    "id": key,
                    "name": h.get("name") or app_id,
                    "icon": h.get("icon") or "",
                    "dev": h.get("developer_name") or "",
                    "summary": h.get("summary") or "",
                    "raw": strip_markup(h.get("description"))[:900],
                    "src_cats": [c.lower() for c in mc + (h.get("sub_categories") or [])],
                    "license": h.get("project_license") or "",
                    "platforms": ["Linux"],
                    "installs": h.get("installs_last_month") or 0,
                    "stars": 0,
                    "added": h.get("added_at") or 0,
                    "updated": h.get("updated_at") or 0,
                    "links": {"flathub": f"https://flathub.org/apps/{app_id}"},
                    "screens": [],
                    "ranks": {},
                }
                apps[key] = a
            a["ranks"][list_name] = rank

    # Szczegóły (strona, kod, zrzuty ekranu) — tylko dla apek bez nich w cache
    details = cache.setdefault("_flathub_details", {})
    for key, a in apps.items():
        app_id = key.split(":", 1)[1]
        d = details.get(app_id)
        if d is None:
            try:
                st = get_json(f"{FLATHUB_API}/appstream/{app_id}") or {}
                urls = st.get("urls") or {}
                d = {
                    "strona": urls.get("homepage") or "",
                    "kod": urls.get("vcs_browser") or "",
                    "screens": pick_screens(st.get("screenshots")),
                }
            except Exception as e:  # jedna dziwna apka nie może wywalić całości
                log(f"  pomijam szczegóły {app_id}: {e}")
                d = {"strona": "", "kod": "", "screens": []}
            details[app_id] = d
            time.sleep(0.1)
        if d.get("strona"):
            a["links"]["strona"] = d["strona"]
        if d.get("kod"):
            a["links"]["kod"] = d["kod"]
        a["screens"] = d.get("screens") or []
    log(f"  {len(apps)} apek open source")
    return apps


# ---------------------------------------------------------------- F-Droid

def loc(value):
    """Wybiera wersję angielską z pola zlokalizowanego F-Droid."""
    if not isinstance(value, dict):
        return value
    for k in ("en-US", "en", "en-GB"):
        if k in value:
            return value[k]
    return next(iter(value.values()), None)


def github_stars(repos):
    """repos: lista 'owner/name'. Zwraca dict -> liczba gwiazdek (GraphQL, 50 na zapytanie)."""
    if not GH_TOKEN or not repos:
        return {}
    out = {}
    headers = {"Authorization": f"bearer {GH_TOKEN}"}
    for i in range(0, len(repos), 50):
        chunk = repos[i:i + 50]
        parts = []
        for j, full in enumerate(chunk):
            owner, name = full.split("/", 1)
            parts.append(f'r{j}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ stargazerCount }}')
        q = "query {" + " ".join(parts) + "}"
        try:
            r = session.post("https://api.github.com/graphql", json={"query": q}, headers=headers, timeout=60)
            data = (r.json() or {}).get("data") or {}
        except (requests.RequestException, ValueError) as e:
            log(f"  GitHub: {e}")
            continue
        for j, full in enumerate(chunk):
            node = data.get(f"r{j}")
            if node:
                out[full] = node["stargazerCount"]
    return out


def collect_fdroid():
    log("F-Droid (pobieram indeks, to kilkadziesiąt MB)…")
    idx = get_json(f"{FDROID_REPO}/index-v2.json")
    if not idx:
        log("  nie udało się pobrać indeksu F-Droid")
        return {}
    now_ms = time.time() * 1000
    cutoff = now_ms - FDROID_MAX_AGE_DAYS * 86400 * 1000
    candidates = []
    for pkg, p in (idx.get("packages") or {}).items():
        try:
            m = p.get("metadata") or {}
            if (m.get("lastUpdated") or 0) < cutoff:
                continue
            name = loc(m.get("name"))
            if not name:
                continue
            icon = loc(m.get("icon")) or {}
            phone = loc((m.get("screenshots") or {}).get("phoneScreenshots") or (m.get("screenshots") or {}).get("phone") or {}) or []
            src = m.get("sourceCode") or ""
            gh = re.match(r"https?://github\.com/([^/]+/[^/#?]+)", src)
            candidates.append({
                "id": "fdroid:" + pkg,
                "name": name,
                "icon": (FDROID_REPO + icon["name"]) if isinstance(icon, dict) and icon.get("name") else "",
                "dev": m.get("authorName") or "",
                "summary": loc(m.get("summary")) or "",
                "raw": strip_markup(loc(m.get("description")))[:900],
                "src_cats": [c.lower() for c in (m.get("categories") or [])],
                "license": m.get("license") or "",
                "platforms": ["Android"],
                "installs": 0,
                "stars": 0,
                "added": int((m.get("added") or 0) / 1000),
                "updated": int((m.get("lastUpdated") or 0) / 1000),
                "links": {k: v for k, v in {
                    "fdroid": f"https://f-droid.org/packages/{pkg}/",
                    "strona": m.get("webSite") or "",
                    "kod": src,
                }.items() if v},
                "screens": [FDROID_REPO + s["name"] for s in phone[:4] if isinstance(s, dict) and s.get("name")],
                "ranks": {},
                "_gh": gh.group(1).removesuffix(".git") if gh else None,
            })
        except Exception as e:  # jedna dziwna apka nie może wywalić całości
            log(f"  pomijam {pkg}: {e}")
    log(f"  {len(candidates)} aktywnych apek")

    stars = github_stars(sorted({c["_gh"] for c in candidates if c["_gh"]}))
    for c in candidates:
        c["stars"] = stars.get(c["_gh"], 0) if c["_gh"] else 0
    if stars:
        candidates.sort(key=lambda c: (c["stars"], c["updated"]), reverse=True)
    else:
        candidates.sort(key=lambda c: c["updated"], reverse=True)
    picked = candidates[:FDROID_LIMIT]
    for i, c in enumerate(picked, 1):
        c["ranks"]["popular"] = i
        c.pop("_gh", None)
    # najnowsze w F-Droid
    for i, c in enumerate(sorted(picked, key=lambda c: c["added"], reverse=True)[:FLATHUB_NEW], 1):
        c["ranks"]["recently-added"] = i
    return {c["id"]: c for c in picked}


# ---------------------------------------------------------------- scalanie

def merge(flathub, fdroid):
    """Ta sama apka na Linuksie i Androidzie (np. LocalSend) staje się jedną kartą."""
    by_name = {norm(a["name"]): a for a in flathub.values()}
    out = dict(flathub)
    for a in fdroid.values():
        twin = by_name.get(norm(a["name"]))
        if twin:
            twin["platforms"] = sorted(set(twin["platforms"]) | {"Android"})
            for k, v in a["links"].items():
                twin["links"].setdefault(k, v)
            twin["stars"] = max(twin["stars"], a["stars"])
        else:
            out[a["id"]] = a
    return out


# ---------------------------------------------------------------- Groq

PROMPT = """Opisujesz aplikacje open source do katalogu w stylu sklepu Google Play.
Czytelnik to zwykły użytkownik, nie programista. Pisz po polsku, prosto i konkretnie.

Dla każdej aplikacji zwróć:
- "haslo": jedno krótkie zdanie (maks. 70 znaków), co to jest. Bez kropki na końcu.
- "opis": 2–3 zdania (maks. 350 znaków): do czego służy, dla kogo, czym się wyróżnia.
  Bez marketingowych przymiotników i bez żargonu. Jeśli termin techniczny jest konieczny, wyjaśnij go w kilku słowach.
- "kategoria": DOKŁADNIE jedna wartość z listy: {cats}
- "zamiennik": nazwa znanej komercyjnej aplikacji, którą ta zastępuje (np. "Photoshop", "Spotify").
  Pusty tekst, jeśli nie ma oczywistego odpowiednika albo nie masz pewności.

Nie wymyślaj funkcji, których nie ma w danych wejściowych.
Odpowiedz wyłącznie JSON-em: {{"apps": [{{"id": "...", "haslo": "...", "opis": "...", "kategoria": "...", "zamiennik": "..."}}]}}

Aplikacje:
{apps}"""


def groq_call(batch):
    payload = [{
        "id": a["id"], "nazwa": a["name"], "platforma": "/".join(a["platforms"]),
        "podsumowanie": a["summary"], "opis_zrodlowy": a["raw"][:700],
        "kategorie_zrodlowe": a["src_cats"][:6],
    } for a in batch]
    body = {
        "model": GROQ_MODEL,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": PROMPT.format(
            cats=" | ".join(CATEGORIES), apps=json.dumps(payload, ensure_ascii=False))}],
    }
    for attempt in range(5):
        r = session.post("https://api.groq.com/openai/v1/chat/completions",
                         headers={"Authorization": f"Bearer {GROQ_KEY}"}, json=body, timeout=120)
        if r.status_code == 429:
            wait = float(r.headers.get("retry-after", 20))
            log(f"  limit Groq, czekam {wait:.0f} s")
            time.sleep(min(wait, 120))
            continue
        if r.status_code >= 400:
            log(f"  Groq {r.status_code}: {r.text[:300]}")
            if r.status_code in (401, 403, 404):
                raise SystemExit("Sprawdź GROQ_API_KEY i GROQ_MODEL.")
            time.sleep(5)
            continue
        try:
            content = r.json()["choices"][0]["message"]["content"]
            return {x["id"]: x for x in json.loads(content).get("apps", []) if "id" in x}
        except (KeyError, ValueError) as e:
            log(f"  niepoprawna odpowiedź Groq ({e}), ponawiam")
    return {}


def fallback_category(a):
    for c in a["src_cats"]:
        if c in FALLBACK_MAP:
            return FALLBACK_MAP[c]
    return "Narzędzia"


def describe(apps, cache):
    opisy = cache.setdefault("opisy", {})
    todo = [a for a in apps.values() if a["id"] not in opisy]
    # najpierw najważniejsze: na topie, popularne
    todo.sort(key=lambda a: min(a["ranks"].values() or [9999]))
    if not GROQ_KEY:
        log("Brak GROQ_API_KEY — używam oryginalnych opisów.")
        todo = []
    todo = todo[:MAX_NEW]
    log(f"Opisuję {len(todo)} nowych apek (Groq, {GROQ_MODEL})…")
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        result = groq_call(batch)
        for a in batch:
            x = result.get(a["id"])
            if not x or not x.get("opis"):
                continue
            kat = x.get("kategoria")
            opisy[a["id"]] = {
                "haslo": (x.get("haslo") or "").strip()[:90],
                "opis": (x.get("opis") or "").strip()[:500],
                "kategoria": kat if kat in CATEGORIES else fallback_category(a),
                "zamiennik": (x.get("zamiennik") or "").strip()[:40],
            }
        log(f"  {min(i + BATCH, len(todo))}/{len(todo)}")
        save_cache(cache)  # zapis po każdej paczce: przerwanie nie gubi pracy
        time.sleep(1.5)

    for a in apps.values():
        o = opisy.get(a["id"])
        if o:
            a.update(o)
        else:
            a.update({"haslo": a["summary"], "opis": a["raw"][:350],
                      "kategoria": fallback_category(a), "zamiennik": ""})


# ---------------------------------------------------------------- zapis

def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    cache = load_cache()
    apps = merge(collect_flathub(cache), collect_fdroid())
    save_cache(cache)
    describe(apps, cache)

    keep = ("id", "name", "icon", "dev", "haslo", "opis", "kategoria", "zamiennik", "license",
            "platforms", "installs", "stars", "added", "updated", "links", "screens", "ranks")
    out = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "categories": CATEGORIES,
        "apps": [{k: a[k] for k in keep} for a in apps.values()],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    save_cache(cache)
    log(f"Gotowe: {len(out['apps'])} apek → docs/{OUT.name}")


if __name__ == "__main__":
    main()

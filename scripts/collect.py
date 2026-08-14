#!/usr/bin/env python3
# =====================================================================
#  AI REGGELI JELENTÉS — napi gyűjtő
#
#  Mit csinál, ha lefut (naponta egyszer, magától):
#    1. Beolvassa a sources.yaml-ból a hírforrásokat.
#    2. Letölti mindegyik RSS-feedet, összeszedi az elmúlt ~30 óra híreit.
#    3. Kiszűri az ismétléseket (ha több lap ugyanarról ír → 1 hír, több forrással).
#    4. Egy AI (Google Gemini) minden hírhez magyar címet + 2-3 mondatos összefoglalót ír,
#       kategóriába sorolja, összeköti a korábbi szálakkal, és megjelöli az ellentmondásokat.
#    5. Elmenti a mai napot: data/ÉÉÉÉ-HH-NN.json
#    6. Frissíti a data/index.json-t (napok listája, szálak, statisztika).
#
#  Ha nincs API-kulcs beállítva, a program akkor is lefut, csak "buta" módban
#  (nyers címekkel, AI-összefoglaló nélkül) — így a rendszer sosem törik el.
# =====================================================================

import os, re, sys, json, html, hashlib, datetime as dt
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import yaml
import feedparser

TZ = ZoneInfo("Europe/Budapest")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")
VALID_CATS = {"modell", "termek", "szabalyozas", "howto"}


# ---------------------------------------------------------------------
# Segédfüggvények
# ---------------------------------------------------------------------
def log(msg):
    print(f"[collect] {msg}", flush=True)

def strip_html(text):
    """HTML-címkék és felesleges szóközök eltávolítása egy kivonatból."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def norm_title(t):
    """Cím egyszerűsítése az ismétlés-kereséshez (kisbetű, ékezet/írásjel nélkül)."""
    t = t.lower()
    t = re.sub(r"[^a-z0-9áéíóöőúüű ]", "", t)
    return re.sub(r"\s+", " ", t).strip()

def entry_time(entry):
    """A hír megjelenési ideje; ha hiányzik, a mostani idő."""
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            return dt.datetime(*val[:6], tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)

def make_id(url, title):
    base = (url or title or "").encode("utf-8")
    return hashlib.sha1(base).hexdigest()[:12]


# ---------------------------------------------------------------------
# 1–2. lépés: feedek letöltése, friss hírek összegyűjtése
# ---------------------------------------------------------------------
def collect_raw(cfg):
    lookback = cfg["settings"]["lookback_hours"]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=lookback)
    raw = []
    for src in cfg["sources"]:
        try:
            feed = feedparser.parse(src["url"])
            if feed.bozo and not feed.entries:
                log(f"KIHAGYVA (nem elérhető): {src['name']}")
                continue
            count = 0
            for e in feed.entries:
                when = entry_time(e)
                if when < cutoff:
                    continue
                title = strip_html(e.get("title", "")).strip()
                link = e.get("link", "")
                if not title or not link:
                    continue
                snippet = strip_html(e.get("summary", e.get("description", "")))[:600]
                raw.append({
                    "title": title, "url": link, "snippet": snippet,
                    "source": src["name"], "hint": src.get("hint", "termek"),
                    "when": when,
                })
                count += 1
            log(f"OK: {src['name']} — {count} friss hír")
        except Exception as ex:
            log(f"HIBA {src['name']}: {ex}")
    return raw


# ---------------------------------------------------------------------
# 3. lépés: ismétlések kiszűrése (több lap → egy hír, több forrással)
# ---------------------------------------------------------------------
def dedup(raw):
    stories = []
    for item in sorted(raw, key=lambda x: x["when"], reverse=True):
        nt = norm_title(item["title"])
        match = None
        for s in stories:
            if SequenceMatcher(None, nt, s["_nt"]).ratio() > 0.72:
                match = s
                break
        if match:
            # már megvan a téma — csak új forrásként adjuk hozzá
            if item["source"] not in [x["name"] for x in match["sources"]]:
                match["sources"].append({"name": item["source"], "url": item["url"]})
            match["source_count"] += 1
        else:
            stories.append({
                "_nt": nt,
                "title": item["title"],
                "snippet": item["snippet"],
                "hint": item["hint"],
                "when": item["when"],
                "sources": [{"name": item["source"], "url": item["url"]}],
                "source_count": 1,
            })
    return stories


# ---------------------------------------------------------------------
# Korábbi hírek betöltése (szál- és ellentmondás-kontextushoz)
# ---------------------------------------------------------------------
def load_recent(context_days):
    if not os.path.exists(os.path.join(DATA_DIR, "index.json")):
        return [], {}
    with open(os.path.join(DATA_DIR, "index.json"), encoding="utf-8") as f:
        idx = json.load(f)
    cutoff = (dt.datetime.now(TZ) - dt.timedelta(days=context_days)).date().isoformat()
    recent = []
    for day in idx.get("days", []):
        if day < cutoff:
            continue
        p = os.path.join(DATA_DIR, f"{day}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                recent += json.load(f).get("articles", [])
    return recent, idx.get("threads", {})


# ---------------------------------------------------------------------
# 4. lépés: AI-feldolgozás (magyar összefoglaló, kategória, szál, ellentmondás)
# ---------------------------------------------------------------------
def enrich_with_ai(stories, recent, threads):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log("FIGYELEM: nincs GEMINI_API_KEY — 'buta' mód (nincs AI-összefoglaló).")
        return dumb_enrich(stories)

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)

    # Kontextus: korábbi szálak (kulcs + cím) + mai címek listája a kereszt-hivatkozáshoz
    thread_ctx = "\n".join(
        f'- kulcs="{k}": {v.get("title","")}' for k, v in list(threads.items())[:40]
    ) or "(még nincs korábbi szál)"
    recent_ctx = "\n".join(
        f'- {a.get("title","")}' for a in recent[:40]
    ) or "(nincs korábbi hír)"

    system = (
        "Te egy magyar nyelvű AI-hírszerkesztő vagy. Feladatod, hogy nyers hírekből "
        "tömör, pontos magyar összefoglalót készíts szakembereknek. Mindig kizárólag "
        "érvényes JSON-nal válaszolj, magyarázat és ```jelölés nélkül."
    )

    results = []
    BATCH = 10
    for i in range(0, len(stories), BATCH):
        batch = stories[i:i + BATCH]
        items_txt = ""
        for j, s in enumerate(batch):
            srcs = ", ".join(x["name"] for x in s["sources"])
            items_txt += (
                f'\n[{j}] CÍM: {s["title"]}\n'
                f'    KIVONAT: {s["snippet"][:400]}\n'
                f'    FORRÁSOK: {srcs}\n'
            )
        prompt = f"""Korábbi szálak (ezek kulcsait használd újra, ha egy hír ezek folytatása):
{thread_ctx}

Korábbi hírek (utóbbi napokból, ellentmondás-ellenőrzéshez):
{recent_ctx}

Mai feldolgozandó hírek:
{items_txt}

Minden hírhez adj vissza EGY objektumot ebben a sorrendben, JSON tömbként.
Mezők:
- "hu_title": rövid, informatív MAGYAR cím
- "hu_summary": 2-3 mondatos MAGYAR összefoglaló, tényszerű, felesleges jelzők nélkül
- "category": pontosan egy: "modell" (új modell/kutatás), "termek" (termék/cég/üzlet),
  "szabalyozas" (szabályozás/jog/biztonság) vagy "howto" (eszköz/gyakorlati útmutató)
- "thread_key": ha a hír egy folyamatban lévő téma része, adj egy rövid angol slug-kulcsot
  (pl. "openai-gpt52"); használd újra a fenti korábbi kulcsot, ha illik. Ha önálló hír: null
- "contradiction": null, VAGY {{"note":"rövid magyar leírás","sides":[
    {{"claim":"magyar állítás","source":"forrás neve"}},
    {{"claim":"ütköző magyar állítás","source":"forrás neve"}}]}}
  — csak akkor, ha valóban ellentmondó tényállítás van a források közt vagy a korábbi hírekkel.

Csak a JSON tömböt add vissza, {len(batch)} elemmel."""

        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=4000,
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
            text = (resp.text or "").strip()
            text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
            parsed = json.loads(text)
            if isinstance(parsed, dict):            # ha objektumba csomagolta a tömböt
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break
            if len(parsed) != len(batch):
                raise ValueError("elemszám-eltérés")
            results += parsed
            log(f"AI feldolgozás: {i+len(batch)}/{len(stories)} kész")
        except Exception as ex:
            log(f"AI HIBA a(z) {i}. kötegnél ({ex}) — buta mód erre a kötegre")
            results += dumb_enrich(batch)
    return results

def dumb_enrich(stories):
    """Tartalék, ha nincs AI: a nyers cím és kivonat kerül be, alap kategóriával."""
    out = []
    for s in stories:
        out.append({
            "hu_title": s["title"],
            "hu_summary": s["snippet"][:280] or "(nincs összefoglaló)",
            "category": s["hint"] if s["hint"] in VALID_CATS else "termek",
            "thread_key": None,
            "contradiction": None,
        })
    return out


# ---------------------------------------------------------------------
# 5–6. lépés: mai fájl mentése + index újraépítése
# ---------------------------------------------------------------------
def build_articles(stories, enriched):
    articles = []
    for s, e in zip(stories, enriched):
        cat = e.get("category")
        if cat not in VALID_CATS:
            cat = "termek"
        articles.append({
            "id": make_id(s["sources"][0]["url"], s["title"]),
            "category": cat,
            "time": s["when"].astimezone(TZ).strftime("%H:%M"),
            "title": e.get("hu_title") or s["title"],
            "summary": e.get("hu_summary") or s["snippet"][:280],
            "sources": s["sources"][:3],
            "sourceCount": s["source_count"],
            "threadId": e.get("thread_key"),
            "contradiction": e.get("contradiction"),
        })
    return articles

def rebuild_index(today, context_days):
    """Végigmegy a mentett napokon, felépíti a napok listáját és a szálakat."""
    days = sorted(
        f[:-5] for f in os.listdir(DATA_DIR)
        if re.match(r"\d{4}-\d{2}-\d{2}\.json$", f)
    )
    # Szálak: azonos thread_key-jű hírek csoportja, ha legalább 2 hír tartozik hozzá
    window_start = (dt.datetime.now(TZ) - dt.timedelta(days=180)).date().isoformat()
    groups = {}
    for day in days:
        if day < window_start:
            continue
        with open(os.path.join(DATA_DIR, f"{day}.json"), encoding="utf-8") as f:
            for a in json.load(f).get("articles", []):
                k = a.get("threadId")
                if k:
                    groups.setdefault(k, []).append((day, a))
    threads = {}
    for k, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda x: x[0])          # legrégebbi elöl → cím onnan
        threads[k] = {
            "title": items[0][1]["title"],
            "articleIds": [a["id"] for _, a in items],
        }
    idx = {
        "generatedAt": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "days": sorted(days, reverse=True),
        "threads": threads,
    }
    with open(os.path.join(DATA_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    log(f"index.json frissítve — {len(days)} nap, {len(threads)} aktív szál")


# ---------------------------------------------------------------------
# Fő futás
# ---------------------------------------------------------------------
def main():
    with open(os.path.join(ROOT, "sources.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    os.makedirs(DATA_DIR, exist_ok=True)

    today = dt.datetime.now(TZ).date().isoformat()
    log(f"Nap: {today} — források: {len(cfg['sources'])}")

    raw = collect_raw(cfg)
    log(f"Összes friss hír (nyers): {len(raw)}")
    stories = dedup(raw)
    log(f"Ismétlésszűrés után: {len(stories)} egyedi hír")

    stories = stories[: cfg["settings"]["max_stories_per_day"]]
    if not stories:
        log("Ma nincs friss hír. Kilépés.")
        return

    recent, threads = load_recent(cfg["settings"]["context_days"])
    enriched = enrich_with_ai(stories, recent, threads)
    articles = build_articles(stories, enriched)

    with open(os.path.join(DATA_DIR, f"{today}.json"), "w", encoding="utf-8") as f:
        json.dump({"date": today, "articles": articles}, f, ensure_ascii=False, indent=2)
    log(f"Mentve: data/{today}.json — {len(articles)} hír")

    rebuild_index(today, cfg["settings"]["context_days"])
    log("Kész.")

if __name__ == "__main__":
    main()

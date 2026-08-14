# AI Reggeli Jelentés

Napi, automatikusan frissülő AI-hírfelület. Minden reggel összegyűjti a világ AI-híreit,
magyar összefoglalót ír hozzájuk, kiszűri az ismétléseket, összeköti a témaszálakat és
megjelöli az ellentmondásokat. A gép dolgozik helyetted — te csak megnyitod a linket.

---

## Mi mihez kell? (a 3 szereplő)

1. **GitHub** – itt „lakik" a projekt, és itt fut minden reggel a gyűjtő (ingyenes).
2. **GitHub Pages** – ez mutatja a kész weboldalt egy linken (ingyenes).
3. **Google Gemini ingyenes API-kulcs** – ez az „AI-agy", ami az összefoglalókat írja
   (állandó ingyenes szint, bankkártya nélkül – **0 Ft**).

---

## Telepítés – első alkalommal (kb. 15 perc)

### 1. Hozz létre egy tárolót (repository) a GitHubon
- Lépj be a github.com-ra (ha nincs fiók, regisztrálj – ingyenes).
- Jobb fent **+ → New repository**.
- Név: pl. `ai-hirjelentes`. Állítsd **Public**-ra. Kattints **Create repository**.

### 2. Töltsd fel a projekt fájljait
- A tároló oldalán: **Add file → Upload files**.
- Húzd be **ennek a mappának a teljes tartalmát** (index.html, README.md, requirements.txt,
  sources.yaml, valamint a `scripts`, `data` és `.github` mappák).
- Alul **Commit changes**.

> Fontos, hogy a `.github/workflows/daily.yml` útvonal megmaradjon – ez indítja a napi futást.

### 3. Add meg a Google Gemini API-kulcsot (biztonságosan)
- Szerezz kulcsot: **aistudio.google.com** → jelentkezz be Google-fiókkal →
  **Get API key → Create API key**. Másold ki. (Nincs bankkártya, nincs számlázás.)
- A GitHub-tárolóban: **Settings → Secrets and variables → Actions → New repository secret**.
- Név: `GEMINI_API_KEY` (pontosan így). Érték: a kimásolt kulcs. **Add secret**.

> A kulcs titkosítva tárolódik, a kódban sehol nem jelenik meg.

### 4. Kapcsold be a weboldalt (GitHub Pages)
- **Settings → Pages**.
- **Source**: „Deploy from a branch". **Branch**: `main`, mappa: `/ (root)`. **Save**.
- Egy perc múlva megjelenik a linked, kb. ilyen:
  `https://<felhasználóneved>.github.io/ai-hirjelentes/`
- Nyisd meg – a kezdő-hírekkel már működik. Telefonon tedd a kezdőképernyőre.

### 5. Indítsd el az első éles gyűjtést
- **Actions** fül → bal oldalt **„Napi AI hírgyűjtés"** → jobbra **Run workflow → Run workflow**.
- 1-2 perc múlva a `data/` mappa feltöltődik friss hírekkel, az oldal magától frissül.

**Kész.** Innentől minden reggel (~06:00) magától lefut, és az oldalad friss lesz.

---

## Napi működés

Nincs teendőd. Minden reggel a GitHub:
1. lefuttatja a gyűjtőt (`scripts/collect.py`),
2. az legyártja a mai `data/ÉÉÉÉ-HH-NN.json` fájlt és frissíti a `data/index.json`-t,
3. visszaírja a tárolóba, a Pages pedig automatikusan újratölti az oldalt.

Bármikor indíthatsz kézi futást is: **Actions → Napi AI hírgyűjtés → Run workflow**.

---

## Testreszabás

**Források hozzáadása/elvétele:** nyisd meg a `sources.yaml`-t (Edit ceruza ikon a GitHubon),
másolj le egy blokkot és írd át. Egy forrás kikapcsolása: tegyél `# ` jelet a sorai elé.

**Beállítások** (szintén `sources.yaml`, alul):
- `lookback_hours` – hány órára visszamenőleg gyűjtsön (alap: 30),
- `max_stories_per_day` – napi maximum hírszám (költség-korlát, alap: 40),
- `context_days` – hány napra nézzen vissza szálakhoz/ellentmondásokhoz (alap: 21).

**Modellváltás:** alapból a `gemini-2.5-flash` fut (ingyenes). Ha több hírt dolgoznál fel
naponta, a `gemini-2.5-flash-lite` nagyobb ingyenes keretet ad. A `.github/workflows/daily.yml`
gyűjtés-lépéséhez add hozzá pl. `MODEL: gemini-2.5-flash-lite` környezeti változót.

---

## Költség

**0 Ft.** A Gemini ingyenes szintje bankkártya nélkül elég erre a célra (a rendszer naponta
csak néhány kérést használ, a napi ingyenes keret ennek a sokszorosa). A GitHub és a Pages
szintén ingyenes.

> Adatvédelem: az ingyenes Gemini-szinten a Google felhasználhatja a beküldött szöveget a
> modelljei fejlesztéséhez. Nyilvános hírek feldolgozásánál ez rendben van; ha ez zavaró,
> a Gemini fizetős szintje vagy a Claude-verzió nem használja a tartalmat tanításra.

---

## Ha valami nem stimmel

- **Üres az oldal / régi hírek:** futtass egy kézi gyűjtést (Actions → Run workflow),
  és nézd meg a futás naplóját – ott látszik forrásonként, mi sikerült.
- **Egy forrás mindig „KIHAGYVA":** valószínűleg megváltozott az RSS-címe.
  Keresd meg a helyeset, és írd át a `sources.yaml`-ban.
- **Nincs AI-összefoglaló (nyers címek):** hiányzik vagy hibás a `GEMINI_API_KEY`
  secret, vagy aznap kimerült az ingyenes napi keret (429-es hiba a naplóban) –
  másnap magától rendeződik.
- **Hetek óta nem frissül magától:** a GitHub 60 nap inaktivitás után szünetelteti az
  ütemezett futásokat – egy kézi indítás vagy egy apró módosítás újraaktiválja.

Az AI-összefoglalók tájékoztató jellegűek – fontos döntés előtt nézd meg az eredeti forrást
(minden hírnél ott a közvetlen link).

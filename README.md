# Event-App Essen

Eine mobil optimierte Web-App, die rund um **Essen Werden** zeigt, was heute, morgen
und am Wochenende los ist — aus 19 lokalen Quellen, automatisch zusammengetragen.

Die App läuft komplett **ohne eigenen Server**: Ein GitHub-Actions-Job crawlt 2×/Tag
alle Quellen, schreibt einen statischen Daten-Snapshot ins Repo und veröffentlicht das
Frontend auf **GitHub Pages**. Alle Filter, Sortierung und die „heute/morgen/Wochenende"-
Logik laufen im Browser. Favoriten werden pro Gerät lokal gespeichert.

## Auf dem Handy nutzen

1. Öffne die Seite im Browser:
   **`https://<dein-github-name>.github.io/Event-App/`**
   (die genaue Adresse erscheint, sobald GitHub Pages aktiviert ist — siehe unten).
2. **iPhone/iPad (Safari):** Teilen-Symbol → **„Zum Home-Bildschirm"**.
   **Android (Chrome):** Menü → **„App installieren" / „Zum Startbildschirm"**.
3. Die App startet danach wie eine normale App im Vollbild.

Es gibt keine Anmeldung, kein Tracking und keine Werbung. Hinweise zu den genutzten
Drittanbietern stehen unter **„Datenschutz"** in der Fußzeile der App.

## Wie es funktioniert

```
GitHub Actions (2×/Tag)
  └─ backend/ als Library: alle Quellen crawlen  →  events.json + weather.json
       └─ commit nach frontend/public/data/
            └─ Next.js Static-Export (output: export)  →  GitHub Pages
                 └─ Browser lädt die JSON und filtert/sortiert clientseitig
```

Bei jedem Lauf startet GitHub Actions eine frische Ubuntu-VM, auf der das volle
Programm abläuft:

1. **PostgreSQL** startet als Container — eine leere Datenbank, die nur für diesen Lauf lebt
2. Das **Backend** wird installiert, inklusive Chromium für die Playwright-Quellen
3. Die **komplette Crawl-Pipeline** läuft: alle 19 Quellen, Geocoding, Wetter,
   Dubletten-Erkennung, Quality-Scores
4. Das Ergebnis wird als `events.json` + `weather.json` **ins Repo committet**
5. **Next.js** baut daraus die statischen Seiten (eine pro Event)
6. Das Ganze wird auf **GitHub Pages deployt** — danach wird die VM verworfen

Deshalb braucht es keinen Server: Die Datenbank existiert nur für ein paar Minuten
während des Crawls, das Endprodukt ist reines statisches HTML + JSON. Für öffentliche
Repositories ist das alles kostenlos.

- **Daten max. 12 h alt.** Vergangene Termine blendet der Browser anhand der Geräte-Uhr aus.
- **Ein zentraler Crawl** bedient alle Besucher — rechtlich schonender als viele Einzel-Clients.

## Selbst betreiben / forken

Diese App ist als persönliches, teilbares Projekt gedacht. Für einen eigenen Betrieb:

1. **Repo forken.**
2. In den Repo-Einstellungen: **Settings → Pages → Source = „GitHub Actions"**.
3. **Secret anlegen:** `NOMINATIM_CONTACT` (eine Kontakt-E-Mail; verlangt die Nominatim-
   Nutzungsrichtlinie für Geocoding-Anfragen).
4. Workflow **`Crawl & Deploy`** unter „Actions" einmal manuell starten (`Run workflow`),
   danach läuft er per Cron.

Der Build setzt `NEXT_PUBLIC_BASE_PATH` automatisch auf `/<repo-name>` (Projekt-Pages-
Subpath). Liegt die App unter einer eigenen Domain im Root, diese Variable leeren.

### Auf eine andere Stadt anpassen

- **Startpunkt** (für Entfernung/Fahrzeit): `ESSEN_WERDEN_LAT` / `ESSEN_WERDEN_LON` in
  `backend/app/services/distance.py`.
- **Quellen:** `backend/app/services/sources_registry.py` — eine Quelle = ein Eintrag.

## Lokale Entwicklung

```bash
# DB starten
docker-compose up -d db

# Backend-Abhängigkeiten installieren
cd backend
pip install -r requirements.txt
# Playwright-Browser (nur nötig für 6 der 19 Quellen-Crawler)
python -m playwright install chromium

# Snapshot erzeugen (gegen die laufende DB; --no-sync exportiert den DB-Stand as-is)
python -m app.scripts.export_snapshot            # crawlt + exportiert
python -m app.scripts.export_snapshot --no-sync  # nur exportieren

# Frontend (nutzt die committete events.json, kein Backend nötig)
cd frontend
npm install
npm run dev        # http://localhost:3000
npm run build      # statischer Export nach out/

# Backend-Tests
cd backend
python -m pytest tests/ -v
```

Schnellstart für die klassische Server-Variante (Parser-Entwicklung): `start.bat`
(Windows) bzw. `start.sh` (Linux/Mac) im Projektroot.

## Lizenz

[MIT](LICENSE)

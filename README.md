# JOLIA Docs

**Turn Documents, Photos and Scans into Knowledge.** – vollständig lokal, ohne Cloud, ohne Docker-Zwang, ohne GPU.

---

## Funktionen

- 📥 **Inbox-Import**: Automatisches Einlesen aus einem konfigurierbaren Ordner (lokal oder NAS)
- � **Mehrseitige Scans**: Kamera-Aufnahmen werden zu **einem PDF mit durchsuchbarem Text** zusammengefasst
- �🗂️ **Archivierung**: Strukturierte Ablage in `source_documents/` mit Datum und Typ
- 🤖 **KI-Analyse**: Extraktion von Text, Metadaten, OCR-Text und Transkripten je nach Dateiformat
- 🔍 **Semantische Suche**: Natürlichsprachige Suche über alle Inhalte via ChromaDB
- 💬 **RAG-Chat**: Fragen stellen und Antworten mit Quellenangaben erhalten (via Ollama)
- 💾 **Backup**: Inkrementelles Backup auf externe Festplatte
- 🔄 **Reindex**: Vollständiger Wiederaufbau des Index aus den Originaldateien

---

## Unterstützte Formate

| Kategorie | Formate |
|-----------|---------|
| Dokumente | PDF, TXT, MD, DOCX, XLSX, PPTX |
| Bilder / Fotos | JPG, PNG, HEIC, TIFF, WebP |
| Audio / Musik | MP3, M4A, WAV, FLAC, OGG |
| Video | MP4, MKV, AVI, MOV, WebM |

---

## Schnellstart (Windows Entwicklung)

```powershell
# 1. Repository klonen / Ordner öffnen
# 2. Voraussetzungen:
#    - Python 3.11+
#    - Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
#    - Ollama: https://ollama.com → ollama pull qwen2.5:3b

# 3. App starten
.\scripts\run_dev_windows.ps1
```

Dann im Browser öffnen: **http://127.0.0.1:8080**

---

## Schnellstart Docker (Linux / macOS)

```bash
git clone <repo-url> jolia
cd jolia
docker compose up -d --build
```

Danach: **http://localhost:8080** öffnen, Dateien in `jolia/inbox` (im
Projektordner) ablegen. Docker installieren, falls nicht vorhanden:
`curl -fsSL https://get.docker.com | sh`

Für Windows 11 gibt es die ausführliche Anleitung im nächsten Abschnitt.

---

## Schnellstart Windows 11 via WSL2 (ein Skript, ohne Docker Desktop)

Für eine komplett automatische Installation auf einem neuen Windows-11-Rechner,
die sich auch wieder rückstandsfrei entfernen lässt:

```powershell
.\scripts\WSL_startup.ps1
```

Das Skript legt eine eigene, isolierte WSL2-Distro `jolia-wsl` an, installiert
darin Docker Engine (kein Docker Desktop), klont JOLIA und startet es per
`docker compose`. Anschließend startet JOLIA bei jedem Windows-Login
automatisch neu. Falls WSL2 auf dem Rechner noch nicht aktiviert war, bricht
das Skript einmalig mit dem Hinweis ab, den Rechner neu zu starten und es
danach erneut auszuführen.

Rückstandsfreie Deinstallation (entfernt Distro, Docker-Daten, Autostart-Task
und Installationsordner vollständig):

```powershell
.\scripts\WSL_uninstall.ps1
```

Für Docker Desktop unter Windows 11 gibt es die ausführliche Anleitung im
nächsten Abschnitt.

---

# 🐳 Docker Desktop unter Windows 11 – Schritt-für-Schritt-Anleitung

Diese Anleitung ist für Einsteiger gedacht und setzt **keine** Docker-Kenntnisse
voraus. Alle Befehle werden in **Windows PowerShell** eingegeben
(Start-Menü → „PowerShell“ eintippen → Enter).

## 0. Was am Ende läuft

Nach dem Setup laufen drei Container:

| Container | Aufgabe |
|-----------|---------|
| `jolia-app` | Die Anwendung + Weboberfläche auf Port 8080 |
| `jolia-ollama` | Lokaler KI-Sprachmodell-Server (Chat, Zusammenfassungen) |
| `jolia-ollama-init` | Einmaliger Hilfs-Job, der das Sprachmodell herunterlädt. Beendet sich danach von selbst – das ist **kein Fehler**. |

Es gibt **keine Cloud-Verbindung**: Alle Daten bleiben auf dem eigenen Rechner.
Internet wird nur beim ersten Start für die Downloads benötigt.

## 1. Voraussetzungen prüfen

| Anforderung | Empfehlung |
|-------------|------------|
| Windows | Windows 11 (64-Bit), aktuelle Updates installiert |
| Arbeitsspeicher | mindestens 8 GB, **empfohlen 16 GB** |
| Freier Festplattenplatz | **mindestens 30 GB** (Image ≈ 8–12 GB, Sprachmodell ≈ 2 GB, plus eigene Dateien) |
| Virtualisierung | Im BIOS/UEFI aktiviert (Intel „VT-x“ / AMD „SVM“) |
| Internet | Für den einmaligen ersten Build nötig |

**Virtualisierung prüfen:** Task-Manager öffnen (`Strg`+`Umschalt`+`Esc`) →
Reiter *Leistung* → *CPU*. Dort muss „Virtualisierung: Aktiviert“ stehen.
Steht dort „Deaktiviert“, siehe [Problem 4](#häufige-probleme-und-ihre-lösung).

## 2. WSL 2 installieren (Unterbau von Docker unter Windows)

PowerShell **als Administrator** öffnen (Rechtsklick auf „Windows PowerShell“ →
*Als Administrator ausführen*) und eingeben:

```powershell
wsl --install
```

Danach **Rechner neu starten**. Nach dem Neustart noch einmal:

```powershell
wsl --update
wsl --status
```

> Wenn `wsl --install` meldet, dass WSL bereits installiert ist, ist alles in
> Ordnung – einfach mit Schritt 3 weitermachen.

## 3. Docker Desktop installieren

1. Herunterladen: <https://www.docker.com/products/docker-desktop/> →
   *Download for Windows (AMD64)* (bzw. ARM64 bei Snapdragon-Geräten).
2. `Docker Desktop Installer.exe` ausführen.
3. Im Installationsdialog **„Use WSL 2 instead of Hyper-V“ angehakt lassen**.
4. Nach der Installation abmelden/neu starten, wenn dazu aufgefordert wird.
5. Docker Desktop starten, die Lizenzbedingungen akzeptieren.
   Die Anmeldung mit einem Docker-Konto kann übersprungen werden
   („Continue without signing in“).
6. Warten, bis unten links im Docker-Desktop-Fenster **„Engine running“** grün
   angezeigt wird. Das kann beim ersten Mal 1–2 Minuten dauern.

**Kontrolle** in einer *normalen* (nicht-administrativen) PowerShell:

```powershell
docker version
docker compose version
```

Beide Befehle müssen Versionsnummern ausgeben. Falls nicht → siehe
[Problem 1 und 2](#häufige-probleme-und-ihre-lösung).

## 4. Projektordner öffnen

```powershell
cd "D:\tools\JOLIA docs"
```

> Der Pfad darf Leerzeichen enthalten – dann muss er, wie oben, in
> Anführungszeichen stehen.

## 5. JOLIA Docs starten

```powershell
docker compose up -d --build
```

Dieser eine Befehl erledigt alles:

1. baut das Anwendungs-Image (Python, OCR/Tesseract, ffmpeg, PyTorch-CPU,
   Whisper, CLIP, Gesichtserkennung),
2. startet den Ollama-Server und lädt das Sprachmodell `qwen2.5:3b` (≈ 2 GB),
3. startet die Anwendung auf Port 8080.

> ⏳ **Der erste Start dauert lange – typischerweise 20 bis 60 Minuten.**
> Vor allem das Kompilieren von `dlib` (Gesichtserkennung) und der Download von
> PyTorch/CLIP brauchen Zeit. Das Fenster **nicht** schließen. Jeder weitere
> Start dauert nur noch wenige Sekunden.

Fortschritt und Status prüfen:

```powershell
docker compose ps          # laufende Container
docker compose logs -f app # Live-Logs der Anwendung (beenden mit Strg+C)
```

Die Anwendung ist bereit, wenn in den Logs steht:
`JOLIA Docs läuft auf 0.0.0.0:8080`.

## 6. Weboberfläche öffnen

<http://localhost:8080>

## 7. Dateien einlesen

Im Projektordner ist automatisch dieser Ordner entstanden:

```
D:\tools\JOLIA docs\jolia\
    inbox\               ← hier Dateien hineinkopieren (werden automatisch importiert)
    source_documents\    ← das fertige Archiv (Originaldateien, unveränderlich)
    backup\              ← Ziel des automatischen täglichen Backups
```

Einfach Dokumente, Fotos, Audio- oder Videodateien nach `jolia\inbox` kopieren.

> Der Import läuft **zeitgesteuert**: Der Ordner wird alle 60 Sekunden geprüft,
> und eine Datei wird erst importiert, wenn sie 30 Sekunden lang unverändert ist
> (damit keine halb kopierten Dateien verarbeitet werden). Nach dem Kopieren also
> ca. 1–2 Minuten Geduld haben. Alternativ funktioniert der Upload-Button in der
> Weboberfläche sofort.

## 8. Eigene Ordner verwenden (optional)

Wer seine Dateien nicht im Projektordner liegen haben möchte, legt eine Datei
namens `.env` **neben** der `docker-compose.yml` an (z. B. mit dem Editor):

```ini
JOLIA_INBOX=C:\Users\Max\Documents\JOLIA-Inbox
JOLIA_ARCHIVE=D:\JOLIA\source_documents
JOLIA_BACKUP=E:\JOLIA-Backup
JOLIA_PORT=8080
```

Danach `docker compose up -d` erneut ausführen. Alle Einträge sind optional;
nicht gesetzte Werte verwenden die Standardordner unter `jolia\`.

> Windows-Pfade werden hier **ohne** Anführungszeichen geschrieben.
> Ordner auf externen/USB-Laufwerken sollten dauerhaft angeschlossen sein.

## 9. Wo liegen die Daten?

| Was | Wo | Sicherung nötig? |
|-----|----|------------------|
| Originaldateien (Archiv) | Host-Ordner `jolia\source_documents` | **Ja** – das ist die Quelle der Wahrheit |
| Metadaten-Sidecars (`.json`/`.md`) | direkt neben den Originaldateien | ja (liegen im selben Ordner) |
| Suchindex (SQLite + ChromaDB) | Docker-Volume `jolia-docs_jolia-store` | nein – jederzeit per *Reindex* neu erzeugbar |
| Heruntergeladene KI-Modelle | Docker-Volumes `jolia-docs_jolia-cache`, `jolia-docs_ollama-models` | nein – werden bei Bedarf neu geladen |

Der Suchindex liegt bewusst in einem Docker-Volume statt in einem
Windows-Ordner: SQLite ist auf Windows-Bind-Mounts deutlich langsamer und kann
zu „database is locked“-Fehlern führen.

---

## Container stoppen, starten und entfernen

Alle Befehle im Projektordner (`cd "D:\tools\JOLIA docs"`) ausführen.

| Ziel | Befehl |
|------|--------|
| **Anhalten** (Container bleiben bestehen, starten nach Neustart **nicht** von selbst) | `docker compose stop` |
| Wieder starten | `docker compose start` |
| Neu starten | `docker compose restart` |
| **Anhalten und Container entfernen** (Daten & Volumes bleiben erhalten) | `docker compose down` |
| Wieder hochfahren nach `down` | `docker compose up -d` |
| Nach Code-Änderungen neu bauen | `docker compose up -d --build` |
| Nur die App neu starten | `docker restart jolia-app` |
| Logs ansehen | `docker compose logs -f app` |
| Ressourcenverbrauch ansehen | `docker stats` |

**Wichtiger Unterschied:**
`stop` merkt sich, dass Sie die Container bewusst angehalten haben – sie starten
dann auch nach einem Windows-Neustart **nicht** automatisch. Erst ein
`docker compose start` bzw. `docker compose up -d` aktiviert den Autostart wieder.

**Alles restlos löschen** (⚠️ entfernt Suchindex, Sprachmodell und Modell-Caches;
die Originaldateien in `jolia\source_documents` bleiben erhalten):

```powershell
docker compose down -v
```

Zusätzlich das gebaute Image entfernen (gibt mehrere GB frei):

```powershell
docker image rm jolia-docs:latest ollama/ollama:latest
docker system prune -a
```

Alternativ geht alles auch per Maus im **Docker Desktop Dashboard** unter
*Containers* → Projekt `jolia-docs` → Buttons *Stop* / *Start* / *Delete*.

---

## Automatischer Start mit Windows

Damit JOLIA Docs nach dem Anmelden automatisch läuft, müssen **zwei** Dinge
zusammenpassen:

**A) Docker Desktop muss automatisch starten**

Docker Desktop → Zahnrad-Symbol (*Settings*) → *General* →
☑ **„Start Docker Desktop when you sign in to your computer“** → *Apply & restart*.

Optional dort auch ☐ *„Open Docker Dashboard when Docker Desktop starts“*
deaktivieren, damit kein Fenster aufgeht.

**B) Die Container müssen eine Neustart-Regel haben**

Das ist bereits eingerichtet: In der [docker-compose.yml](docker-compose.yml)
steht bei `app` und `ollama` die Regel `restart: unless-stopped`. Sie bedeutet:
Die Container starten automatisch mit der Docker-Engine – **außer** man hat sie
vorher ausdrücklich mit `docker compose stop` angehalten.

Einmalig „scharf schalten“:

```powershell
docker compose up -d
```

Anschließend testen: Windows neu starten, ca. 1–2 Minuten warten (Docker Desktop
braucht etwas), dann <http://localhost:8080> aufrufen.

> Hinweis: Beim automatischen Start läuft der Hilfs-Container
> `jolia-ollama-init` nicht erneut – das ist korrekt, das Sprachmodell ist ja
> bereits heruntergeladen.

### Autostart wieder abschalten

Je nachdem, wie gründlich es sein soll:

1. **Nur diesmal nicht starten:**
   ```powershell
   docker compose stop
   ```
   Durch `stop` respektiert `unless-stopped` den Wunsch – die Container bleiben
   auch nach dem nächsten Windows-Start aus.

2. **Neustart-Regel dauerhaft entfernen** (Container laufen weiter, starten aber
   nie mehr von selbst):
   ```powershell
   docker update --restart=no jolia-app jolia-ollama
   ```
   Dauerhaft in der Konfiguration: in [docker-compose.yml](docker-compose.yml)
   bei beiden Diensten `restart: unless-stopped` durch `restart: "no"` ersetzen
   und `docker compose up -d` ausführen.

3. **Docker Desktop selbst nicht mehr automatisch starten:**
   Docker Desktop → *Settings* → *General* →
   ☐ „Start Docker Desktop when you sign in to your computer“.
   Zusätzlich im Task-Manager → Reiter *Autostart-Apps* → Eintrag
   **„Docker Desktop“** → Rechtsklick → *Deaktivieren*.

Danach startet JOLIA Docs nur noch manuell:
Docker Desktop starten → PowerShell → `cd "D:\tools\JOLIA docs"` →
`docker compose up -d`.

---

## Häufige Probleme und ihre Lösung

**1. `docker : Die Benennung "docker" wurde nicht als Name eines Cmdlet … erkannt`**
Docker Desktop ist nicht installiert oder die PowerShell wurde vor der
Installation geöffnet. PowerShell-Fenster schließen und neu öffnen; wenn das
nicht hilft, Docker Desktop erneut installieren und den Rechner neu starten.

**2. `error during connect … open //./pipe/dockerDesktopLinuxEngine: Das System kann die angegebene Datei nicht finden`**
Docker Desktop läuft nicht. Docker Desktop über das Startmenü starten und warten,
bis unten links **„Engine running“** grün ist. Erst dann die Befehle ausführen.

**3. „WSL 2 installation is incomplete“ / „WSL kernel version too low“**
```powershell
wsl --update
wsl --shutdown
```
Danach Docker Desktop neu starten. Falls das nicht hilft: Rechner neu starten.

**4. „Hardware assisted virtualization … is not enabled“**
Virtualisierung ist im BIOS/UEFI abgeschaltet. Rechner neu starten, beim
Hochfahren ins BIOS/UEFI (meist `Entf`, `F2` oder `F10`), dort *Intel VT-x* /
*Intel Virtualization Technology* bzw. *AMD SVM Mode* aktivieren, speichern.
Zusätzlich müssen in Windows die Features *Plattform für virtuelle Computer* und
*Windows-Subsystem für Linux* aktiv sein
(*Systemsteuerung → Programme → Windows-Features aktivieren oder deaktivieren*).

**5. `Bind for 0.0.0.0:8080 failed: port is already allocated` / „Ports are not available“**
Ein anderes Programm belegt Port 8080. Verursacher finden:
```powershell
netstat -ano | findstr :8080
```
Einfachste Lösung: anderen Port verwenden. Datei `.env` neben der
`docker-compose.yml` anlegen mit `JOLIA_PORT=8081`, dann
`docker compose up -d`. Die Oberfläche ist danach unter
<http://localhost:8081> erreichbar.

**6. Build bricht mit Netzwerkfehlern ab (`Could not fetch URL`, `timeout`, `TLS handshake`)**
Meist Firmen-Proxy, VPN oder Virenscanner. Proxy in Docker Desktop eintragen:
*Settings → Resources → Proxies*. VPN testweise trennen. Danach neu bauen:
```powershell
docker compose build --no-cache
docker compose up -d
```

**7. Build bricht beim Kompilieren von `dlib` ab / Container wird „Killed“ (Exit-Code 137)**
Zu wenig Arbeitsspeicher für die Docker-VM. In Docker Desktop unter
*Settings → Resources* den Speicher auf mindestens **6 GB** erhöhen.
Bei WSL 2 wird das über die Datei `C:\Users\<Benutzername>\.wslconfig` gesteuert:
```ini
[wsl2]
memory=8GB
processors=4
```
Danach `wsl --shutdown` ausführen und Docker Desktop neu starten.

**8. `no space left on device`**
Festplatte voll. Aufräumen mit:
```powershell
docker system prune -a
```
Oder den Speicherort verlegen: *Settings → Resources → Advanced →
„Disk image location“* auf ein Laufwerk mit mehr Platz setzen.

**9. Die Weboberfläche zeigt „Seite nicht erreichbar“**
Prüfen, ob der Container wirklich läuft:
```powershell
docker compose ps
docker compose logs --tail 50 app
```
Steht bei `jolia-app` *Exited* oder *Restarting*, geben die Logs den Grund an.
Direkt nach dem Start kann es zudem 30–60 Sekunden dauern, bis die App bereit ist.
Immer `http://localhost:8080` verwenden – nicht `https://`.

**10. Dateien aus dem Inbox-Ordner werden nicht importiert**
- 1–2 Minuten warten (Prüfintervall 60 s + 30 s Stabilitätsprüfung).
- Sicherstellen, dass es der **richtige** Ordner ist: der `jolia\inbox` neben der
  `docker-compose.yml`, bzw. der in `.env` gesetzte Pfad. Kontrolle:
  ```powershell
  docker exec jolia-app ls /data/inbox
  ```
  Wird hier nichts gelistet, zeigt der Mount woanders hin.
- Sehr große Dateien (> 2 GB) werden übersprungen
  (`processing.max_file_size_mb`).

**11. Windows fragt nach „Dateifreigabe“ oder der Ordner bleibt leer**
Bei einer Windows-Sicherheitsabfrage von Docker auf *Zulassen* klicken. Wird
statt WSL 2 der Hyper-V-Backend verwendet, muss das Laufwerk zusätzlich unter
*Settings → Resources → File sharing* freigegeben werden.

**12. Chat-Antworten dauern sehr lange**
Das Sprachmodell läuft auf der CPU. 30–120 Sekunden pro Antwort sind auf einem
normalen Notebook normal. Ein kleineres Modell oder ein höheres Zeitlimit lässt
sich ohne Neubau über die `.env` einstellen – siehe
[Notfall-Schalter](#notfall-schalter-wenn-etwas-klemmt).

**13. `jolia-ollama-init` steht auf „Exited (0)“**
Das ist **korrekt**. Der Container hat seine einzige Aufgabe – das Sprachmodell
herunterladen – erledigt und sich beendet.

**14. Nach einem Windows-Update / Absturz startet nichts mehr**
```powershell
wsl --shutdown
```
Docker Desktop beenden und neu starten, dann `docker compose up -d`.

**15. Der Rechner ist dauerhaft ausgelastet / der Import kommt nicht voran**
Gesichtserkennung und Transkription sind auf der CPU sehr rechenintensiv.
Einzelne Funktionen lassen sich ohne Neubau abschalten – siehe
[Notfall-Schalter](#notfall-schalter-wenn-etwas-klemmt).

---

## Notfall-Schalter (wenn etwas klemmt)

Im Normalfall gibt es **nichts zu konfigurieren** – im Docker-Image sind alle
Funktionen bewusst eingeschaltet. Falls aber eine Funktion Probleme macht, zu
langsam ist oder ein Modell nicht geladen werden kann, lässt sich jede einzelne
abschalten, **ohne das Image neu zu bauen**.

**So geht's – immer nach demselben Muster:**

1. Datei `.env` neben der `docker-compose.yml` anlegen bzw. öffnen
   (Vorlage mit allen Schaltern: [.env.example](.env.example)).
2. Die gewünschte Zeile eintragen, z. B.:
   ```ini
   JOLIA_ENABLE_FACE_DETECTION=false
   ```
3. Übernehmen (dauert Sekunden, **kein** `--build`):
   ```powershell
   docker compose up -d
   ```

Wahrheitswerte dürfen `true`/`false`, `1`/`0`, `yes`/`no` oder `on`/`off` sein.
Ein Tippfehler bricht den Start **nicht** ab – der Wert wird ignoriert und im Log
als Warnung gemeldet (`docker compose logs app`).

### Funktionen abschalten

| Schalter | Schaltet ab | Sinnvoll wenn |
|----------|-------------|---------------|
| `JOLIA_ENABLE_FACE_DETECTION=false` | Gesichtserkennung in Fotos | Import dauert bei vielen Bildern sehr lange, CPU dauerhaft am Anschlag |
| `JOLIA_ENABLE_CLIP_EMBEDDINGS=false` | Bildähnlichkeitssuche | Bildimport hängt oder braucht zu viel Arbeitsspeicher |
| `JOLIA_ENABLE_CLAP_EMBEDDINGS=false` | Audio-/Musikähnlichkeitssuche | Fehler beim Laden des Modells von HuggingFace (kein Internet, Firmennetz) |
| `JOLIA_ENABLE_AUDIO_TRANSCRIPTION=false`<br>`JOLIA_ENABLE_VIDEO_TRANSCRIPTION=false` | Whisper-Transkription | Audio/Video-Dateien blockieren die Verarbeitung stundenlang |
| `JOLIA_ENABLE_MEDIA_SUMMARIZATION=false` | KI-Zusammenfassung von Transkripten | Ollama ist nicht erreichbar oder zu langsam |
| `JOLIA_ENABLE_TAG_SUGGESTION=false` | Automatische Tag-Vorschläge | wie oben |
| `JOLIA_ENABLE_OCR=false`<br>`JOLIA_ENABLE_IMAGE_OCR=false` | Texterkennung in PDFs bzw. Bildern | Tesseract-Fehler, oder OCR wird nicht gebraucht |
| `JOLIA_WATCHER_ENABLED=false` | Automatischer Import aus der Inbox | Dateien sollen nur noch bewusst über die Weboberfläche hochgeladen werden |
| `JOLIA_CLUSTERING_ENABLED=false` | Nächtliches Clustering (Gesichter/Orte/Duplikate) | Rechner soll nachts in Ruhe gelassen werden |
| `JOLIA_BACKUP_ENABLED=false` | Tägliches Backup | Backup-Laufwerk fehlt oder ist voll |

### Leistung anpassen

| Schalter | Standard | Wirkung |
|----------|----------|---------|
| `JOLIA_MAX_CONCURRENT_PROCESSING=1` | 3 | Weniger Dateien gleichzeitig → Rechner bleibt bedienbar |
| `JOLIA_TRANSCRIPTION_SAMPLE_SECONDS=30` | 90 | Kürzerer Ausschnitt für Transkripte → deutlich schneller (`0` = ganze Datei) |
| `JOLIA_WHISPER_MODEL=tiny` | `base` | Kleineres Transkriptionsmodell (`tiny`/`base`/`small`/`medium`/`large`) |
| `JOLIA_MAX_FILE_SIZE_MB=500` | 2000 | Größere Dateien werden übersprungen |
| `JOLIA_OCR_LANGUAGES=eng` | `deu+eng` | OCR-Sprachen (im Image enthalten: `deu`, `eng`) |
| `OLLAMA_MODEL=qwen2.5:1.5b` | `qwen2.5:3b` | Kleineres, schnelleres Sprachmodell. Vorher laden: `docker exec jolia-ollama ollama pull qwen2.5:1.5b` |
| `JOLIA_OLLAMA_TIMEOUT=600` | 300 | Zeitlimit pro KI-Antwort in Sekunden – erhöhen bei sehr langsamer CPU |
| `JOLIA_HF_ENDPOINT=https://hf-mirror.com` | – | Spiegelserver, falls `huggingface.co` blockiert ist |

### Login einschalten

Standardmäßig gibt es **keinen Login**, und Port 8080 ist im ganzen lokalen
Netzwerk erreichbar. Auf einem Einzelplatz-PC ist das in Ordnung – steht der
Rechner in einem gemeinsam genutzten Netz, sollte der Zugriffsschutz an:

```powershell
# Passwort-Hash erzeugen (PowerShell)
$s = [System.Security.Cryptography.SHA256]::Create()
-join ($s.ComputeHash([Text.Encoding]::UTF8.GetBytes("meinPasswort")) | % { $_.ToString("x2") })
```

Ergebnis in die `.env` eintragen:

```ini
JOLIA_AUTH_ENABLED=true
JOLIA_AUTH_USERNAME=admin
JOLIA_AUTH_PASSWORD_HASH=<der erzeugte Hex-Wert>
JOLIA_AUTH_SESSION_SECRET=<eine lange, zufällige Zeichenkette>
```

Danach `docker compose up -d`. Die Übertragung läuft unverschlüsselt über HTTP –
der Login schützt gegen neugierige Mitbenutzer im LAN, ersetzt aber keine
Absicherung für den Zugriff aus dem Internet.

### Prüfen, ob ein Schalter gewirkt hat

Die Seite **Einstellungen** in der Weboberfläche zeigt den tatsächlich aktiven
Zustand (welche Funktionen laufen, ob Ollama verbunden ist). Alternativ:

```powershell
docker compose logs --tail 50 app
docker exec jolia-app env | Select-String JOLIA_
```

---

## Hinweise zum Docker-Image

Im Image sind **alle Features aktiviert**: OCR (Tesseract, deutsch + englisch),
Audio-/Video-Transkription (openai-whisper), CLIP-Bildähnlichkeitssuche
(OpenCLIP, offline ins Image gebacken), CLAP-Audiosuche und Gesichtserkennung
(face-recognition/dlib). PyTorch wird bewusst aus dem **CPU-Index** installiert –
ohne das wäre das Image durch die CUDA-Bibliotheken mehrere GB größer.
Der erste `--build` dauert deshalb länger (dlib wird kompiliert, ~340 MB
CLIP-Modell wird geladen). Die optionalen Pakete stehen in
[requirements.extra.txt](requirements.extra.txt).

---

## Installation (Linux / Deployment – ohne Docker)

```bash
# Repository klonen
git clone <repo-url> jolia
cd jolia

# Installation
bash scripts/install_linux.sh

# config.yaml anpassen
nano config.yaml

# Ollama installieren und Modell laden
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b

# Starten
bash scripts/run_linux.sh
```

---

## Konfiguration

Kopiere `config.example.yaml` nach `config.yaml` und passe die Pfade an:

```yaml
paths:
  inbox: "/mnt/fritzbox/inbox"       # Eingangsordner (NAS oder lokal)
  archive_root: "/home/docstore/source_documents"
  data_dir: "/home/docstore/data"

models:
  ollama_model: "qwen2.5:3b"          # Oder mistral:7b-instruct-q4
  embedding_model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

Für die Windows-Entwicklung: `.env.example` → `.env` kopieren und anpassen.

Einzelne Werte aus der `config.yaml` lassen sich über Umgebungsvariablen
überschreiben (Pfade, Feature-Schalter, Leistungsgrenzen, Login). Die
vollständige Liste steht in [.env.example](.env.example) und in
[app/config.py](app/config.py) unter `_ENV_OVERRIDES`; die Erklärung dazu im
Abschnitt [Notfall-Schalter](#notfall-schalter-wenn-etwas-klemmt). Im
Docker-Betrieb ist das der einzige vorgesehene Weg, etwas anzupassen – die
`config.yaml` liegt fest im Image.

---

## Architektur

```
Inbox-Ordner
    ↓ Import
source_documents/          ← Originaldateien (unveränderlich)
  documents/2026/...
  images/2026/...
  audio/2026/...
  video/2026/...
    + *.json               ← Sidecar: strukturierte Metadaten
    + *.md                 ← Sidecar: Markdown-Zusammenfassung

data/archive.db            ← SQLite (abgeleiteter Index)
data/chroma/               ← ChromaDB Vektoren (abgeleiteter Index)
```

**Kernprinzip**: Das Filesystem ist die Source of Truth. SQLite und ChromaDB können jederzeit aus den Originaldateien und Sidecars neu aufgebaut werden.

---

## Projektstruktur

```
app/
  main.py              FastAPI App
  config.py            Konfigurationsladung
  api/                 REST-Routes + UI-Routes
  db/                  SQLAlchemy-Modelle + Repositories
  services/            Geschäftslogik (Ingestion, Embedding, RAG, ...)
  processors/          Dateiformat-Prozessoren
  templates/           Jinja2 HTML-Templates
  static/              CSS + JavaScript
scripts/               Start- und Installationsskripte
tests/                 Unit-Tests
```

---

## Tests ausführen

```bash
source .venv/bin/activate
pip install pytest
pytest tests/ -v
```

---

## Mehrseitige Scans (Scan-Bundles)

Alle Scan-Quellen legen Einzelbilder in die Inbox; JOLIA fasst sie zu **einem PDF**
zusammen, legt einen durchsuchbaren Textlayer (Tesseract) hinein und analysiert
zusätzlich jede Seite per Ollama-Vision (Bildinhalte und handschriftliche Notizen
landen als eigene Chunks im Suchindex). Die Einzelbilder werden nicht archiviert.

**Voraussetzung für den markierbaren Text im PDF:** Tesseract muss installiert und
im `PATH` sein. Fehlt es, entsteht ein reines Bild-PDF – die Inhalte sind dann nur
über die JOLIA-Suche auffindbar, nicht im PDF-Viewer.

### Konvention für die Inbox

| Element | Muster | Beispiel |
|---------|--------|----------|
| Seite | `{bundle_id}_{NN}.{jpg\|png\|heic\|webp\|tif}` | `60926a67…7430_01.jpg` |
| Manifest (optional) | `{bundle_id}.scan.json` | `60926a67…7430.scan.json` |
| Ergebnis | `{titel}__{bundle_id}.pdf` | `Rechnung Stadtwerke__60926a67…7430.pdf` |

`bundle_id` ist eine UUID (mit oder ohne Bindestriche). Ein Bundle wird verarbeitet,
sobald das Manifest `"complete": true` enthält, die erwartete Seitenzahl erreicht ist
oder seit der letzten Seite `scan.bundle_idle_seconds` vergangen sind.

```json
{
  "bundle_id": "60926a67c9af4cda862d22eac1d87430",
  "title": "Rechnung Stadtwerke",
  "source": "kotlin-app",
  "expected_pages": 2,
  "complete": true
}
```

### API (für PWA, Web-UI und externe Apps)

```http
POST /api/scan/upload            # multipart: files[], bundle_id, title, source, complete
POST /api/scan/bundles/{id}/complete   # offenes Bundle abschließen (optional: title)
GET  /api/scan/bundles           # offene Bundles auflisten
```

Beispiel für eine externe App (z. B. Kotlin), die Seiten einzeln hochlädt:

```bash
BID=$(uuidgen | tr -d '-')
curl -X POST http://localhost:8080/api/scan/upload \
  -F "files=@seite1.jpg;type=image/jpeg" \
  -F "bundle_id=$BID" -F "source=kotlin-app" \
  -F "title=Rechnung Stadtwerke" -F "complete=false"

curl -X POST http://localhost:8080/api/scan/upload \
  -F "files=@seite2.jpg;type=image/jpeg" \
  -F "bundle_id=$BID" -F "complete=false"

curl -X POST "http://localhost:8080/api/scan/bundles/$BID/complete"
```

Alternativ kann die App die Dateien direkt (z. B. per SMB) nach der obigen
Konvention in die Inbox schreiben – der Watcher bündelt sie dann selbstständig.

### Einstellungen (`config.yaml`, Abschnitt `scan`)

| Schlüssel | Bedeutung |
|-----------|-----------|
| `bundle_enabled` | Bündelung aktiv; `false` = Seiten werden als Einzelbilder importiert |
| `bundle_idle_seconds` | Wartezeit nach der letzten Seite, wenn kein Manifest vorliegt |
| `pdf_ocr` | Tesseract-Textlayer ins PDF einbetten |
| `pdf_dpi` | Seitengröße; `0` = automatisch aus der Bildgröße (≈ A4) |
| `vision_per_page` | Ollama-Vision je Seite (Bildinhalte, Handschrift) |
| `vision_max_pages` | Deckel für die Vision-Analyse; `0` = alle Seiten |
| `keep_page_images_seconds` | `>0` = Seitenbilder zur Fehlersuche im `temp_dir` behalten |

---

## Optionale Erweiterungen

- **Audio-/Video-Transkription**: whisper.cpp installieren und in `config.yaml` konfigurieren
- **HEIC-Support**: `pip install pillow-heif` (bereits in requirements.txt)
- **Autostart Linux**: systemd-Service anlegen
- **Automatischer Inbox-Watcher**: `watcher.enabled: true` in config.yaml setzen

---

## Lizenz

Privates Projekt – kein öffentliches Release vorgesehen.

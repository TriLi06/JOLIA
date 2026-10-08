# JOLIA

JOLIA archiviert Dokumente, Fotos, Scans, Audio- und Videodateien lokal und macht ihre Inhalte durch OCR, Metadaten, Transkription und semantische Suche auffindbar.

## Lizenz und Nutzungsumfang

**JOLIA darf nur nicht-kommerziell genutzt werden.** Der JOLIA-eigene Code steht unter der [PolyForm Noncommercial License 1.0.0](LICENSE). Die Lizenz gestattet nur die dort beschriebenen nicht-kommerziellen Zwecke. Dazu gehören bestimmte private Studien-, Hobby- und Forschungszwecke sowie die Nutzung durch die in der Lizenz aufgeführten nicht-kommerziellen Organisationen.

Kommerzielle Nutzung ist nicht gestattet. Dazu zählt insbesondere der Einsatz in geschäftlichen Betriebsabläufen, ein kostenpflichtiger oder monetarisierter Dienst, Weiterverkauf oder die Integration in ein kommerzielles Produkt. Eine kostenlose Bereitstellung macht eine geschäftliche Nutzung nicht automatisch nicht-kommerziell. Für eine kommerzielle Nutzung ist vorab eine separate schriftliche Erlaubnis des Rechteinhabers erforderlich. Bei Zweifeln gilt der Lizenztext; diese README ist keine Rechtsberatung.

PolyForm Noncommercial beschränkt die Nutzungsfelder und ist daher **keine OSI-anerkannte Open-Source-Lizenz**. JOLIA ist unter diesen Bedingungen source-available, aber nicht „Open Source“ im Sinne der Open Source Definition.

Drittanbieter-Code und Modellgewichte unterliegen weiterhin ihren jeweils eigenen Bedingungen. Sie werden durch die JOLIA-Lizenz weder ersetzt noch erweitert. Siehe [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) und [LICENSE-OpenCV-4.9.0.txt](LICENSE-OpenCV-4.9.0.txt).

### AI-Unterstützung

Teile des Quellcodes wurden mit Unterstützung von GitHub Copilot erstellt oder überarbeitet. KI-Nutzung überträgt keine Urheberrechte und garantiert nicht, dass ein Vorschlag frei von Ähnlichkeiten zu anderem Material ist. Der Maintainer ist für Prüfung, Rechteklärung und Lizenzierung der veröffentlichten Beiträge verantwortlich.

JOLIA verwendet außerdem zahlreiche externe Bibliotheken, die in `requirements.txt`, `requirements.extra.txt` und `docscan-pwa/package-lock.json` deklariert sind. Das ist von kopiertem Drittanbieter-Quellcode zu unterscheiden. Zusätzlich sind einzelne Assets wie OpenCV.js ausdrücklich als Drittanbieterbestandteil dokumentiert. Die SBOM-Anleitung unten inventarisiert Paketabhängigkeiten, ersetzt aber keine Lizenzprüfung.

## Unterstützte Installation

**Der einzige unterstützte Installationsweg ist das Windows-11-WSL2-Installationsskript.** Eigenständige Linux-, macOS-, Docker-Desktop- oder manuelle Python-Installationen werden nicht unterstützt. Das Skript richtet eine eigene WSL2-Distribution ein und installiert Docker Engine darin; Docker Compose ist dabei interne Implementierung und kein zusätzlicher Installationsweg. Docker Desktop wird nicht benötigt.

### Voraussetzungen

- Windows 11 64-Bit mit aktivierter Hardware-Virtualisierung
- Git für Windows
- Administratorzugriff zum Aktivieren von WSL2 und der Virtual Machine Platform
- Internetzugang für WSL, Systempakete, JOLIA-Abhängigkeiten und Modelle
- Mindestens 30 GB freier Speicher; 16 GB RAM werden empfohlen

### Installation

Öffne `cmd.exe` und führe aus:

```bat
git clone https://github.com/TriLi06/JOLIA.git "%USERPROFILE%\JOLIA"
cd /d "%USERPROFILE%\JOLIA"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\WSL_startup.ps1"
```

Wähle im Menü `1` für Installation oder Reparatur. Das Skript fordert bei Bedarf Administratorrechte über die Windows-UAC-Abfrage an. Lies und bestätige die PolyForm-Lizenz, wenn sie angezeigt wird. Falls WSL2 erst aktiviert werden muss, starte Windows nach der Meldung neu und führe das Skript erneut aus.

Vor dem Docker-Build und den Ollama-Modell-Downloads zeigt das Skript zusätzlich die Bedingungen der externen Modelle an. Zum Fortfahren muss `MODELLBEDINGUNGEN GEPRUEFT` exakt eingegeben werden. Diese Bestätigung informiert über die Bedingungen, erteilt aber keine zusätzlichen Rechte und ersetzt keine separate Modelllizenz oder Registrierung. Details stehen unter [Modelle und Downloads](#modelle-und-downloads).

Bei FRITZ!NAS-Speicher sind die im Skript stehenden Zugangswerte nur Beispiele. Ersetze sie vor der Verwendung durch eigene Werte oder wähle im Menü einen lokalen Speicherordner. Veröffentliche keine persönlichen Zugangsdaten.

Nach erfolgreichem Start ist JOLIA unter <http://localhost:8090> erreichbar.
Das Skript gibt zusätzlich die LAN-Adresse für andere Geräte im Heimnetz aus.
Bei Problemen mit dem Netzwerkzugriff wähle im Menü `7` für die schrittweise
Diagnose; Menüpunkt `1` installiert oder repariert die WSL-/LAN-Konfiguration.

Für andere Geräte verwende `http://<Windows-LAN-IP>:8090`, nicht eine Docker-Bridge-
oder WSL-NAT-Adresse. Das Heimnetz muss in Windows als **Privat** eingestuft sein;
öffentliche Netzwerke bleiben bewusst gesperrt. Ein Test vom Windows-Host auf seine
eigene LAN-IP kann im Mirrored-Modus fehlschlagen, obwohl andere Geräte Zugriff haben.
Teste deshalb auch von einem zweiten Gerät im selben vertrauenswürdigen Heimnetz.

Ollama ist absichtlich nur im Docker-Netz unter `http://ollama:11434` erreichbar.
`http://localhost:11434` auf Windows und die LAN-IP auf Port `11434` sind keine
vorgesehenen Zugriffswege. Menüpunkt `7` prüft die Verbindung aus dem App-Container,
die Modellliste, eine echte Bild-Inferenz mit dem konfigurierten Vision-Modell und
die Init-Logs. Der Inferenztest lädt das Modell dafür einmal in den Arbeitsspeicher.
`jolia-ollama-init`
mit Status `Exited (0)` ist normal; bei einem fehlgeschlagenen Modell-Download
startet die App nicht.

Bei einer Reparatur schreibt der Installer Port und Speicherpfade in
`/opt/jolia/.env` neu und prüft die Compose-Konfiguration. Er meldet einen
fehlgeschlagenen App-Start nicht als erfolgreiche Installation. Ist trotz
`networkingMode=mirrored` noch NAT aktiv, speichere zuerst andere WSL-Arbeit,
führe `wsl --shutdown` aus und starte Menüpunkt `1` erneut. Verwende denselben
Windows-Benutzer wie bei der Installation: WSL-Distributionen sind benutzergebunden.

Regressionstests für den Installer (ohne Installation, Administratorrechte oder
Modell-Downloads):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\test_wsl_startup.ps1
```

### Installer-EXE bauen

Maintainer können eine Windows-Launcher-EXE erstellen. Voraussetzungen sind Windows PowerShell 5.1 oder neuer, der .NET Framework 4.x C#-Compiler und Internetzugriff; Git oder zusätzliche PowerShell-Module werden nicht benötigt:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

Ohne Parameter baut der Builder aus der lokalen `scripts/WSL_startup.ps1`; die EXE startet standardmäßig genau diese mitgelieferte Datei und lädt zur Laufzeit nichts nach. Für einen Build aus GitHub kann `-GitHubRef` auf einen Branch, Tag oder Commit-SHA gesetzt werden. Release-Builds aus GitHub müssen einen vollständigen Commit-SHA verwenden, nicht einen beweglichen Branch.

Das Ergebnis liegt unter `dist\JOLIA_setup.exe`. Ohne Programmargument lädt die EXE bei jedem Start das aktuelle `WSL_startup.ps1` von `main` per HTTPS und startet es mit Windows PowerShell. Bei fehlender Verbindung verwendet sie nach einem Hinweis die mitgelieferte `WSL_startup.ps1`-Build-Kopie. Beide Dateien sowie `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md` und `LICENSE-OpenCV-4.9.0.txt` gehören deshalb gemeinsam ins Release-Bundle. Das Setup benötigt Internetzugang und führt weiter über WSL2; keine echten Passwörter oder geheimen Werte in die Skriptdatei aufnehmen.

Der Builder kompiliert einen kleinen, im Buildskript definierten C#-Launcher und lädt kein PS2EXE oder anderes PowerShell-zu-EXE-Modul. Ein optionales erstes Programmargument der EXE aktiviert einen expliziten Download von `WSL_startup.ps1` für diese GitHub-Referenz; ohne Argument wird das mitgelieferte Skript verwendet.

Für Nutzer wird das vollständige Bundle aus `dist` als GitHub-Release angeboten. Vor dem Start das Bundle entpacken und `JOLIA_setup.exe` aus diesem Ordner starten. Die EXE ist nicht Authenticode-signiert; Windows SmartScreen kann deshalb eine Warnung anzeigen. Eine Code-Signatur mit einem passenden Herausgeberzertifikat wäre vor breiter Verteilung empfehlenswert.

### Verwaltung und Deinstallation

Das WSL-Menü bietet:

| Auswahl | Aktion |
| --- | --- |
| `1` | JOLIA installieren oder reparieren |
| `2` | JOLIA aktualisieren; Modellbedingungen werden vor dem Build erneut angezeigt |
| `3` | Windows-Autostart aktivieren oder deaktivieren |
| `4` | WSL-Distribution und darin gespeicherte JOLIA-/Docker-Daten löschen |
| `5` | Installationsstatus prüfen |
| `6` | FRITZ!NAS oder lokalen Speicherordner konfigurieren |
| `7` | LAN-Zugriff einschließlich Container-Health und Docker-Portweiterleitung testen |
| `8` | JOLIA-Containerlogs der letzten 10 Minuten und neue Einträge live anzeigen |

Menüpunkt `4` löscht die JOLIA-WSL-Distribution einschließlich der darin gespeicherten Archive, Datenbanken, Modelle, Container und Volumes. Erstelle und prüfe vorher ein Backup. Die Windows-Features WSL2 und Virtual Machine Platform bleiben aktiviert. Der geklonte Ordner `%USERPROFILE%\JOLIA` wird nicht automatisch entfernt.

## Modelle und Downloads

JOLIA verteilt im Quellrepository keine Modell-Checkpoint-Dateien. Der WSL-Installer baut jedoch ein lokales Container-Image und lädt Modelle auf den Rechner. Die Modellbedingungen sind unabhängig von der PolyForm-Lizenz für JOLIA:

- Die Standardmodelle `qwen2.5:1.5b`, `qwen2.5:7b` und `qwen2.5vl:3b` werden laut den jeweiligen Ollama-Modellseiten unter Apache-2.0 angeboten.
- `bge-m3` wird laut Modellkarte unter MIT angeboten.
- Der OpenAI-CLIP-Checkpoint `ViT-B-32` wird beim Docker-Build heruntergeladen und in das lokal gebaute Image kopiert.
- LAION CLAP und Whisper werden bei aktivierter Funktion beziehungsweise erster Verwendung nachgeladen.
- Das dlib-68-Punkt-Landmark-Modell kommt über `face-recognition`; der Upstream weist auf Einschränkungen der zugrunde liegenden iBUG-Daten für kommerzielle Produkte hin.

Andere Modelle können enger lizenziert sein. Beispielsweise beschränkt die Qwen Research License `qwen2.5:3b` auf Forschungs- oder Evaluationszwecke; MiniCPM-V hat ebenfalls eigene Bedingungen. Diese Varianten sind keine Installer-Defaults. Modell-Tags und Bedingungen können sich ändern. Prüfe vor jeder Weitergabe eines gebauten Images die exakte Version, Lizenz und erforderlichen Hinweise. Eine Modell-Bestätigung im Installer macht eine durch die jeweilige Modelllizenz ausgeschlossene Nutzung nicht zulässig.

## Software-Stückliste (SBOM)

Für einen Release wird eine CycloneDX-SBOM mit Syft 1.52.0 erzeugt. Das Skript lädt Syft als fest versionierten Container in die verwaltete WSL-Docker-Umgebung; eine separate Syft-Installation auf Windows ist nicht erforderlich. Erzeuge nach der WSL-Installation eine SBOM für Quellmanifeste und Lockfiles:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\generate_sbom.ps1
```

Nach dem App-Build zusätzlich SBOMs für die tatsächlich verwendeten Container-Images erstellen:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\generate_sbom.ps1 -Image "jolia-docs:latest","ollama/ollama:latest"
```

Die Datei `.env.example` enthält nur optionale Runtime-Overrides. Sie ist keine Installationsanleitung. In der verwalteten Distribution liegt die App-Konfiguration unter `/opt/jolia/.env`; Speicherpfade und Port werden über das WSL-Menü verwaltet.

Die SBOM-Dateien erscheinen in `dist\sbom\` und tragen den Git-Commit im Namen und in den Metadaten. Hänge die passenden SBOMs zusammen mit `JOLIA_setup.exe` und den Lizenzbeilegern an das Release. Paket-SBOMs erfassen Modellgewichte nicht zuverlässig, auch nicht den CLIP-Checkpoint im JOLIA-Image oder Gewichte in Ollama-Volumes; dafür gilt zusätzlich das manuelle Modellinventar in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). `requirements.txt` enthält Versionsbereiche statt eines vollständigen Python-Lockfiles, daher ist die Image-SBOM für die tatsächlich installierten Python-/Systempakete maßgeblich.

## Daten und Netzwerk

JOLIA verarbeitet und speichert Dokumente, Suchindex und Modelle lokal in der WSL-Umgebung beziehungsweise in den konfigurierten Speicherorten. Internet ist für Installation und Modell-Downloads erforderlich. Die Oberfläche lädt Pico CSS zur Laufzeit von jsDelivr; dadurch entsteht auch nach der Installation eine externe Webanfrage. „Lokal“ bedeutet daher, dass Dokumentinhalte und Inferenz lokal verarbeitet werden, nicht dass der Rechner keinerlei Netzwerkverbindungen aufnimmt.

### Zugriff und Heimnetz

**JOLIA hat in der unterstützten WSL-Installation bewusst keine Anmeldung und kein Passwort.** Jeder Rechner oder jedes Gerät, das den veröffentlichten Port im lokalen Netz erreichen kann, kann auf die JOLIA-Weboberfläche und ihre Funktionen zugreifen. Es gibt keine Benutzertrennung.

Der WSL-Installer aktiviert Mirrored Networking. Die Anwendung lauscht im Container auf allen Interfaces (`0.0.0.0`); der Windows-Port ist standardmäßig `8090`. Die Windows-Firewall und der Router beeinflussen die Erreichbarkeit, ersetzen aber keine Anmeldung.

**JOLIA ist ausschließlich für ein privates, vertrauenswürdiges und abgesichertes Heimnetz vorgesehen.** Nicht in Firmen-/Schulnetzen, öffentlichen oder Gäste-WLANs oder anderen gemeinsam genutzten Netzen betreiben. Keine Router-Portweiterleitung, öffentliche Freigabe, Reverse-Proxy-Veröffentlichung oder Tunnel zu JOLIA einrichten. Alle Personen und Geräte mit Zugriff auf dieses Heimnetz sind als vertrauenswürdig zu behandeln. Wenn diese Voraussetzung nicht erfüllt ist, JOLIA nicht starten.

Die Übertragung läuft über HTTP und ist nicht für Internetzugriff abgesichert. Dokumente, Fotos und gegebenenfalls Gesichtserkennungsdaten werden lokal verarbeitet; jeder erreichbare LAN-Nutzer kann jedoch mit der Anwendung interagieren. Das Setup fragt kein Passwort ab und stellt keinen Login bereit.

### Verarbeitungszeiten in der Konsole anzeigen

JOLIA schreibt bei der Verarbeitung einer Datei die Laufzeit der einzelnen Schritte und die Gesamtzeit ins Anwendungs-Log. Öffne dazu PowerShell unter Windows und führe aus:

```powershell
wsl -d jolia-wsl -u root -- docker logs -f jolia-app
```

Die Ausgabe wird fortlaufend angezeigt; `Strg+C` beendet die Anzeige, nicht JOLIA. Zum Anzeigen der letzten 10 Minuten und anschließendem Weiterverfolgen:

```powershell
wsl -d jolia-wsl -u root -- docker logs --since 10m -f jolia-app
```

Die Zeilen mit `Laufzeit` zeigen unter anderem Bildanalyse, Datei-Extraktion, Embeddings, Zusammenfassung, Tag-Vorschlag und Kategorisierung.

## Funktionen und Formate

- Automatischer Inbox-Import und Archivierung der Originaldateien
- OCR, Metadaten- und Textextraktion sowie optional Audio-/Video-Transkription
- Semantische Suche, RAG-Chat, Kategorien und Tags
- Backups und Reindexierung aus den Originaldateien
- Bündelung mehrseitiger Scans in durchsuchbare PDFs

| Kategorie | Formate |
| --- | --- |
| Dokumente | PDF, TXT, MD, DOCX, XLSX, PPTX |
| Bilder | JPG, PNG, HEIC, TIFF, WebP |
| Audio | MP3, M4A, WAV, FLAC, OGG |
| Video | MP4, MKV, AVI, MOV, WebM |

## Mehrseitige Scans

Scan-Clients können einzelne Seiten in die Inbox legen; JOLIA bündelt sie nach einer erwarteten Seitenzahl, einem Manifest oder einer Ruhezeit. Der Dateiname hat die Form `{bundle_id}_{NN}.{jpg|png|heic|webp|tif}`. Ein optionales `{bundle_id}.scan.json`-Manifest kann Titel, Quelle, erwartete Seitenzahl und Abschlussstatus enthalten.

```json
{
  "bundle_id": "60926a67c9af4cda862d22eac1d87430",
  "title": "Rechnung Stadtwerke",
  "source": "external-client",
  "expected_pages": 2,
  "complete": true
}
```

Die API bietet `POST /api/scan/upload`, `POST /api/scan/bundles/{id}/complete` und `GET /api/scan/bundles`. Für einen durchsuchbaren PDF-Textlayer muss Tesseract installiert und erreichbar sein.

## Projekt und Hinweise

```text
app/                    Anwendung, API, Datenbank und Verarbeitung
docscan-pwa/            Browserbasierte Scan-Anwendung
scripts/WSL_startup.ps1 Einziger unterstützter Installer/Verwalter
docker/                 Hilfen für den internen WSL-Image-Build
tests/                  Tests
```

Der Inhalt von `docker/`, `Dockerfile` und `docker-compose.yml` dient ausschließlich dem WSL-Installationsweg und ist keine Anleitung für eine separate Docker-Installation.
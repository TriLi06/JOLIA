# PageScan

Eigenständige Android-App (Kotlin) zum Scannen mehrseitiger PDFs. Vollständig
unabhängig von der JOLIA-Docs-Anwendung im übergeordneten Ordner.

## Funktionsweise

- Live-Vorschau (CameraX) mit fortlaufender Dokumenterkennung über OpenCV
  (Canny + Kontursuche + `approxPolyDP`), das größte konvexe Viereck mit
  plausiblen Innenwinkeln wird als Seite gewertet.
- Der erkannte Rahmen wird als Overlay ins Livebild gezeichnet; auf seinen
  Mittelpunkt wird per `startFocusAndMetering` scharfgestellt.
- Wird kein Dokument gefunden, erscheint kein Rahmen und die Aufnahme wird
  ungeschnitten (komplettes Kamerabild) übernommen.
- Nach dem Auslösen wird das Foto per `warpPerspective` auf das Viereck
  zugeschnitten und entzerrt.
- Abschließen erzeugt ein mehrseitiges PDF (A4, Seiten eingepasst) unter
  `Download/PageScan/Scan_<Zeitstempel>.pdf`.

## Bedienung

| Ansicht | Buttons |
| --- | --- |
| Kamera | **Scannen** (+ **Abschließen**, sobald Seiten erfasst sind) |
| Nach Aufnahme | **Weitere Seite**, **Abschließen**, **Verwerfen** |

## Bauen

Voraussetzungen: JDK 17, Android SDK 35, minSdk 34 (Android 14).

In Android Studio (Ladybug oder neuer) den Ordner `pdfscanner-android` öffnen –
der Gradle-Wrapper wird dabei automatisch ergänzt.

Auf der Kommandozeile ohne Wrapper-JAR zuerst einmalig:

```powershell
cd pdfscanner-android
gradle wrapper --gradle-version 8.9
./gradlew assembleDebug
```

Die OpenCV-Bibliothek wird als Maven-Artefakt (`org.opencv:opencv`) bezogen,
es ist kein manuelles SDK-Setup nötig. Paketiert werden nur `arm64-v8a` und
`armeabi-v7a`.

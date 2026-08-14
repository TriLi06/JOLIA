export default function SettingsPage() {
  return (
    <div className="min-h-screen bg-slate-900 p-4">
      <h1 className="mb-5 text-lg font-bold text-white">Einstellungen</h1>

      <div className="space-y-4">
        <section className="rounded-xl bg-slate-800 p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-300">Über JOLIA Docs</h2>
          <div className="space-y-2 text-sm text-slate-400">
            <Row label="Version" value="1.0.0" />
            <Row label="Backend" value="FastAPI (Python)" />
            <Row label="Kamera-Erkennung" value="OpenCV.js" />
          </div>
        </section>

        <section className="rounded-xl bg-slate-800 p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-300">Erweiterte Funktionen</h2>
          <div className="space-y-3">
            <a
              href="/dashboard"
              className="block rounded-xl bg-slate-700 px-4 py-3 text-sm text-white hover:bg-slate-600"
            >
              🌐 Vollständiges Web-Interface öffnen
            </a>
            <a
              href="/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="block rounded-xl bg-slate-700 px-4 py-3 text-sm text-white hover:bg-slate-600"
            >
              📖 API-Dokumentation (Swagger)
            </a>
          </div>
        </section>

        <section className="rounded-xl bg-slate-800 p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-300">PWA-Installation</h2>
          <p className="text-xs leading-relaxed text-slate-400">
            Fügen Sie diese Seite zum Startbildschirm hinzu, um sie als eigenständige App zu nutzen.
            In Android Chrome: Menü → „Zum Startbildschirm hinzufügen".
          </p>
        </section>

        <section className="rounded-xl bg-slate-800 p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-300">OpenCV.js</h2>
          <p className="text-xs leading-relaxed text-slate-400">
            Für die Dokumenterkennung wird OpenCV.js benötigt. Laden Sie{' '}
            <code className="rounded bg-slate-700 px-1 text-blue-300">opencv.js</code> herunter
            und legen Sie es unter{' '}
            <code className="rounded bg-slate-700 px-1 text-blue-300">public/opencv/opencv.js</code> ab.
          </p>
        </section>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-300">{value}</span>
    </div>
  );
}

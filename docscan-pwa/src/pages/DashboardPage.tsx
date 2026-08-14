import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';

interface Stats {
  status_counts: Record<string, number>;
  recent_files: Array<{ id: string; original_filename: string; status: string; imported_at: string; content_type?: string }>;
  chroma_counts: Record<string, number>;
  inbox_path: string;
  model_mismatch_warning?: string;
  last_backup?: string;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  pending: { label: 'Wartend', color: 'bg-yellow-700 text-yellow-200' },
  queued: { label: 'In Warteschlange', color: 'bg-blue-800 text-blue-200' },
  processing: { label: 'Wird verarbeitet', color: 'bg-indigo-800 text-indigo-200' },
  done: { label: 'Abgeschlossen', color: 'bg-green-800 text-green-200' },
  error: { label: 'Fehler', color: 'bg-red-800 text-red-200' },
  skipped: { label: 'Übersprungen', color: 'bg-slate-700 text-slate-300' },
};

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchStats();
  }, []);

  async function fetchStats() {
    setLoading(true);
    try {
      const [filesRes, statsRes] = await Promise.all([
        api.get('/files?limit=10'),
        api.get('/files?limit=1'),
      ]);
      // Statistiken aus Dateiliste ableiten
      const allFiles: any[] = filesRes.data.items ?? [];
      const status_counts: Record<string, number> = {};
      allFiles.forEach((f: any) => {
        status_counts[f.status] = (status_counts[f.status] ?? 0) + 1;
      });
      setStats({
        status_counts,
        recent_files: allFiles.slice(0, 10),
        chroma_counts: {},
        inbox_path: '',
      });
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleImportInbox() {
    setImporting(true);
    setImportMsg(null);
    try {
      const res = await api.post('/files/import-inbox');
      setImportMsg(res.data.message ?? 'Import abgeschlossen.');
      fetchStats();
    } catch (err: any) {
      setImportMsg(`Fehler: ${err.response?.data?.detail ?? err.message}`);
    } finally {
      setImporting(false);
    }
  }

  const totalFiles = Object.values(stats?.status_counts ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div className="min-h-screen bg-slate-900 p-4">
      {/* Kopfzeile */}
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">JOLIA Docs</h1>
          <p className="text-xs text-slate-500">Turn Documents, Photos and Scans into Knowledge.</p>
        </div>
        <Link
          to="/scan"
          className="flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500"
        >
          📷 Scannen
        </Link>
      </div>

      {/* Meldung bei Modell-Mismatch */}
      {stats?.model_mismatch_warning && (
        <div className="mb-4 rounded-xl border border-yellow-700 bg-yellow-900/30 p-3 text-sm text-yellow-300">
          ⚠️ {stats.model_mismatch_warning}
        </div>
      )}

      {/* Import-Meldung */}
      {importMsg && (
        <div className="mb-4 rounded-xl border border-green-700 bg-green-900/30 p-3 text-sm text-green-300">
          {importMsg}
        </div>
      )}

      {/* Statistik-Kacheln */}
      {loading ? (
        <div className="flex justify-center py-10">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-600 border-t-blue-400" />
        </div>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-3 gap-3">
            <div className="rounded-xl bg-slate-800 p-3 text-center">
              <p className="text-2xl font-bold text-white">{totalFiles}</p>
              <p className="text-xs text-slate-400">Gesamt</p>
            </div>
            <div className="rounded-xl bg-green-900/40 p-3 text-center">
              <p className="text-2xl font-bold text-green-300">{stats?.status_counts?.done ?? 0}</p>
              <p className="text-xs text-slate-400">Verarbeitet</p>
            </div>
            <div className="rounded-xl bg-red-900/40 p-3 text-center">
              <p className="text-2xl font-bold text-red-300">{stats?.status_counts?.error ?? 0}</p>
              <p className="text-xs text-slate-400">Fehler</p>
            </div>
          </div>

          {/* Status-Aufschlüsselung */}
          {Object.keys(STATUS_LABELS).map((st) =>
            (stats?.status_counts?.[st] ?? 0) > 0 ? (
              <div key={st} className="mb-2 flex items-center justify-between rounded-lg bg-slate-800 px-3 py-2">
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_LABELS[st].color}`}>
                  {STATUS_LABELS[st].label}
                </span>
                <span className="text-sm font-semibold text-white">{stats!.status_counts[st]}</span>
              </div>
            ) : null,
          )}

          {/* Inbox-Import */}
          <div className="my-4 rounded-xl bg-slate-800 p-4">
            <h2 className="mb-3 text-sm font-semibold text-slate-300">Inbox-Import</h2>
            <button
              onClick={handleImportInbox}
              disabled={importing}
              className={`w-full rounded-xl py-3 text-sm font-semibold text-white transition-colors ${
                importing ? 'cursor-not-allowed bg-slate-600' : 'bg-blue-600 hover:bg-blue-500'
              }`}
            >
              {importing ? 'Importiere…' : '📂 Inbox jetzt importieren'}
            </button>
          </div>

          {/* Zuletzt hinzugefügte Dateien */}
          {stats && stats.recent_files.length > 0 && (
            <div className="rounded-xl bg-slate-800 p-4">
              <h2 className="mb-3 text-sm font-semibold text-slate-300">Zuletzt importiert</h2>
              <ul className="space-y-2">
                {stats.recent_files.slice(0, 5).map((f) => (
                  <li key={f.id}>
                    <Link
                      to={`/files/${f.id}`}
                      className="flex items-center justify-between rounded-lg px-2 py-1.5 hover:bg-slate-700"
                    >
                      <span className="truncate text-sm text-white">{f.original_filename}</span>
                      <span className={`ml-2 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_LABELS[f.status]?.color ?? 'bg-slate-700 text-slate-300'}`}>
                        {STATUS_LABELS[f.status]?.label ?? f.status}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
              <Link to="/files" className="mt-3 block text-center text-xs text-blue-400 hover:underline">
                Alle Dateien anzeigen →
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  );
}

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';

interface FileItem {
  id: string;
  original_filename: string;
  mime_type: string | null;
  content_type: string | null;
  file_size: number | null;
  status: string;
  imported_at: string;
}

const STATUS_COLOR: Record<string, string> = {
  done: 'bg-green-800 text-green-200',
  error: 'bg-red-800 text-red-200',
  processing: 'bg-indigo-800 text-indigo-200',
  queued: 'bg-blue-800 text-blue-200',
  pending: 'bg-yellow-800 text-yellow-200',
};

function formatBytes(bytes: number | null): string {
  if (!bytes) return '–';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function FilesPage() {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState('');
  const limit = 30;

  useEffect(() => {
    fetchFiles();
  }, [page]);

  async function fetchFiles() {
    setLoading(true);
    try {
      const res = await api.get('/files', { params: { limit, offset: page * limit } });
      setFiles(res.data.items ?? []);
      setTotal(res.data.total ?? 0);
    } catch {
      setFiles([]);
    } finally {
      setLoading(false);
    }
  }

  const filtered = filter
    ? files.filter((f) => f.original_filename.toLowerCase().includes(filter.toLowerCase()))
    : files;

  return (
    <div className="min-h-screen bg-slate-900 p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-bold text-white">Dateien</h1>
        <span className="text-sm text-slate-400">{total} gesamt</span>
      </div>

      {/* Suchfeld */}
      <input
        type="search"
        placeholder="Datei suchen…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="mb-4 w-full rounded-xl bg-slate-800 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:ring-2 focus:ring-blue-500"
      />

      {loading ? (
        <div className="flex justify-center py-10">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-600 border-t-blue-400" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-12 text-center text-slate-500">Keine Dateien gefunden.</div>
      ) : (
        <ul className="space-y-2">
          {filtered.map((f) => (
            <li key={f.id}>
              <Link
                to={`/files/${f.id}`}
                className="flex items-center justify-between rounded-xl bg-slate-800 px-4 py-3 hover:bg-slate-700"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-white">{f.original_filename}</p>
                  <p className="text-xs text-slate-500">
                    {f.content_type ?? f.mime_type ?? '–'} · {formatBytes(f.file_size)}
                  </p>
                </div>
                <span
                  className={`ml-2 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_COLOR[f.status] ?? 'bg-slate-700 text-slate-300'}`}
                >
                  {f.status}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {/* Seitennavigation */}
      {total > limit && (
        <div className="mt-4 flex justify-center gap-3">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="rounded-lg bg-slate-700 px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            ← Zurück
          </button>
          <span className="self-center text-xs text-slate-400">
            Seite {page + 1} / {Math.ceil(total / limit)}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={(page + 1) * limit >= total}
            className="rounded-lg bg-slate-700 px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            Weiter →
          </button>
        </div>
      )}
    </div>
  );
}

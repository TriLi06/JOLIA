import { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import api from '../services/api';

interface FileDetail {
  id: string;
  original_filename: string;
  archive_path: string;
  mime_type: string | null;
  content_type: string | null;
  file_size: number | null;
  status: string;
  imported_at: string;
  processed_at: string | null;
  error_message: string | null;
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

function formatDate(iso: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleString('de-DE');
}

export default function FileDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [file, setFile] = useState<FileDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [reprocessing, setReprocessing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (id) fetchFile(id);
  }, [id]);

  async function fetchFile(fileId: string) {
    setLoading(true);
    try {
      const res = await api.get(`/files/${fileId}`);
      setFile(res.data);
    } catch {
      setFile(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleReprocess() {
    if (!id) return;
    setReprocessing(true);
    try {
      const res = await api.post(`/files/${id}/reprocess`);
      setMsg(res.data.message ?? 'Verarbeitung gestartet.');
      fetchFile(id);
    } catch (err: any) {
      setMsg(`Fehler: ${err.response?.data?.detail ?? err.message}`);
    } finally {
      setReprocessing(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-900">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-600 border-t-blue-400" />
      </div>
    );
  }

  if (!file) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-slate-900 p-6 text-center">
        <p className="mb-4 text-slate-400">Datei nicht gefunden.</p>
        <button onClick={() => navigate('/files')} className="text-blue-400 hover:underline">
          Zurück zur Liste
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 p-4">
      <button onClick={() => navigate('/files')} className="mb-4 text-sm text-blue-400 hover:underline">
        ← Zurück zu Dateien
      </button>

      <div className="rounded-xl bg-slate-800 p-4">
        <h1 className="mb-1 break-all text-base font-bold text-white">{file.original_filename}</h1>
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_COLOR[file.status] ?? 'bg-slate-700 text-slate-300'}`}>
          {file.status}
        </span>

        <div className="mt-4 space-y-2 text-sm text-slate-300">
          <Row label="Typ" value={file.content_type ?? file.mime_type ?? '–'} />
          <Row label="Größe" value={formatBytes(file.file_size)} />
          <Row label="Importiert" value={formatDate(file.imported_at)} />
          <Row label="Verarbeitet" value={formatDate(file.processed_at)} />
          <Row label="Archivpfad" value={file.archive_path} mono />
        </div>

        {file.error_message && (
          <div className="mt-4 rounded-lg bg-red-900/40 p-3 text-xs text-red-300">
            <strong>Fehler:</strong> {file.error_message}
          </div>
        )}

        {msg && (
          <div className="mt-3 rounded-lg bg-blue-900/40 p-3 text-xs text-blue-300">{msg}</div>
        )}

        <div className="mt-5 flex gap-3">
          <a
            href={`/api/files/${file.id}/download`}
            className="flex-1 rounded-xl bg-slate-700 py-2.5 text-center text-sm font-semibold text-white hover:bg-slate-600"
            download
          >
            ⬇ Herunterladen
          </a>
          <button
            onClick={handleReprocess}
            disabled={reprocessing}
            className={`flex-1 rounded-xl py-2.5 text-sm font-semibold text-white ${
              reprocessing ? 'cursor-not-allowed bg-slate-600' : 'bg-blue-600 hover:bg-blue-500'
            }`}
          >
            {reprocessing ? 'Startet…' : '↺ Neu verarbeiten'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      <span className={`break-all ${mono ? 'font-mono text-xs' : ''}`}>{value}</span>
    </div>
  );
}

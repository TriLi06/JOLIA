import { useEffect, useState } from 'react';
import api from '../services/api';

interface Job {
  id: string;
  file_id: string;
  file_name: string;
  job_type: string;
  status: string;
  created_at: string;
  finished_at: string | null;
  error_message: string | null;
}

const STATUS_COLOR: Record<string, string> = {
  done: 'bg-green-800 text-green-200',
  error: 'bg-red-800 text-red-200',
  running: 'bg-indigo-800 text-indigo-200',
  queued: 'bg-blue-800 text-blue-200',
  pending: 'bg-yellow-800 text-yellow-200',
};

function formatDate(iso: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleString('de-DE');
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 5000);
    return () => clearInterval(interval);
  }, []);

  async function fetchJobs() {
    try {
      const res = await api.get('/jobs');
      setJobs(res.data.items ?? res.data ?? []);
    } catch {
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }

  const runningCount = jobs.filter((j) => j.status === 'running' || j.status === 'queued').length;

  return (
    <div className="min-h-screen bg-slate-900 p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-bold text-white">Verarbeitungsaufträge</h1>
        {runningCount > 0 && (
          <span className="flex items-center gap-1 rounded-full bg-blue-800 px-3 py-0.5 text-xs font-semibold text-blue-200">
            <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />
            {runningCount} aktiv
          </span>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-10">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-600 border-t-blue-400" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="py-12 text-center text-slate-500">Keine Aufträge vorhanden.</div>
      ) : (
        <ul className="space-y-2">
          {jobs.map((job) => (
            <li key={job.id} className="rounded-xl bg-slate-800 p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <span className="truncate text-sm font-medium text-white">{job.file_name ?? job.file_id}</span>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_COLOR[job.status] ?? 'bg-slate-700 text-slate-300'}`}>
                  {job.status}
                </span>
              </div>
              <div className="space-y-0.5 text-xs text-slate-500">
                <p>Typ: {job.job_type}</p>
                <p>Erstellt: {formatDate(job.created_at)}</p>
                {job.finished_at && <p>Abgeschlossen: {formatDate(job.finished_at)}</p>}
              </div>
              {job.error_message && (
                <div className="mt-2 rounded-lg bg-red-900/40 p-2 text-xs text-red-300">
                  {job.error_message}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-4 text-center text-xs text-slate-600">Wird alle 5 Sekunden aktualisiert</p>
    </div>
  );
}

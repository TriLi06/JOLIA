import { useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';

interface SearchResult {
  id: string;
  file_id: string;
  text: string;
  score: number;
  file_name: string;
  content_type: string;
  collection: string;
  page: number | null;
  summary: string | null;
  thumbnail_url: string | null;
}

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setSearched(true);
    try {
      const res = await api.get('/search', { params: { q: query, n: 20 } });
      setResults(res.data.results ?? []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  function highlightText(text: string, q: string): string {
    if (!q.trim()) return text;
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return text.replace(new RegExp(`(${escaped})`, 'gi'), '<mark class="bg-yellow-600/40 rounded px-0.5">$1</mark>');
  }

  return (
    <div className="min-h-screen bg-slate-900 p-4">
      <h1 className="mb-4 text-lg font-bold text-white">Semantische Suche</h1>

      <form onSubmit={handleSearch} className="mb-4 flex gap-2">
        <input
          ref={inputRef}
          type="search"
          placeholder="Dokumente durchsuchen…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 rounded-xl bg-slate-800 px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          Suchen
        </button>
      </form>

      {loading && (
        <div className="flex justify-center py-10">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-600 border-t-blue-400" />
        </div>
      )}

      {!loading && searched && results.length === 0 && (
        <div className="py-12 text-center text-slate-500">Keine Ergebnisse für „{query}".</div>
      )}

      {!loading && results.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs text-slate-500">{results.length} Treffer</p>
          {results.map((r) => (
            <div key={r.id} className="rounded-xl bg-slate-800 p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <Link
                  to={`/files/${r.file_id}`}
                  className="truncate text-sm font-semibold text-blue-400 hover:underline"
                >
                  {r.file_name}
                </Link>
                <span className="shrink-0 text-xs text-slate-500">
                  {(r.score * 100).toFixed(0)}%
                </span>
              </div>
              {r.page && (
                <p className="mb-1 text-xs text-slate-500">Seite {r.page}</p>
              )}
              <p
                className="text-xs leading-relaxed text-slate-300 line-clamp-4"
                dangerouslySetInnerHTML={{ __html: highlightText(r.text, query) }}
              />
              {r.summary && (
                <p className="mt-2 text-xs text-slate-500 italic line-clamp-2">{r.summary}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

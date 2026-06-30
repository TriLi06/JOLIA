import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ReviewCard from '../components/ReviewCard';
import StatusToast from '../components/StatusToast';
import LoadingSpinner from '../components/LoadingSpinner';
import { useScanStore } from '../store/scanStore';
import { useUpload } from '../hooks/useUpload';

interface Toast {
  message: string;
  type: 'success' | 'error' | 'info';
}

export default function ReviewPage() {
  const navigate = useNavigate();
  const { guid, pages, clearSession, removeLastPage } = useScanStore();
  const { isUploading, progress, error: uploadError, successMessage, uploadSession } = useUpload();

  const [toast, setToast] = useState<Toast | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  // Leere Session → zurück zur Scan-Seite
  useEffect(() => {
    if (pages.length === 0 && !isUploading) {
      navigate('/scan');
    }
  }, [pages.length, isUploading, navigate]);

  // Upload-Fehler als Toast zeigen
  useEffect(() => {
    if (uploadError) {
      setToast({ message: uploadError, type: 'error' });
    }
  }, [uploadError]);

  // Erfolg: Toast zeigen, dann Session leeren
  useEffect(() => {
    if (successMessage) {
      setToast({ message: successMessage, type: 'success' });
      const timer = setTimeout(() => {
        clearSession();
        navigate('/dashboard');
      }, 2500);
      return () => clearTimeout(timer);
    }
  }, [successMessage, clearSession, navigate]);

  async function handleSave() {
    if (!guid || pages.length === 0) return;
    await uploadSession(guid, pages);
  }

  function handleCancel() {
    setShowConfirm(true);
  }

  function confirmCancel() {
    clearSession();
    navigate('/scan');
  }

  return (
    <div className="flex h-screen flex-col bg-slate-900">
      {/* Kopfzeile */}
      <div className="flex items-center justify-between border-b border-slate-700 bg-slate-800 px-4 py-3">
        <h1 className="text-base font-bold text-white">Erfasste Seiten</h1>
        <span className="rounded-full bg-blue-700 px-3 py-0.5 text-xs font-semibold text-white">
          {pages.length} Seite{pages.length !== 1 ? 'n' : ''}
        </span>
      </div>

      {/* Seiten-Raster */}
      <div className="flex-1 overflow-y-auto p-3">
        <div className="grid grid-cols-2 gap-3">
          {pages.map((page, i) => (
            <ReviewCard
              key={page.index}
              page={page}
              onRemove={() => {
                if (i === pages.length - 1) {
                  removeLastPage();
                } else {
                  // Alle Seiten ab diesem Index entfernen
                  removeLastPage();
                }
              }}
            />
          ))}
        </div>
      </div>

      {/* Untere Aktionsleiste */}
      <div className="flex items-center justify-between border-t border-slate-700 bg-slate-800 px-3 py-3 gap-2">
        <button
          onClick={handleCancel}
          className="flex-1 rounded-xl border border-red-700 py-3 text-sm font-semibold text-red-400 hover:bg-red-900/30"
        >
          ✗ Abbrechen
        </button>

        <button
          onClick={() => navigate('/scan')}
          className="flex-1 rounded-xl border border-blue-600 py-3 text-sm font-semibold text-blue-400 hover:bg-blue-900/30"
        >
          + Seite
        </button>

        <button
          onClick={handleSave}
          disabled={isUploading || pages.length === 0}
          className={`flex-1 rounded-xl py-3 text-sm font-semibold text-white ${
            isUploading
              ? 'cursor-not-allowed bg-slate-600'
              : 'bg-green-600 hover:bg-green-500'
          }`}
        >
          ✓ Speichern
        </button>
      </div>

      {/* Upload-Fortschritt */}
      {isUploading && (
        <LoadingSpinner
          progress={progress}
          label={`Dokument wird übertragen… (${progress}%)`}
        />
      )}

      {/* Toast */}
      {toast && (
        <StatusToast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      {/* Abbrechen-Bestätigung */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-xs rounded-2xl bg-slate-800 p-6 shadow-2xl">
            <h2 className="mb-2 text-center text-base font-semibold text-white">Scans verwerfen?</h2>
            <p className="mb-5 text-center text-sm text-slate-400">
              Alle {pages.length} Seite{pages.length !== 1 ? 'n' : ''} werden gelöscht.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 rounded-xl border border-slate-600 py-2 text-sm text-slate-300 hover:bg-slate-700"
              >
                Zurück
              </button>
              <button
                onClick={confirmCancel}
                className="flex-1 rounded-xl bg-red-600 py-2 text-sm font-semibold text-white hover:bg-red-500"
              >
                Verwerfen
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

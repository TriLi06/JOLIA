import { useState } from 'react';
import { ScannedPage } from '../store/scanStore';

interface ReviewCardProps {
  page: ScannedPage;
  onRemove: () => void;
}

export default function ReviewCard({ page, onRemove }: ReviewCardProps) {
  const [showModal, setShowModal] = useState(false);

  return (
    <>
      <div className="relative overflow-hidden rounded-xl shadow-lg">
        {/* Seitennummer-Badge */}
        <span className="absolute left-2 top-2 z-10 rounded-full bg-blue-600 px-2 py-0.5 text-xs font-bold text-white">
          {page.index}
        </span>

        {/* Entfernen-Button */}
        <button
          onClick={onRemove}
          className="absolute right-2 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-red-600 text-sm font-bold text-white shadow hover:bg-red-500"
          aria-label="Seite entfernen"
        >
          ×
        </button>

        {/* Vorschaubild */}
        <img
          src={page.previewUrl}
          alt={`Seite ${page.index}`}
          className="h-48 w-full cursor-pointer object-cover"
          onClick={() => setShowModal(true)}
        />
      </div>

      {/* Vollbild-Modal */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4"
          onClick={() => setShowModal(false)}
        >
          <div className="relative max-h-full max-w-full" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => setShowModal(false)}
              className="absolute -right-3 -top-3 flex h-8 w-8 items-center justify-center rounded-full bg-slate-700 text-lg font-bold text-white"
              aria-label="Schließen"
            >
              ×
            </button>
            <img
              src={page.previewUrl}
              alt={`Seite ${page.index} – Vollbild`}
              className="max-h-[90vh] max-w-[90vw] rounded-lg object-contain shadow-2xl"
            />
            <p className="mt-2 text-center text-sm text-slate-400">Seite {page.index}</p>
          </div>
        </div>
      )}
    </>
  );
}

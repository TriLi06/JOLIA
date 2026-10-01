import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import CameraView from '../components/CameraView';
import ScanButton from '../components/ScanButton';
import StatusToast from '../components/StatusToast';
import { useCamera } from '../hooks/useCamera';
import { useOpenCV } from '../hooks/useOpenCV';
import { useScanStore } from '../store/scanStore';
import { canvasToBlob, applyPerspectiveCorrection } from '../utils/imageUtils';

interface Toast {
  message: string;
  type: 'success' | 'error' | 'info';
}

export default function ScanPage() {
  const navigate = useNavigate();
  const videoRef = useRef<HTMLVideoElement>(null!);
  const canvasRef = useRef<HTMLCanvasElement>(null!);
  const containerRef = useRef<HTMLDivElement>(null);
  const stopLoopRef = useRef<(() => void) | null>(null);
  const captureInputRef = useRef<HTMLInputElement>(null);

  const [toast, setToast] = useState<Toast | null>(null);
  const [viewDimensions, setViewDimensions] = useState({ width: window.innerWidth, height: window.innerHeight });

  const { isReady, error: cameraError } = useCamera(videoRef);
  const { isLoaded: cvLoaded, detectedCorners, startDetectionLoop } = useOpenCV();
  const { pages, addPage } = useScanStore();

  // Fenstergröße verfolgen
  useEffect(() => {
    const update = () => {
      if (containerRef.current) {
        setViewDimensions({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight,
        });
      }
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  // Erkennungsschleife starten wenn Kamera & OpenCV bereit
  useEffect(() => {
    if (!isReady || !cvLoaded) return;

    const stop = startDetectionLoop(videoRef, canvasRef);
    stopLoopRef.current = stop;

    return () => {
      stop();
      stopLoopRef.current = null;
    };
  }, [isReady, cvLoaded, startDetectionLoop, videoRef, canvasRef]);

  const handleScan = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;

    // Erkennungsschleife kurz pausieren
    stopLoopRef.current?.();

    try {
      const offscreen = document.createElement('canvas');
      offscreen.width = video.videoWidth || 1920;
      offscreen.height = video.videoHeight || 1080;
      const ctx = offscreen.getContext('2d');
      if (!ctx) return;

      ctx.drawImage(video, 0, 0);

      let blob: Blob;

      if (detectedCorners && window.cv?.Mat) {
        try {
          const cv = window.cv;
          const src = cv.imread(offscreen);
          // Corners umrechnen: von Display-Koordinaten auf Video-Koordinaten
          const scaleX = offscreen.width / viewDimensions.width;
          const scaleY = offscreen.height / viewDimensions.height;
          const scaledCorners = detectedCorners.map(([x, y]) => [x * scaleX, y * scaleY]);

          const dst = applyPerspectiveCorrection(cv, src, scaledCorners);
          const dstCanvas = document.createElement('canvas');
          dstCanvas.width = dst.cols;
          dstCanvas.height = dst.rows;
          cv.imshow(dstCanvas, dst);
          src.delete();
          dst.delete();

          blob = await canvasToBlob(dstCanvas, 0.92);
        } catch {
          // Fallback auf Rohbild
          blob = await canvasToBlob(offscreen, 0.92);
          setToast({ message: 'Perspektivkorrektur fehlgeschlagen – Originalbild wird verwendet.', type: 'info' });
        }
      } else {
        blob = await canvasToBlob(offscreen, 0.92);
        if (!detectedCorners) {
          setToast({ message: 'Kein Dokument erkannt – Originalbild wird verwendet.', type: 'info' });
        }
      }

      addPage(blob);
      navigate('/scan/review');
    } finally {
      // Schleife wieder starten
      if (isReady && cvLoaded) {
        const stop = startDetectionLoop(videoRef, canvasRef);
        stopLoopRef.current = stop;
      }
    }
  }, [detectedCorners, viewDimensions, addPage, navigate, isReady, cvLoaded, startDetectionLoop, videoRef, canvasRef]);

  // Kamera-App des Geraets: liefert dieselben Seiten in denselben Stack wie die Live-Kamera.
  const handleCaptureFiles = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      event.target.value = '';
      if (files.length === 0) return;
      files.forEach((file) => addPage(file, 'pwa-capture'));
      navigate('/scan/review');
    },
    [addPage, navigate],
  );

  const captureInput = (
    <input
      ref={captureInputRef}
      type="file"
      accept="image/*"
      capture="environment"
      multiple
      hidden
      onChange={handleCaptureFiles}
    />
  );

  // Kamera-Fehler anzeigen
  if (cameraError) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-slate-900 p-6 text-center">
        <span className="mb-4 text-5xl">📷</span>
        <h2 className="mb-2 text-lg font-semibold text-red-400">Kamera nicht verfügbar</h2>
        <p className="mb-6 text-sm text-slate-400">{cameraError}</p>
        {captureInput}
        <button
          onClick={() => captureInputRef.current?.click()}
          className="mb-3 rounded-xl bg-blue-600 px-6 py-3 font-semibold text-white"
        >
          📸 Kamera-App verwenden
        </button>
        <button
          onClick={() => window.location.reload()}
          className="rounded-xl border border-slate-600 px-6 py-3 font-semibold text-slate-300"
        >
          Erneut versuchen
        </button>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex h-screen flex-col bg-black">
      {/* Kopfzeile */}
      <div className="flex items-center justify-between bg-slate-900/80 px-4 py-3 backdrop-blur-sm">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-slate-400 hover:text-white"
          aria-label="Zurück"
        >
          ← Zurück
        </button>
        <h1 className="text-base font-bold tracking-wide text-white">DocScan</h1>
        {pages.length > 0 && (
          <span className="rounded-full bg-blue-700 px-3 py-0.5 text-xs font-semibold text-white">
            Seite {pages.length + 1}
          </span>
        )}
        {pages.length === 0 && <div className="w-16" />}
      </div>

      {/* Kamera-Ansicht */}
      <CameraView
        videoRef={videoRef}
        canvasRef={canvasRef}
        corners={detectedCorners}
        viewDimensions={viewDimensions}
      />

      {/* Ladeoverlay: Kamera/OpenCV wird initialisiert */}
      {(!isReady || !cvLoaded) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-600 border-t-blue-400" />
          <p className="mt-3 text-sm text-slate-300">
            {!isReady ? 'Kamera wird initialisiert…' : 'OpenCV wird geladen…'}
          </p>
        </div>
      )}

      {/* Untere Aktionsleiste */}
      <div className="flex items-center justify-between bg-slate-900/90 px-6 py-4 backdrop-blur-sm">
        <button
          onClick={() => navigate('/scan/review')}
          disabled={pages.length === 0}
          className={`rounded-xl px-4 py-2 text-sm font-medium ${
            pages.length > 0
              ? 'bg-slate-700 text-white hover:bg-slate-600'
              : 'cursor-not-allowed bg-slate-800 text-slate-600'
          }`}
        >
          Prüfen ({pages.length})
        </button>

        <ScanButton onScan={handleScan} disabled={!isReady} />

        {captureInput}
        <button
          onClick={() => captureInputRef.current?.click()}
          className="rounded-xl bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600"
          title="Seiten mit der Kamera-App des Geräts aufnehmen"
        >
          📸 Kamera-App
        </button>
      </div>

      {/* Toast-Benachrichtigung */}
      {toast && (
        <StatusToast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}

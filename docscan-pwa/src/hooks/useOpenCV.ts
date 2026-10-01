import { useEffect, useRef, useState, RefObject, useCallback } from 'react';
import { ERROR_MESSAGES } from '../utils/errorMessages';

interface UseOpenCVResult {
  isLoaded: boolean;
  error: string | null;
  detectedCorners: number[][] | null;
  startDetectionLoop: (
    videoRef: RefObject<HTMLVideoElement>,
    canvasRef: RefObject<HTMLCanvasElement>,
  ) => () => void;
}

declare global {
  interface Window {
    cv: any;
  }
}

export function useOpenCV(): UseOpenCVResult {
  const [isLoaded, setIsLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detectedCorners, setDetectedCorners] = useState<number[][] | null>(null);

  useEffect(() => {
    if (window.cv && window.cv.Mat) {
      setIsLoaded(true);
      return;
    }

    // Prüfen ob Skript bereits eingefügt
    if (document.getElementById('opencv-script')) {
      // Warten bis geladen
      const interval = setInterval(() => {
        if (window.cv && window.cv.Mat) {
          setIsLoaded(true);
          clearInterval(interval);
        }
      }, 200);
      return () => clearInterval(interval);
    }

    const script = document.createElement('script');
    script.id = 'opencv-script';
    script.src = '/opencv/opencv.js';
    script.async = true;
    script.onerror = () => setError(ERROR_MESSAGES.OPENCV_LOAD_ERROR);

    script.onload = () => {
      if (window.cv) {
        if (window.cv.getBuildInformation) {
          // Bereits initialisiert
          setIsLoaded(true);
        } else {
          window.cv.onRuntimeInitialized = () => setIsLoaded(true);
        }
      } else {
        setError(ERROR_MESSAGES.OPENCV_LOAD_ERROR);
      }
    };

    document.head.appendChild(script);
  }, []);

  const startDetectionLoop = useCallback(
    (
      videoRef: RefObject<HTMLVideoElement>,
      canvasRef: RefObject<HTMLCanvasElement>,
    ): (() => void) => {
      let animFrameId: number;
      let running = true;

      const offscreen = document.createElement('canvas');

      const detect = () => {
        if (!running) return;

        const video = videoRef.current;
        const canvas = canvasRef.current;

        if (!video || !canvas || video.readyState < 2 || !window.cv?.Mat) {
          animFrameId = requestAnimationFrame(detect);
          return;
        }

        const vw = video.videoWidth;
        const vh = video.videoHeight;
        if (!vw || !vh) {
          animFrameId = requestAnimationFrame(detect);
          return;
        }

        offscreen.width = vw;
        offscreen.height = vh;
        const ctx = offscreen.getContext('2d');
        if (!ctx) { animFrameId = requestAnimationFrame(detect); return; }

        ctx.drawImage(video, 0, 0, vw, vh);

        const cv = window.cv;
        let src: any, gray: any, blurred: any, edges: any, contours: any, hierarchy: any;

        try {
          src = cv.imread(offscreen);
          gray = new cv.Mat();
          blurred = new cv.Mat();
          edges = new cv.Mat();
          contours = new cv.MatVector();
          hierarchy = new cv.Mat();

          cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);
          cv.GaussianBlur(gray, blurred, new cv.Size(5, 5), 0);
          cv.Canny(blurred, edges, 75, 200);

          cv.findContours(edges, contours, hierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);

          const frameArea = vw * vh;
          let bestContour: number[][] | null = null;
          let bestArea = 0;

          for (let i = 0; i < contours.size(); i++) {
            const cnt = contours.get(i);
            const peri = cv.arcLength(cnt, true);
            const approx = new cv.Mat();
            cv.approxPolyDP(cnt, approx, 0.02 * peri, true);

            if (approx.rows === 4) {
              const area = Math.abs(cv.contourArea(approx));
              if (area > frameArea * 0.1 && area > bestArea) {
                bestArea = area;
                const pts: number[][] = [];
                for (let r = 0; r < 4; r++) {
                  const x = approx.data32S[r * 2];
                  const y = approx.data32S[r * 2 + 1];
                  // Normalisieren auf Canvas-Anzeigegröße
                  pts.push([
                    (x / vw) * canvas.offsetWidth,
                    (y / vh) * canvas.offsetHeight,
                  ]);
                }
                bestContour = pts;
              }
              approx.delete();
            } else {
              approx.delete();
            }

            cnt.delete();
          }

          setDetectedCorners(bestContour);
        } catch {
          // Stille Fehler bei einzelnen Frames ignorieren
        } finally {
          src?.delete();
          gray?.delete();
          blurred?.delete();
          edges?.delete();
          contours?.delete();
          hierarchy?.delete();
        }

        animFrameId = requestAnimationFrame(detect);
      };

      animFrameId = requestAnimationFrame(detect);

      return () => {
        running = false;
        cancelAnimationFrame(animFrameId);
      };
    },
    [],
  );

  return { isLoaded, error, detectedCorners, startDetectionLoop };
}

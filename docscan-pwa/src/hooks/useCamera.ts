import { useEffect, useRef, useState, RefObject } from 'react';
import { ERROR_MESSAGES } from '../utils/errorMessages';

interface UseCameraResult {
  isReady: boolean;
  error: string | null;
  stream: MediaStream | null;
}

export function useCamera(videoRef: RefObject<HTMLVideoElement>): UseCameraResult {
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function startCamera() {
      try {
        const mediaStream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
            // @ts-expect-error advanced constraints nicht im Standard-TS-Typ
            advanced: [{ focusMode: 'continuous' }],
          },
          audio: false,
        });

        if (cancelled) {
          mediaStream.getTracks().forEach((t) => t.stop());
          return;
        }

        streamRef.current = mediaStream;
        setStream(mediaStream);

        if (videoRef.current) {
          videoRef.current.srcObject = mediaStream;
          videoRef.current.onloadedmetadata = () => {
            if (!cancelled) setIsReady(true);
          };
        }
      } catch (err: any) {
        if (cancelled) return;
        const msg = ERROR_MESSAGES[err.name as string] ?? ERROR_MESSAGES.UNKNOWN_ERROR;
        setError(msg);
      }
    }

    startCamera();

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, [videoRef]);

  return { isReady, error, stream };
}

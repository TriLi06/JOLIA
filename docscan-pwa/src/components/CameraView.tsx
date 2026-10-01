import { RefObject } from 'react';
import DocumentOverlay from './DocumentOverlay';

interface CameraViewProps {
  videoRef: RefObject<HTMLVideoElement>;
  canvasRef: RefObject<HTMLCanvasElement>;
  corners: number[][] | null;
  viewDimensions: { width: number; height: number };
}

export default function CameraView({ videoRef, canvasRef, corners, viewDimensions }: CameraViewProps) {
  return (
    <div className="relative flex-1 overflow-hidden bg-black">
      {/* Video-Feed */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="absolute inset-0 h-full w-full object-cover"
      />

      {/* Verstecktes Canvas für Frame-Verarbeitung */}
      <canvas ref={canvasRef} className="hidden" />

      {/* Dokumenterkennung-Overlay */}
      <DocumentOverlay
        corners={corners}
        width={viewDimensions.width || window.innerWidth}
        height={viewDimensions.height || window.innerHeight}
      />
    </div>
  );
}

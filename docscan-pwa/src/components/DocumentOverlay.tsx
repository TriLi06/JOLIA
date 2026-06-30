interface DocumentOverlayProps {
  corners: number[][] | null;
  width: number;
  height: number;
}

export default function DocumentOverlay({ corners, width, height }: DocumentOverlayProps) {
  const hasDoc = corners !== null && corners.length === 4;

  const polygonPoints = hasDoc
    ? corners.map((c) => `${c[0]},${c[1]}`).join(' ')
    : '';

  // Führungs-Rechteck: 70 % der Anzeige, zentriert
  const guideW = width * 0.7;
  const guideH = height * 0.75;
  const guideX = (width - guideW) / 2;
  const guideY = (height - guideH) / 2;

  return (
    <div className="pointer-events-none absolute inset-0">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        xmlns="http://www.w3.org/2000/svg"
        className="absolute inset-0"
      >
        {hasDoc ? (
          <polygon
            points={polygonPoints}
            fill="rgba(34,197,94,0.12)"
            stroke="#22c55e"
            strokeWidth="3"
            className="animate-pulse-slow"
          />
        ) : (
          <rect
            x={guideX}
            y={guideY}
            width={guideW}
            height={guideH}
            fill="none"
            stroke="#f59e0b"
            strokeWidth="2"
            strokeDasharray="12 6"
          />
        )}
      </svg>

      {/* Status-Text */}
      <div className="absolute left-0 right-0 top-6 flex justify-center">
        {hasDoc ? (
          <span className="rounded-full bg-green-900/70 px-4 py-1 text-sm font-semibold text-green-300">
            Dokument erkannt ✓
          </span>
        ) : (
          <span className="rounded-full bg-yellow-900/70 px-4 py-1 text-sm font-semibold text-yellow-300">
            Dokument wird gesucht…
          </span>
        )}
      </div>
    </div>
  );
}

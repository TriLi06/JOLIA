interface LoadingSpinnerProps {
  progress?: number;
  label?: string;
}

export default function LoadingSpinner({ progress, label }: LoadingSpinnerProps) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/70 backdrop-blur-sm">
      {/* Kreis-Spinner */}
      <div className="relative h-20 w-20">
        <svg
          className="h-20 w-20 animate-spin"
          viewBox="0 0 80 80"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <circle cx="40" cy="40" r="34" stroke="#1e293b" strokeWidth="8" />
          <path
            d="M40 6 A34 34 0 0 1 74 40"
            stroke="#3b82f6"
            strokeWidth="8"
            strokeLinecap="round"
          />
        </svg>
        {progress !== undefined && (
          <span className="absolute inset-0 flex items-center justify-center text-sm font-semibold text-white">
            {progress}%
          </span>
        )}
      </div>

      {label && (
        <p className="mt-4 text-center text-sm text-slate-300">{label}</p>
      )}
    </div>
  );
}

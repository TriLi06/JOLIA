interface ScanButtonProps {
  onScan: () => void;
  disabled?: boolean;
}

export default function ScanButton({ onScan, disabled = false }: ScanButtonProps) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-xs font-medium uppercase tracking-widest text-slate-400">
        Scannen
      </span>
      <button
        onClick={onScan}
        disabled={disabled}
        className={`flex h-20 w-20 items-center justify-center rounded-full shadow-xl transition-transform active:scale-90 ${
          disabled
            ? 'cursor-not-allowed bg-slate-600 opacity-50'
            : 'bg-blue-500 hover:bg-blue-400'
        }`}
        aria-label="Seite scannen"
      >
        {/* Kamera-Icon (SVG) */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="white"
          className="h-9 w-9"
        >
          <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" />
          <path
            fillRule="evenodd"
            d="M8.5 3.5A1.5 1.5 0 0 1 10 2h4a1.5 1.5 0 0 1 1.5 1.5H19A2 2 0 0 1 21 5.5v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2h3.5Zm9.5 2H6a.5.5 0 0 0-.5.5v12a.5.5 0 0 0 .5.5h12a.5.5 0 0 0 .5-.5v-12a.5.5 0 0 0-.5-.5Z"
            clipRule="evenodd"
          />
        </svg>
      </button>
    </div>
  );
}

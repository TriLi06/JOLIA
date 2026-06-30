import { useEffect, useRef, useState } from 'react';

interface StatusToastProps {
  message: string;
  type: 'success' | 'error' | 'info';
  onClose: () => void;
}

export default function StatusToast({ message, type, onClose }: StatusToastProps) {
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Trigger slide-up animation
    const frame = requestAnimationFrame(() => setVisible(true));
    timerRef.current = setTimeout(() => {
      setVisible(false);
      setTimeout(onClose, 300);
    }, 5000);

    return () => {
      cancelAnimationFrame(frame);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [onClose]);

  const colors: Record<string, string> = {
    success: 'bg-green-700 border-green-500',
    error: 'bg-red-800 border-red-600',
    info: 'bg-blue-700 border-blue-500',
  };

  const icons: Record<string, string> = {
    success: '✅',
    error: '❌',
    info: 'ℹ️',
  };

  return (
    <div
      className={`fixed bottom-20 left-1/2 z-50 w-[90vw] max-w-sm -translate-x-1/2 rounded-xl border px-4 py-3 shadow-xl transition-all duration-300 ${colors[type]} ${
        visible ? 'translate-y-0 opacity-100' : 'translate-y-8 opacity-0'
      }`}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-lg">{icons[type]}</span>
        <p className="flex-1 text-sm leading-snug text-white">{message}</p>
        <button
          onClick={() => { setVisible(false); setTimeout(onClose, 300); }}
          className="ml-1 text-white/70 hover:text-white"
          aria-label="Schließen"
        >
          ×
        </button>
      </div>
    </div>
  );
}

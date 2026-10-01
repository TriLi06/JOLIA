import { create } from 'zustand';
import { generateGuid } from '../utils/guid';

export interface ScannedPage {
  index: number;       // 1-basiert
  blob: Blob;
  previewUrl: string;  // URL.createObjectURL
}

export interface ScanSession {
  guid: string | null;
  pages: ScannedPage[];
  title: string;
  source: string;
}

interface ScanStore extends ScanSession {
  addPage: (blob: Blob, source?: string) => void;
  setTitle: (title: string) => void;
  clearSession: () => void;
  removeLastPage: () => void;
}

export const useScanStore = create<ScanStore>((set, get) => ({
  guid: null,
  pages: [],
  title: '',
  source: 'pwa-live',

  addPage: (blob: Blob, source?: string) => {
    const { guid, pages } = get();
    const newGuid = guid ?? generateGuid();
    const previewUrl = URL.createObjectURL(blob);
    const newPage: ScannedPage = {
      index: pages.length + 1,
      blob,
      previewUrl,
    };
    set({
      guid: newGuid,
      pages: [...pages, newPage],
      ...(source && pages.length === 0 ? { source } : {}),
    });
  },

  setTitle: (title: string) => set({ title }),

  clearSession: () => {
    const { pages } = get();
    pages.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    set({ guid: null, pages: [], title: '', source: 'pwa-live' });
  },

  removeLastPage: () => {
    const { pages } = get();
    if (pages.length === 0) return;
    const last = pages[pages.length - 1];
    URL.revokeObjectURL(last.previewUrl);
    set({ pages: pages.slice(0, -1) });
  },
}));

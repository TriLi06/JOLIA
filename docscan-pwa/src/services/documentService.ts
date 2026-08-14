import api from './api';
import { ScannedPage } from '../store/scanStore';

/**
 * Lädt alle gescannten Seiten als Multipart-Upload zum JOLIA Docs-Backend hoch.
 */
export async function uploadSession(
  guid: string,
  pages: ScannedPage[],
  onProgress: (percent: number) => void,
): Promise<void> {
  const formData = new FormData();

  for (const page of pages) {
    const paddedIndex = String(page.index).padStart(2, '0');
    const filename = `${guid}_${paddedIndex}.jpg`;
    formData.append('files', page.blob, filename);
  }

  await api.post('/scan/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
    onUploadProgress: (evt) => {
      if (evt.total && evt.total > 0) {
        onProgress(Math.round((evt.loaded / evt.total) * 100));
      }
    },
  });
}

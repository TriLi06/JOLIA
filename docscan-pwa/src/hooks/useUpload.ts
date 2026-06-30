import { useState, useCallback } from 'react';
import { ScannedPage } from '../store/scanStore';
import { ERROR_MESSAGES, SUCCESS_MESSAGES } from '../utils/errorMessages';
import { uploadSession as apiUpload } from '../services/documentService';

interface UseUploadResult {
  isUploading: boolean;
  progress: number;
  error: string | null;
  successMessage: string | null;
  uploadSession: (guid: string, pages: ScannedPage[]) => Promise<boolean>;
  reset: () => void;
}

export function useUpload(): UseUploadResult {
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const uploadSession = useCallback(async (guid: string, pages: ScannedPage[]): Promise<boolean> => {
    setIsUploading(true);
    setProgress(0);
    setError(null);
    setSuccessMessage(null);

    try {
      await apiUpload(guid, pages, (n) => setProgress(n));
      setSuccessMessage(SUCCESS_MESSAGES.UPLOAD_SUCCESS(guid, pages.length));
      setProgress(100);
      return true;
    } catch (err: any) {
      let msg = ERROR_MESSAGES.UNKNOWN_ERROR;
      if (err.code === 'ECONNABORTED') {
        msg = ERROR_MESSAGES.UPLOAD_TIMEOUT;
      } else if (err.response) {
        if (err.response.status === 401) msg = ERROR_MESSAGES.UPLOAD_UNAUTHORIZED;
        else if (err.response.status >= 500) msg = ERROR_MESSAGES.UPLOAD_SERVER_ERROR;
      } else if (err.request) {
        msg = ERROR_MESSAGES.UPLOAD_NETWORK_ERROR;
      }
      setError(msg);
      return false;
    } finally {
      setIsUploading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setIsUploading(false);
    setProgress(0);
    setError(null);
    setSuccessMessage(null);
  }, []);

  return { isUploading, progress, error, successMessage, uploadSession, reset };
}

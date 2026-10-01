export const ERROR_MESSAGES: Record<string, string> = {
  NotAllowedError: 'Kamera-Zugriff verweigert. Bitte Berechtigungen in den Browser-Einstellungen aktivieren.',
  NotFoundError: 'Keine Kamera gefunden. Stellen Sie sicher, dass ein Gerät angeschlossen ist.',
  OverconstrainedError: 'Die gewünschte Auflösung wird von dieser Kamera nicht unterstützt.',
  NotReadableError: 'Kamera wird bereits von einer anderen Anwendung verwendet.',
  UPLOAD_TIMEOUT: 'Upload-Timeout. Bitte Netzwerkverbindung prüfen und erneut versuchen.',
  UPLOAD_SERVER_ERROR: 'Serverfehler beim Speichern der Dokumente. Bitte später erneut versuchen.',
  UPLOAD_NETWORK_ERROR: 'Keine Verbindung zum Server. Bitte Netzwerk prüfen.',
  UPLOAD_UNAUTHORIZED: 'Nicht autorisiert. Bitte erneut anmelden.',
  OPENCV_LOAD_ERROR: 'OpenCV-Bibliothek konnte nicht geladen werden. Kantenerkennung nicht verfügbar.',
  UNKNOWN_ERROR: 'Unbekannter Fehler. Bitte die App neu starten.',
};

export const SUCCESS_MESSAGES = {
  UPLOAD_SUCCESS: (guid: string, count: number) =>
    `✅ ${count} Seite(n) erfolgreich hochgeladen. Dokument-ID: ${guid.substring(0, 8)}…`,
};

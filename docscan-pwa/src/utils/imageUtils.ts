/**
 * Konvertiert ein Canvas-Element in einen JPEG-Blob.
 */
export function canvasToBlob(canvas: HTMLCanvasElement, quality = 0.92): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error('Canvas-zu-Blob-Konvertierung fehlgeschlagen'));
        }
      },
      'image/jpeg',
      quality,
    );
  });
}

/**
 * Ordnet vier Punkte: oben-links, oben-rechts, unten-rechts, unten-links.
 */
function orderCorners(pts: number[][]): number[][] {
  // Sortiere nach y-Wert (oben/unten trennen)
  const sorted = [...pts].sort((a, b) => a[1] - b[1]);
  const top = sorted.slice(0, 2).sort((a, b) => a[0] - b[0]);    // kleinere x = links
  const bottom = sorted.slice(2).sort((a, b) => a[0] - b[0]);

  return [top[0], top[1], bottom[1], bottom[0]]; // TL, TR, BR, BL
}

/**
 * Wendet eine perspektivische Korrektur auf die Quellmatrix an.
 * Ausgabegröße: 794 × 1123 (A4 bei 96 dpi).
 */
export function applyPerspectiveCorrection(
  cv: any,
  srcMat: any,
  corners: number[][],
): any {
  const A4_W = 794;
  const A4_H = 1123;

  const ordered = orderCorners(corners);

  // Quell-Punkte (detektierte Ecken)
  const srcPts = cv.matFromArray(4, 1, cv.CV_32FC2, [
    ordered[0][0], ordered[0][1],
    ordered[1][0], ordered[1][1],
    ordered[2][0], ordered[2][1],
    ordered[3][0], ordered[3][1],
  ]);

  // Ziel-Punkte (A4-Rechteck)
  const dstPts = cv.matFromArray(4, 1, cv.CV_32FC2, [
    0, 0,
    A4_W, 0,
    A4_W, A4_H,
    0, A4_H,
  ]);

  const M = cv.getPerspectiveTransform(srcPts, dstPts);
  const dst = new cv.Mat();
  const dsize = new cv.Size(A4_W, A4_H);

  cv.warpPerspective(srcMat, dst, M, dsize, cv.INTER_LINEAR, cv.BORDER_CONSTANT, new cv.Scalar());

  srcPts.delete();
  dstPts.delete();
  M.delete();

  return dst;
}

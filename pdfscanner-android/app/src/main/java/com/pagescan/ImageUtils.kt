package com.pagescan

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.graphics.PointF
import androidx.camera.core.ImageProxy
import org.opencv.android.Utils
import org.opencv.core.Mat
import org.opencv.core.MatOfPoint2f
import org.opencv.core.Point
import org.opencv.core.Size
import org.opencv.imgproc.Imgproc
import java.io.File
import java.io.FileOutputStream
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.roundToInt

object ImageUtils {

    /** JPEG-Frame der Aufnahme in eine aufrecht gedrehte Bitmap wandeln. */
    fun toUprightBitmap(image: ImageProxy): Bitmap {
        val buffer = image.planes[0].buffer
        val bytes = ByteArray(buffer.remaining())
        buffer.get(bytes)
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            ?: error("Aufnahme konnte nicht dekodiert werden")

        val rotation = image.imageInfo.rotationDegrees
        if (rotation == 0) return bitmap

        val matrix = Matrix().apply { postRotate(rotation.toFloat()) }
        val rotated = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        if (rotated !== bitmap) bitmap.recycle()
        return rotated
    }

    /**
     * Entzerrt [source] auf das durch [corners] (normalisiert, 0..1) beschriebene Viereck.
     * Ohne Ecken wird das Bild unverändert zurückgegeben.
     */
    fun cropAndDewarp(source: Bitmap, corners: List<PointF>?): Bitmap {
        if (corners == null || corners.size != 4) return source

        val src = corners.map {
            Point(
                (it.x * source.width).toDouble().coerceIn(0.0, source.width - 1.0),
                (it.y * source.height).toDouble().coerceIn(0.0, source.height - 1.0),
            )
        }
        val widthPx = max(distance(src[0], src[1]), distance(src[3], src[2])).roundToInt()
        val heightPx = max(distance(src[0], src[3]), distance(src[1], src[2])).roundToInt()
        if (widthPx < MIN_EDGE || heightPx < MIN_EDGE) return source

        val srcMat = MatOfPoint2f(src[0], src[1], src[2], src[3])
        val dstMat = MatOfPoint2f(
            Point(0.0, 0.0),
            Point(widthPx - 1.0, 0.0),
            Point(widthPx - 1.0, heightPx - 1.0),
            Point(0.0, heightPx - 1.0),
        )
        val transform = Imgproc.getPerspectiveTransform(srcMat, dstMat)
        val input = Mat()
        val output = Mat()
        return try {
            Utils.bitmapToMat(source, input)
            Imgproc.warpPerspective(
                input, output, transform,
                Size(widthPx.toDouble(), heightPx.toDouble()),
                Imgproc.INTER_LINEAR
            )
            val result = Bitmap.createBitmap(widthPx, heightPx, Bitmap.Config.ARGB_8888)
            Utils.matToBitmap(output, result)
            source.recycle()
            result
        } catch (t: Throwable) {
            source
        } finally {
            srcMat.release()
            dstMat.release()
            transform.release()
            input.release()
            output.release()
        }
    }

    fun writeJpeg(bitmap: Bitmap, target: File, quality: Int = 88): File {
        target.parentFile?.mkdirs()
        FileOutputStream(target).use { out ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
        }
        return target
    }

    /** Speicherschonendes Laden einer Vorschau. */
    fun decodePreview(file: File, maxSize: Int = 1400): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / sample > maxSize) sample *= 2
        return BitmapFactory.decodeFile(
            file.absolutePath,
            BitmapFactory.Options().apply { inSampleSize = sample }
        )
    }

    private fun distance(a: Point, b: Point) = hypot(a.x - b.x, a.y - b.y)

    private const val MIN_EDGE = 32
}

package com.pagescan

import android.graphics.PointF
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import org.opencv.core.Core
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.core.MatOfPoint
import org.opencv.core.MatOfPoint2f
import org.opencv.core.Point
import org.opencv.core.Size
import org.opencv.imgproc.Imgproc
import kotlin.math.abs
import kotlin.math.max

/**
 * Sucht im Live-Bild das größte konvexe Viereck (= vermutete Dokumentseite).
 * Liefert `null`, wenn kein plausibles Dokument gefunden wurde.
 */
class DocumentAnalyzer(private val onResult: (Detection?) -> Unit) : ImageAnalysis.Analyzer {

    override fun analyze(image: ImageProxy) {
        val result = try {
            detect(image)
        } catch (t: Throwable) {
            null
        } finally {
            image.close()
        }
        onResult(result)
    }

    private fun detect(image: ImageProxy): Detection? {
        val sensorGray = image.toGrayMat()
        val upright = sensorGray.rotateUpright(image.imageInfo.rotationDegrees)
        if (upright !== sensorGray) sensorGray.release()

        val work = Mat()
        val longSide = max(upright.width(), upright.height())
        val scale = if (longSide > WORK_SIZE) WORK_SIZE.toDouble() / longSide else 1.0
        if (scale < 1.0) {
            Imgproc.resize(upright, work, Size(), scale, scale, Imgproc.INTER_AREA)
        } else {
            upright.copyTo(work)
        }
        val aspect = upright.width().toFloat() / upright.height().toFloat()
        upright.release()

        val edges = Mat()
        val kernel = Imgproc.getStructuringElement(Imgproc.MORPH_RECT, Size(3.0, 3.0))
        val contours = ArrayList<MatOfPoint>()
        val hierarchy = Mat()
        try {
            Imgproc.GaussianBlur(work, work, Size(5.0, 5.0), 0.0)
            Imgproc.Canny(work, edges, 40.0, 120.0)
            Imgproc.dilate(edges, edges, kernel)
            Imgproc.findContours(
                edges, contours, hierarchy,
                Imgproc.RETR_LIST, Imgproc.CHAIN_APPROX_SIMPLE
            )

            val frameArea = (work.width() * work.height()).toDouble()
            var best: List<Point>? = null
            var bestArea = frameArea * MIN_AREA_RATIO

            for (contour in contours) {
                val area = Imgproc.contourArea(contour)
                if (area < bestArea) continue

                val curve = MatOfPoint2f(*contour.toArray())
                val approx = MatOfPoint2f()
                val peri = Imgproc.arcLength(curve, true)
                Imgproc.approxPolyDP(curve, approx, 0.02 * peri, true)
                val points = approx.toArray()
                curve.release()
                approx.release()

                if (points.size != 4) continue
                val poly = MatOfPoint(*points)
                val convex = Imgproc.isContourConvex(poly)
                poly.release()
                if (!convex) continue
                if (!hasPlausibleAngles(points)) continue

                best = points.toList()
                bestArea = area
            }

            val corners = best?.let { orderCorners(it) } ?: return null
            return Detection(
                corners = corners.map {
                    PointF(
                        (it.x / work.width()).toFloat().coerceIn(0f, 1f),
                        (it.y / work.height()).toFloat().coerceIn(0f, 1f),
                    )
                },
                frameAspect = aspect,
            )
        } finally {
            contours.forEach { it.release() }
            hierarchy.release()
            kernel.release()
            edges.release()
            work.release()
        }
    }

    /** Verwirft stark verzerrte Vierecke (Innenwinkel müssen grob rechtwinklig sein). */
    private fun hasPlausibleAngles(points: Array<Point>): Boolean {
        for (i in points.indices) {
            val prev = points[(i + 3) % 4]
            val cur = points[i]
            val next = points[(i + 1) % 4]
            val ax = prev.x - cur.x
            val ay = prev.y - cur.y
            val bx = next.x - cur.x
            val by = next.y - cur.y
            val denom = Math.hypot(ax, ay) * Math.hypot(bx, by)
            if (denom == 0.0) return false
            val cos = (ax * bx + ay * by) / denom
            if (abs(cos) > MAX_CORNER_COS) return false
        }
        return true
    }

    /** Sortiert nach oben-links, oben-rechts, unten-rechts, unten-links. */
    private fun orderCorners(points: List<Point>): List<Point> {
        val bySum = points.sortedBy { it.x + it.y }
        val byDiff = points.sortedBy { it.y - it.x }
        val topLeft = bySum.first()
        val bottomRight = bySum.last()
        val topRight = byDiff.first()
        val bottomLeft = byDiff.last()
        return listOf(topLeft, topRight, bottomRight, bottomLeft)
    }

    private companion object {
        const val WORK_SIZE = 480
        const val MIN_AREA_RATIO = 0.12
        const val MAX_CORNER_COS = 0.5 // entspricht 60°..120°
    }
}

/** Y-Ebene eines YUV_420_888-Frames als Graustufen-Mat. */
private fun ImageProxy.toGrayMat(): Mat {
    val plane = planes[0]
    val buffer = plane.buffer
    val rowStride = plane.rowStride
    val data = ByteArray(width * height)
    if (rowStride == width) {
        buffer.get(data, 0, data.size)
    } else {
        val row = ByteArray(rowStride)
        for (y in 0 until height) {
            buffer.position(y * rowStride)
            buffer.get(row, 0, minOf(rowStride, buffer.remaining()))
            System.arraycopy(row, 0, data, y * width, width)
        }
    }
    val mat = Mat(height, width, CvType.CV_8UC1)
    mat.put(0, 0, data)
    return mat
}

private fun Mat.rotateUpright(degrees: Int): Mat {
    val code = when (((degrees % 360) + 360) % 360) {
        90 -> Core.ROTATE_90_CLOCKWISE
        180 -> Core.ROTATE_180
        270 -> Core.ROTATE_90_COUNTERCLOCKWISE
        else -> return this
    }
    val out = Mat()
    Core.rotate(this, out, code)
    return out
}

package com.pagescan

import android.graphics.PointF
import android.graphics.RectF

/**
 * Erkannter Dokumentrahmen.
 *
 * [corners] sind auf 0..1 normalisiert und beziehen sich auf das aufrecht gedrehte
 * Kamerabild (gleiche Orientierung wie die Vorschau), Reihenfolge: oben-links,
 * oben-rechts, unten-rechts, unten-links.
 */
data class Detection(
    val corners: List<PointF>,
    val frameAspect: Float,
) {
    val centerX: Float get() = corners.map { it.x }.average().toFloat()
    val centerY: Float get() = corners.map { it.y }.average().toFloat()
}

/**
 * Bereich, den ein Bild mit [aspect] in einer View der Größe [viewWidth] x [viewHeight]
 * bei FIT_CENTER-Skalierung einnimmt.
 */
fun fitCenterRect(viewWidth: Float, viewHeight: Float, aspect: Float): RectF {
    if (viewWidth <= 0f || viewHeight <= 0f || aspect <= 0f) {
        return RectF(0f, 0f, viewWidth, viewHeight)
    }
    return if (viewWidth / viewHeight > aspect) {
        val w = viewHeight * aspect
        val left = (viewWidth - w) / 2f
        RectF(left, 0f, left + w, viewHeight)
    } else {
        val h = viewWidth / aspect
        val top = (viewHeight - h) / 2f
        RectF(0f, top, viewWidth, top + h)
    }
}

/** Rechnet normalisierte Ecken in View-Koordinaten um. */
fun Detection.toViewPoints(viewWidth: Float, viewHeight: Float): List<PointF> {
    val rect = fitCenterRect(viewWidth, viewHeight, frameAspect)
    return corners.map {
        PointF(rect.left + it.x * rect.width(), rect.top + it.y * rect.height())
    }
}

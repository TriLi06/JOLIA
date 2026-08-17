package com.pagescan

import android.content.ContentValues
import android.content.Context
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.pdf.PdfDocument
import android.net.Uri
import android.provider.MediaStore
import java.io.File
import java.io.OutputStream
import kotlin.math.min

/** Erzeugt aus den Seitenbildern ein mehrseitiges PDF im Ordner "Downloads/PageScan". */
object PdfWriter {

    private const val A4_WIDTH_PT = 595
    private const val A4_HEIGHT_PT = 842

    fun save(context: Context, pages: List<File>, displayName: String): Uri {
        require(pages.isNotEmpty()) { "Keine Seiten vorhanden" }

        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
            put(MediaStore.MediaColumns.MIME_TYPE, "application/pdf")
            put(MediaStore.MediaColumns.RELATIVE_PATH, "Download/PageScan")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: error("PDF konnte nicht angelegt werden")

        try {
            resolver.openOutputStream(uri)?.use { write(pages, it) }
                ?: error("PDF konnte nicht geschrieben werden")
        } catch (t: Throwable) {
            resolver.delete(uri, null, null)
            throw t
        }

        values.clear()
        values.put(MediaStore.MediaColumns.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
        return uri
    }

    private fun write(pages: List<File>, out: OutputStream) {
        val document = PdfDocument()
        val paint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
        try {
            pages.forEachIndexed { index, file ->
                val bitmap = ImageUtils.decodePreview(file, maxSize = 2200) ?: return@forEachIndexed
                val portrait = bitmap.height >= bitmap.width
                val pageWidth = if (portrait) A4_WIDTH_PT else A4_HEIGHT_PT
                val pageHeight = if (portrait) A4_HEIGHT_PT else A4_WIDTH_PT

                val page = document.startPage(
                    PdfDocument.PageInfo.Builder(pageWidth, pageHeight, index + 1).create()
                )
                val scale = min(
                    pageWidth.toFloat() / bitmap.width,
                    pageHeight.toFloat() / bitmap.height
                )
                val drawWidth = bitmap.width * scale
                val drawHeight = bitmap.height * scale
                val left = (pageWidth - drawWidth) / 2f
                val top = (pageHeight - drawHeight) / 2f
                page.canvas.drawBitmap(
                    bitmap,
                    Rect(0, 0, bitmap.width, bitmap.height),
                    RectF(left, top, left + drawWidth, top + drawHeight),
                    paint,
                )
                document.finishPage(page)
                bitmap.recycle()
            }
            document.writeTo(out)
        } finally {
            document.close()
        }
    }
}

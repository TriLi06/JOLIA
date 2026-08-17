package com.pagescan

import android.app.Application
import android.graphics.PointF
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executor
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

sealed interface ScanStep {
    /** Live-Kamera, wartet auf Auslösen. */
    data object Camera : ScanStep

    /** Zuletzt aufgenommene Seite wird zur Bestätigung gezeigt. */
    data class Review(val page: File) : ScanStep
}

class ScanViewModel(application: Application) : AndroidViewModel(application) {

    private val pagesDir = File(application.cacheDir, "pages")

    private val _detection = MutableStateFlow<Detection?>(null)
    val detection = _detection.asStateFlow()

    private val _step = MutableStateFlow<ScanStep>(ScanStep.Camera)
    val step = _step.asStateFlow()

    private val _pageCount = MutableStateFlow(0)
    val pageCount = _pageCount.asStateFlow()

    private val _busy = MutableStateFlow(false)
    val busy = _busy.asStateFlow()

    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val messages = _messages.asSharedFlow()

    private val pages = mutableListOf<File>()
    private var lastDetectionAt = 0L

    var imageCapture: ImageCapture? = null

    init {
        pagesDir.deleteRecursively()
        pagesDir.mkdirs()
    }

    /** Wird vom Analyzer-Thread aufgerufen; hält den Rahmen kurz stabil, um Flackern zu vermeiden. */
    fun onDetection(detection: Detection?) {
        val now = System.currentTimeMillis()
        if (detection != null) {
            lastDetectionAt = now
            _detection.value = detection
        } else if (now - lastDetectionAt > DETECTION_HOLD_MS) {
            _detection.value = null
        }
    }

    fun capture(executor: Executor) {
        val capture = imageCapture ?: return
        if (_busy.value) return
        _busy.value = true

        val corners = _detection.value?.corners
        viewModelScope.launch {
            try {
                val proxy = capture.takePictureSuspending(executor)
                val page = withContext(Dispatchers.Default) {
                    try {
                        val upright = ImageUtils.toUprightBitmap(proxy)
                        val cropped = ImageUtils.cropAndDewarp(upright, corners)
                        val target = File(pagesDir, "page_${System.currentTimeMillis()}.jpg")
                        ImageUtils.writeJpeg(cropped, target)
                        cropped.recycle()
                        target
                    } finally {
                        proxy.close()
                    }
                }
                _step.value = ScanStep.Review(page)
            } catch (t: Throwable) {
                _messages.tryEmit("Aufnahme fehlgeschlagen")
            } finally {
                _busy.value = false
            }
        }
    }

    /** Aktuelle Seite übernehmen und zurück zur Kamera. */
    fun keepPage() {
        val current = _step.value as? ScanStep.Review ?: return
        pages += current.page
        _pageCount.value = pages.size
        _step.value = ScanStep.Camera
    }

    /** Aktuelle Seite verwerfen. */
    fun discardPage() {
        val current = _step.value as? ScanStep.Review ?: return
        current.page.delete()
        _step.value = ScanStep.Camera
    }

    /** Aktuelle Seite übernehmen und PDF schreiben. */
    fun finishDocument() {
        val current = _step.value as? ScanStep.Review
        if (current != null) {
            pages += current.page
            _pageCount.value = pages.size
        }
        if (pages.isEmpty()) return
        if (_busy.value) return

        _busy.value = true
        val snapshot = pages.toList()
        viewModelScope.launch {
            try {
                val name = "Scan_" + SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US)
                    .format(Date()) + ".pdf"
                withContext(Dispatchers.IO) {
                    PdfWriter.save(getApplication<Application>(), snapshot, name)
                }
                _messages.tryEmit("Gespeichert: Download/PageScan/$name")
                reset()
            } catch (t: Throwable) {
                _messages.tryEmit("PDF konnte nicht gespeichert werden")
            } finally {
                _busy.value = false
                _step.value = ScanStep.Camera
            }
        }
    }

    private fun reset() {
        pages.forEach { it.delete() }
        pages.clear()
        _pageCount.value = 0
    }

    override fun onCleared() {
        super.onCleared()
        pagesDir.deleteRecursively()
    }

    private companion object {
        const val DETECTION_HOLD_MS = 700L
    }
}

private suspend fun ImageCapture.takePictureSuspending(executor: Executor): ImageProxy =
    suspendCancellableCoroutine { cont: CancellableContinuation<ImageProxy> ->
        takePicture(executor, object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                if (cont.isActive) cont.resume(image) else image.close()
            }

            override fun onError(exception: ImageCaptureException) {
                cont.resumeWithException(exception)
            }
        })
    }

/** Mittelpunkt des Rahmens in View-Koordinaten – für den Autofokus. */
fun Detection.focusPoint(viewWidth: Float, viewHeight: Float): PointF {
    val rect = fitCenterRect(viewWidth, viewHeight, frameAspect)
    return PointF(rect.left + centerX * rect.width(), rect.top + centerY * rect.height())
}

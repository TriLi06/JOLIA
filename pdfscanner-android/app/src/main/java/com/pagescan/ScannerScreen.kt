package com.pagescan

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraControl
import androidx.camera.core.CameraSelector
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.math.abs

@Composable
fun ScannerApp(viewModel: ScanViewModel = viewModel()) {
    val context = LocalContext.current
    var hasPermission by remember { mutableStateOf(context.hasCameraPermission()) }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> hasPermission = granted }

    LaunchedEffect(Unit) {
        if (!hasPermission) permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(viewModel) {
        viewModel.messages.collect { snackbarHostState.showSnackbar(it) }
    }

    Scaffold(
        containerColor = Color.Black,
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        Box(
            Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            if (hasPermission) {
                ScannerContent(viewModel)
            } else {
                PermissionPane { permissionLauncher.launch(Manifest.permission.CAMERA) }
            }
        }
    }
}

@Composable
private fun PermissionPane(onRequest: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = stringResource(R.string.camera_permission_rationale),
            color = Color.White,
            textAlign = TextAlign.Center,
        )
        Button(onClick = onRequest, modifier = Modifier.padding(top = 16.dp)) {
            Text(stringResource(R.string.grant_permission))
        }
    }
}

@Composable
private fun ScannerContent(viewModel: ScanViewModel) {
    val context = LocalContext.current
    val step by viewModel.step.collectAsState()
    val busy by viewModel.busy.collectAsState()
    val pageCount by viewModel.pageCount.collectAsState()
    val analysisExecutor = rememberAnalysisExecutor()
    val mainExecutor = remember(context) { ContextCompat.getMainExecutor(context) }

    Box(Modifier.fillMaxSize()) {
        // Kamera bleibt gebunden, damit die Vorschau nach dem Review sofort weiterläuft.
        CameraPane(viewModel, analysisExecutor, Modifier.fillMaxSize())

        val current = step
        if (current is ScanStep.Review) {
            PageReview(current, Modifier.fillMaxSize())
        }

        Column(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .background(Color(0xAA000000))
                .navigationBarsPadding()
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            if (pageCount > 0) {
                Text(
                    text = "$pageCount Seite(n) erfasst",
                    color = Color.White,
                    modifier = Modifier.padding(bottom = 12.dp),
                )
            }
            when (current) {
                is ScanStep.Camera -> CameraControls(
                    enabled = !busy,
                    showFinish = pageCount > 0,
                    onScan = { viewModel.capture(mainExecutor) },
                    onFinish = viewModel::finishDocument,
                )

                is ScanStep.Review -> ReviewControls(
                    enabled = !busy,
                    onNextPage = viewModel::keepPage,
                    onFinish = viewModel::finishDocument,
                    onDiscard = viewModel::discardPage,
                )
            }
        }

        if (busy) {
            CircularProgressIndicator(
                modifier = Modifier.align(Alignment.Center),
                color = Color.White,
            )
        }
    }
}

@Composable
private fun CameraControls(
    enabled: Boolean,
    showFinish: Boolean,
    onScan: () -> Unit,
    onFinish: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Button(
            onClick = onScan,
            enabled = enabled,
            modifier = Modifier
                .weight(1f)
                .height(56.dp),
        ) {
            Text(stringResource(R.string.scan))
        }
        if (showFinish) {
            OutlinedButton(
                onClick = onFinish,
                enabled = enabled,
                modifier = Modifier
                    .weight(1f)
                    .height(56.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
            ) {
                Text(stringResource(R.string.finish))
            }
        }
    }
}

@Composable
private fun ReviewControls(
    enabled: Boolean,
    onNextPage: () -> Unit,
    onFinish: () -> Unit,
    onDiscard: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Button(
                onClick = onNextPage,
                enabled = enabled,
                modifier = Modifier
                    .weight(1f)
                    .height(56.dp),
            ) {
                Text(stringResource(R.string.next_page))
            }
            Button(
                onClick = onFinish,
                enabled = enabled,
                modifier = Modifier
                    .weight(1f)
                    .height(56.dp),
            ) {
                Text(stringResource(R.string.finish))
            }
        }
        OutlinedButton(
            onClick = onDiscard,
            enabled = enabled,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
        ) {
            Text(stringResource(R.string.discard))
        }
    }
}

@Composable
private fun PageReview(step: ScanStep.Review, modifier: Modifier = Modifier) {
    val bitmap = remember(step.page) { ImageUtils.decodePreview(step.page) }
    Box(modifier.background(Color.Black), contentAlignment = Alignment.Center) {
        bitmap?.let {
            Image(
                bitmap = it.asImageBitmap(),
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .fillMaxSize()
                    .statusBarsPadding()
                    .padding(bottom = 176.dp),
            )
        }
    }
}

@Composable
private fun CameraPane(
    viewModel: ScanViewModel,
    analysisExecutor: ExecutorService,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember {
        PreviewView(context).apply {
            scaleType = PreviewView.ScaleType.FIT_CENTER
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
        }
    }
    var cameraControl by remember { mutableStateOf<CameraControl?>(null) }

    val provider by produceState<ProcessCameraProvider?>(initialValue = null, context) {
        value = runCatching { context.awaitCameraProvider() }.getOrNull()
    }

    LaunchedEffect(provider, lifecycleOwner) {
        val cameraProvider = provider ?: return@LaunchedEffect

        val resolution = ResolutionSelector.Builder()
            .setAspectRatioStrategy(AspectRatioStrategy.RATIO_4_3_FALLBACK_AUTO_STRATEGY)
            .build()

        val preview = Preview.Builder()
            .setResolutionSelector(resolution)
            .build()
            .apply { setSurfaceProvider(previewView.surfaceProvider) }

        val analysis = ImageAnalysis.Builder()
            .setResolutionSelector(resolution)
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
            .build()
            .apply { setAnalyzer(analysisExecutor, DocumentAnalyzer(viewModel::onDetection)) }

        val capture = ImageCapture.Builder()
            .setResolutionSelector(resolution)
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
            .build()

        runCatching {
            cameraProvider.unbindAll()
            cameraProvider.bindToLifecycle(
                lifecycleOwner,
                CameraSelector.DEFAULT_BACK_CAMERA,
                preview,
                analysis,
                capture,
            )
        }.onSuccess { camera ->
            viewModel.imageCapture = capture
            cameraControl = camera.cameraControl
        }
    }

    DisposableEffect(provider) {
        onDispose {
            provider?.unbindAll()
            viewModel.imageCapture = null
        }
    }

    AutoFocusOnDocument(viewModel, previewView, cameraControl)

    Box(modifier) {
        AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())
        DocumentOverlay(viewModel, Modifier.fillMaxSize())
    }
}

@Composable
private fun DocumentOverlay(viewModel: ScanViewModel, modifier: Modifier = Modifier) {
    val detection by viewModel.detection.collectAsState()
    Canvas(modifier) {
        val current = detection ?: return@Canvas
        val points = current.toViewPoints(size.width, size.height)
        val path = Path().apply {
            moveTo(points[0].x, points[0].y)
            for (i in 1 until points.size) lineTo(points[i].x, points[i].y)
            close()
        }
        drawPath(path, color = Color(0x334DD0E1))
        drawPath(path, color = Color(0xFF4DD0E1), style = Stroke(width = 6f))
        points.forEach { drawCircle(Color(0xFF4DD0E1), radius = 10f, center = Offset(it.x, it.y)) }
    }
}

/** Fokussiert regelmäßig auf die Mitte des erkannten Dokuments. */
@Composable
private fun AutoFocusOnDocument(
    viewModel: ScanViewModel,
    previewView: PreviewView,
    cameraControl: CameraControl?,
) {
    LaunchedEffect(cameraControl) {
        val control = cameraControl ?: return@LaunchedEffect
        var lastX = Float.NaN
        var lastY = Float.NaN
        var lastFocusAt = 0L
        while (isActive) {
            delay(700)
            val detection = viewModel.detection.value ?: continue
            val width = previewView.width.toFloat()
            val height = previewView.height.toFloat()
            if (width <= 0f || height <= 0f) continue

            val now = System.currentTimeMillis()
            val moved = lastX.isNaN() ||
                abs(detection.centerX - lastX) > 0.05f ||
                abs(detection.centerY - lastY) > 0.05f
            if (!moved && now - lastFocusAt < 4000L) continue

            val target = detection.focusPoint(width, height)
            val point = previewView.meteringPointFactory.createPoint(target.x, target.y)
            val action = FocusMeteringAction.Builder(
                point,
                FocusMeteringAction.FLAG_AF or FocusMeteringAction.FLAG_AE
            ).setAutoCancelDuration(3, TimeUnit.SECONDS).build()
            runCatching { control.startFocusAndMetering(action) }

            lastX = detection.centerX
            lastY = detection.centerY
            lastFocusAt = now
        }
    }
}

@Composable
private fun rememberAnalysisExecutor(): ExecutorService {
    val executor = remember { Executors.newSingleThreadExecutor() }
    DisposableEffect(executor) { onDispose { executor.shutdown() } }
    return executor
}

private fun Context.hasCameraPermission() =
    ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
        PackageManager.PERMISSION_GRANTED

private suspend fun Context.awaitCameraProvider(): ProcessCameraProvider =
    suspendCancellableCoroutine { cont ->
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            try {
                cont.resume(future.get())
            } catch (t: Throwable) {
                cont.resumeWithException(t)
            }
        }, ContextCompat.getMainExecutor(this))
    }

package com.pagescan

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import org.opencv.android.OpenCVLoader

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        if (!OpenCVLoader.initLocal()) {
            Toast.makeText(this, "Bilderkennung nicht verfügbar", Toast.LENGTH_LONG).show()
        }

        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                ScannerApp()
            }
        }
    }
}

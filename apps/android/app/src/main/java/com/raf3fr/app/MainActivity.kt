package com.raf3fr.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.content.ContextCompat
import com.raf3fr.app.theme.RAF3FRTheme
import com.raf3fr.app.ui.RAF3FRApp

class MainActivity : ComponentActivity() {
    private val viewModel: RAF3FRViewModel by viewModels()

    private val sourcePicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let {
            persistReadPermission(it)
            val document = documentInfo(it)
            viewModel.selectSource(it, document.first, document.second)
        }
    }

    private val donorPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let {
            persistReadPermission(it)
            val document = documentInfo(it)
            viewModel.selectDonor(it, document.first)
        }
    }

    private val outputPicker =
        registerForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
            uri?.let {
                persistWritePermission(it)
                viewModel.startConversion(it, documentInfo(it).first)
            }
        }

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.rgb(11, 11, 11)),
        )
        setContent {
            RAF3FRTheme {
                RAF3FRApp(
                    viewModel = viewModel,
                    onChooseSource = { sourcePicker.launch(arrayOf("*/*")) },
                    onChooseDonor = { donorPicker.launch(arrayOf("*/*")) },
                    onChooseOutput = {
                        requestNotificationPermission()
                        outputPicker.launch(viewModel.suggestedOutputName())
                    },
                    onOpenOutput = { uri ->
                        startActivity(
                            Intent(Intent.ACTION_VIEW).apply {
                                setDataAndType(uri, "application/octet-stream")
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            },
                        )
                    },
                )
            }
        }
    }

    private fun persistReadPermission(uri: Uri) {
        runCatching {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    private fun persistWritePermission(uri: Uri) {
        runCatching {
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
            )
        }
    }

    private fun documentInfo(uri: Uri): Pair<String, Long?> {
        var name = uri.lastPathSegment ?: "RAW"
        var size: Long? = null
        val cursor: Cursor? = contentResolver.query(
            uri,
            arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE),
            null,
            null,
            null,
        )
        cursor?.use {
            if (it.moveToFirst()) {
                val nameIndex = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = it.getColumnIndex(OpenableColumns.SIZE)
                if (nameIndex >= 0) name = it.getString(nameIndex) ?: name
                if (sizeIndex >= 0 && !it.isNull(sizeIndex)) size = it.getLong(sizeIndex)
            }
        }
        return name to size
    }

    private fun requestNotificationPermission() {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}

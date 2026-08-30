package com.raf3fr.app.worker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.StatFs
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import com.raf3fr.app.MainActivity
import com.raf3fr.app.R
import com.raf3fr.app.engine.NativeEngine
import java.io.File
import java.io.FileOutputStream
import java.util.zip.GZIPInputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.job
import kotlinx.coroutines.withContext
import org.json.JSONObject

class ConversionWorker(
    appContext: Context,
    parameters: WorkerParameters,
) : CoroutineWorker(appContext, parameters) {
    private val jobId = id.toString()

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val sourceUri = inputData.stringUri(KEY_SOURCE_URI) ?: return@withContext failure("invalid_source")
        val donorUri = inputData.stringUri(KEY_DONOR_URI)
        val outputUri = inputData.stringUri(KEY_OUTPUT_URI) ?: return@withContext failure("invalid_output")
        val options = inputData.getString(KEY_OPTIONS) ?: return@withContext failure("invalid_options")
        val outputName = inputData.getString(KEY_OUTPUT_NAME) ?: "output.3FR"
        val language = inputData.getString(KEY_LANGUAGE) ?: "EN"

        val jobDirectory = File(applicationContext.filesDir, "jobs/$jobId")
        jobDirectory.deleteRecursively()
        check(jobDirectory.mkdirs()) { "cannot create private job directory" }
        val source = File(jobDirectory, "source.raf")
        val donor = File(jobDirectory, "donor.3fr")
        val output = File(jobDirectory, "output.3fr")

        try {
            setForeground(notification(STAGE_COPYING, language))
            ensureStorage(sourceUri, donorUri)
            copyFromUri(sourceUri, source, 0)
            if (donorUri == null) {
                copyBundledDonor(donor, source.length())
            } else {
                copyFromUri(donorUri, donor, source.length())
            }
            currentCoroutineContext().ensureActive()
            if (isStopped) return@withContext Result.failure(stageData(STAGE_CANCELLED))

            setProgress(stageData(STAGE_CONVERTING))
            setForeground(notification(STAGE_CONVERTING, language))
            val cancellationHandle = currentCoroutineContext().job.invokeOnCompletion { cause ->
                if (cause is kotlinx.coroutines.CancellationException) NativeEngine.cancel(jobId)
            }
            val conversion = try {
                JSONObject(NativeEngine.convert(source.path, donor.path, output.path, options, jobId))
            } finally {
                cancellationHandle.dispose()
            }
            if (!conversion.optBoolean("ok")) {
                return@withContext failure(conversion.optString("error", "native_conversion_failed"))
            }
            currentCoroutineContext().ensureActive()

            setProgress(stageData(STAGE_VERIFYING))
            setForeground(notification(STAGE_VERIFYING, language))
            val verification = JSONObject(NativeEngine.verify(donor.path, output.path, source.path))
            if (!verification.optBoolean("ok")) {
                return@withContext failure(verification.optString("error", "native_verification_failed"))
            }

            setProgress(stageData(STAGE_SAVING))
            setForeground(notification(STAGE_SAVING, language))
            copyToUri(output, outputUri)
            preserveManifest(File(output.path + ".json"), outputName)

            Result.success(
                Data.Builder()
                    .putString(KEY_STAGE, STAGE_COMPLETE)
                    .putString(KEY_OUTPUT_URI, outputUri.toString())
                    .putString(KEY_OUTPUT_NAME, outputName)
                    .putString(
                        KEY_OUTPUT_SHA256,
                        verification.optJSONObject("result")?.optString("output_sha256"),
                    )
                    .build(),
            )
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            NativeEngine.cancel(jobId)
            throw cancelled
        } catch (error: Throwable) {
            failure(error.message ?: error.javaClass.simpleName)
        } finally {
            jobDirectory.deleteRecursively()
        }
    }

    private fun ensureStorage(sourceUri: Uri, donorUri: Uri?) {
        val sourceSize = documentSize(sourceUri) ?: FALLBACK_SOURCE_BYTES
        val donorSize = donorUri?.let(::documentSize) ?: FALLBACK_DONOR_BYTES
        val required = sourceSize + donorSize * 2 + STORAGE_HEADROOM_BYTES
        val available = StatFs(applicationContext.filesDir.path).availableBytes
        check(available >= required) { "insufficient_storage" }
    }

    private suspend fun copyBundledDonor(target: File, baseBytes: Long) {
        GZIPInputStream(applicationContext.assets.open(BUNDLED_DONOR_ASSET)).use { input ->
            FileOutputStream(target).use { output ->
                val buffer = ByteArray(COPY_BUFFER_BYTES)
                var copied = 0L
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                    copied += count
                    if (copied % PROGRESS_INTERVAL_BYTES < COPY_BUFFER_BYTES) {
                        setProgress(stageData(STAGE_COPYING, baseBytes + copied))
                    }
                }
                output.fd.sync()
            }
        }
    }

    private suspend fun copyFromUri(uri: Uri, target: File, baseBytes: Long) {
        applicationContext.contentResolver.openInputStream(uri).use { input ->
            checkNotNull(input) { "cannot_open_input" }
            FileOutputStream(target).use { output ->
                val buffer = ByteArray(COPY_BUFFER_BYTES)
                var copied = 0L
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                    copied += count
                    if (copied % PROGRESS_INTERVAL_BYTES < COPY_BUFFER_BYTES) {
                        setProgress(stageData(STAGE_COPYING, baseBytes + copied))
                    }
                }
                output.fd.sync()
            }
        }
    }

    private suspend fun copyToUri(source: File, uri: Uri) {
        applicationContext.contentResolver.openOutputStream(uri, "w").use { output ->
            checkNotNull(output) { "cannot_open_output" }
            source.inputStream().use { input ->
                val buffer = ByteArray(COPY_BUFFER_BYTES)
                var copied = 0L
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val count = input.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                    copied += count
                    if (copied % PROGRESS_INTERVAL_BYTES < COPY_BUFFER_BYTES) {
                        setProgress(stageData(STAGE_SAVING, copied))
                    }
                }
                output.flush()
            }
        }
    }

    private fun preserveManifest(manifest: File, outputName: String) {
        if (!manifest.isFile) return
        val history = File(applicationContext.filesDir, "history")
        check(history.exists() || history.mkdirs()) { "cannot_create_history" }
        manifest.copyTo(File(history, "$jobId-${outputName}.json"), overwrite = false)
    }

    private fun documentSize(uri: Uri): Long? = applicationContext.contentResolver
        .query(uri, arrayOf(android.provider.OpenableColumns.SIZE), null, null, null)
        ?.use { cursor ->
            val index = cursor.getColumnIndex(android.provider.OpenableColumns.SIZE)
            if (index >= 0 && cursor.moveToFirst() && !cursor.isNull(index)) cursor.getLong(index) else null
        }

    private fun notification(stage: String, language: String): ForegroundInfo {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "RAF3FR conversion", NotificationManager.IMPORTANCE_LOW),
        )
        val intent = PendingIntent.getActivity(
            applicationContext,
            0,
            Intent(applicationContext, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("RAF3FR")
            .setContentText(notificationStage(stage, language))
            .setContentIntent(intent)
            .setOngoing(true)
            .setSilent(true)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    private fun failure(message: String): Result = Result.failure(
        Data.Builder().putString(KEY_STAGE, STAGE_FAILED).putString(KEY_ERROR, message).build(),
    )

    private fun stageData(stage: String, bytes: Long = 0): Data = Data.Builder()
        .putString(KEY_STAGE, stage)
        .putLong(KEY_BYTES, bytes)
        .build()

    private fun Data.stringUri(key: String): Uri? = getString(key)?.let(Uri::parse)

    private fun notificationStage(stage: String, language: String): String {
        val chinese = language == "ZH"
        return when (stage) {
            STAGE_COPYING -> if (chinese) "读取文件" else "Reading files"
            STAGE_CONVERTING -> if (chinese) "转换 RAW" else "Converting RAW"
            STAGE_VERIFYING -> if (chinese) "校验 3FR" else "Verifying 3FR"
            STAGE_SAVING -> if (chinese) "保存文件" else "Saving file"
            else -> if (chinese) "准备中" else "Preparing"
        }
    }

    companion object {
        const val KEY_SOURCE_URI = "source_uri"
        const val KEY_DONOR_URI = "donor_uri"
        const val KEY_OUTPUT_URI = "output_uri"
        const val KEY_OUTPUT_NAME = "output_name"
        const val KEY_OPTIONS = "options"
        const val KEY_LANGUAGE = "language"
        const val KEY_STAGE = "stage"
        const val KEY_BYTES = "bytes"
        const val KEY_ERROR = "error"
        const val KEY_OUTPUT_SHA256 = "output_sha256"

        const val STAGE_QUEUED = "queued"
        const val STAGE_COPYING = "copying"
        const val STAGE_CONVERTING = "converting"
        const val STAGE_VERIFYING = "verifying"
        const val STAGE_SAVING = "saving"
        const val STAGE_COMPLETE = "complete"
        const val STAGE_FAILED = "failed"
        const val STAGE_CANCELLED = "cancelled"

        private const val CHANNEL_ID = "raf3fr_conversion"
        private const val NOTIFICATION_ID = 3107
        private const val COPY_BUFFER_BYTES = 1024 * 1024
        private const val PROGRESS_INTERVAL_BYTES = 8L * 1024 * 1024
        private const val STORAGE_HEADROOM_BYTES = 128L * 1024 * 1024
        private const val FALLBACK_SOURCE_BYTES = 180L * 1024 * 1024
        private const val FALLBACK_DONOR_BYTES = 220L * 1024 * 1024
        private const val BUNDLED_DONOR_ASSET = "sanitized_x2d_template.bin"
    }
}

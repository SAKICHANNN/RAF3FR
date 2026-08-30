package com.raf3fr.app

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.Data
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.raf3fr.app.data.AppPreferences
import com.raf3fr.app.model.ConversionSettings
import com.raf3fr.app.model.JobPhase
import com.raf3fr.app.model.JobState
import com.raf3fr.app.model.Language
import com.raf3fr.app.model.SelectedDocument
import com.raf3fr.app.worker.ConversionWorker
import java.util.UUID
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

class RAF3FRViewModel(application: Application) : AndroidViewModel(application) {
    private val preferences = AppPreferences(application)
    private val workManager = WorkManager.getInstance(application)
    private var workObserver: Job? = null

    private val _settings = MutableStateFlow(ConversionSettings())
    val settings: StateFlow<ConversionSettings> = _settings.asStateFlow()

    private val _source = MutableStateFlow<SelectedDocument?>(null)
    val source: StateFlow<SelectedDocument?> = _source.asStateFlow()

    private val _job = MutableStateFlow(JobState())
    val job: StateFlow<JobState> = _job.asStateFlow()

    init {
        viewModelScope.launch {
            preferences.settings.collectLatest { _settings.value = it }
        }
        viewModelScope.launch {
            preferences.source.collectLatest { _source.value = it }
        }
        viewModelScope.launch {
            preferences.activeWorkId.collectLatest { id ->
                if (id != null && id != _job.value.id) observeWork(UUID.fromString(id))
            }
        }
    }

    fun selectSource(uri: Uri, name: String, size: Long?) {
        _source.value = SelectedDocument(uri, name, size)
        if (!_job.value.isRunning) _job.value = JobState()
        viewModelScope.launch { preferences.setSource(uri.toString(), name, size) }
    }

    fun selectDonor(uri: Uri, name: String) {
        viewModelScope.launch { preferences.setDonor(uri.toString(), name) }
    }

    fun useBundledDonor() {
        viewModelScope.launch { preferences.clearDonor() }
    }

    fun setLanguage(language: Language) {
        _settings.value = _settings.value.copy(language = language)
        viewModelScope.launch { preferences.setLanguage(language) }
    }

    fun updateSettings(transform: (ConversionSettings) -> ConversionSettings) {
        val updated = transform(_settings.value)
        _settings.value = updated
        viewModelScope.launch { preferences.updateSettings(updated) }
    }

    fun suggestedOutputName(): String {
        val stem = source.value?.name?.substringBeforeLast('.')?.ifBlank { "RAF3FR" } ?: "RAF3FR"
        return "$stem-X2D.3FR"
    }

    fun startConversion(outputUri: Uri, outputName: String) {
        val source = source.value ?: return
        val settings = settings.value
        if (_job.value.isRunning) return
        val request = OneTimeWorkRequestBuilder<ConversionWorker>()
            .setInputData(
                Data.Builder()
                    .putString(ConversionWorker.KEY_SOURCE_URI, source.uri.toString())
                    .putString(ConversionWorker.KEY_DONOR_URI, settings.donorUri)
                    .putString(ConversionWorker.KEY_OUTPUT_URI, outputUri.toString())
                    .putString(ConversionWorker.KEY_OUTPUT_NAME, outputName)
                    .putString(ConversionWorker.KEY_OPTIONS, settings.nativeJson())
                    .putString(ConversionWorker.KEY_LANGUAGE, settings.language.name)
                    .build(),
            )
            .addTag(WORK_TAG)
            .build()
        _job.value = JobState(
            id = request.id.toString(),
            phase = JobPhase.QUEUED,
            outputUri = outputUri,
            outputName = outputName,
        )
        workManager.enqueue(request)
        viewModelScope.launch { preferences.setActiveWorkId(request.id.toString()) }
        observeWork(request.id)
    }

    fun cancel() {
        _job.value.id?.let { workManager.cancelWorkById(UUID.fromString(it)) }
    }

    private fun observeWork(id: UUID) {
        workObserver?.cancel()
        workObserver = viewModelScope.launch {
            workManager.getWorkInfoByIdFlow(id).collectLatest { info ->
                if (info == null) return@collectLatest
                val data = if (info.state.isFinished) info.outputData else info.progress
                val stage = data.getString(ConversionWorker.KEY_STAGE)
                val prior = _job.value
                val phase = when (info.state) {
                    WorkInfo.State.ENQUEUED, WorkInfo.State.BLOCKED -> JobPhase.QUEUED
                    WorkInfo.State.RUNNING -> phaseFromStage(stage)
                    WorkInfo.State.SUCCEEDED -> JobPhase.COMPLETE
                    WorkInfo.State.CANCELLED -> JobPhase.CANCELLED
                    WorkInfo.State.FAILED -> JobPhase.FAILED
                }
                _job.value = JobState(
                    id = id.toString(),
                    phase = phase,
                    transferredBytes = data.getLong(ConversionWorker.KEY_BYTES, prior.transferredBytes),
                    outputUri = data.getString(ConversionWorker.KEY_OUTPUT_URI)?.let(Uri::parse)
                        ?: prior.outputUri,
                    outputName = data.getString(ConversionWorker.KEY_OUTPUT_NAME) ?: prior.outputName,
                    detail = data.getString(ConversionWorker.KEY_ERROR),
                )
                if (info.state.isFinished) preferences.setActiveWorkId(null)
            }
        }
    }

    private fun phaseFromStage(stage: String?): JobPhase = when (stage) {
        ConversionWorker.STAGE_COPYING -> JobPhase.COPYING
        ConversionWorker.STAGE_CONVERTING -> JobPhase.CONVERTING
        ConversionWorker.STAGE_VERIFYING -> JobPhase.VERIFYING
        ConversionWorker.STAGE_SAVING -> JobPhase.SAVING
        else -> JobPhase.QUEUED
    }

    companion object {
        const val WORK_TAG = "raf3fr_conversion"
    }
}

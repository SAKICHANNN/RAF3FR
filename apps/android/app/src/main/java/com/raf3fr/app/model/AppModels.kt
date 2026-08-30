package com.raf3fr.app.model

import android.net.Uri

enum class Language { ZH, EN }

enum class WhiteBalanceMode(val wire: String) {
    AUTO("auto"),
    AS_SHOT("as-shot"),
    DONOR("donor"),
}

enum class SensorMappingMode(val wire: String) {
    IDENTITY("identity"),
    D65("d65-dnglab-bootstrap"),
    ADAPTIVE("wb-adaptive-bootstrap"),
}

enum class PreviewMode(val wire: String) {
    SOURCE("source"),
    DONOR("donor"),
}

enum class DonorLensMode(val wire: String) {
    NEUTRALIZE("neutralize"),
    PRESERVE("preserve"),
}

enum class DistortionModel(val wire: String) {
    NATIVE_MATCH("native-match"),
    LEGACY_IN_BOUNDS("legacy-in-bounds"),
}

enum class IsoPolicy(val wire: String) {
    NEAREST_X2D("nearest-x2d"),
    HNNR_STABLE("hnnr-stable"),
    CAPTURE("capture"),
}

data class ConversionSettings(
    val language: Language = Language.EN,
    val donorUri: String? = null,
    val donorName: String? = null,
    val whiteBalance: WhiteBalanceMode = WhiteBalanceMode.AUTO,
    val sensorMapping: SensorMappingMode = SensorMappingMode.ADAPTIVE,
    val preview: PreviewMode = PreviewMode.SOURCE,
    val donorLens: DonorLensMode = DonorLensMode.NEUTRALIZE,
    val distortionModel: DistortionModel = DistortionModel.NATIVE_MATCH,
    val isoPolicy: IsoPolicy = IsoPolicy.HNNR_STABLE,
    val inverseCalibration: Boolean = false,
    val distortionStrength: Float = 1f,
    val chromaticAberrationStrength: Float = 1f,
    val vignettingStrength: Float = 0f,
) {
    fun nativeJson(): String = """{
        "white_balance":"${whiteBalance.wire}",
        "sensor_mapping":"${sensorMapping.wire}",
        "preview":"${preview.wire}",
        "donor_lens_correction":"${donorLens.wire}",
        "distortion_model":"${distortionModel.wire}",
        "iso_policy":"${isoPolicy.wire}",
        "inverse_x2d_calibration":$inverseCalibration,
        "distortion_strength":$distortionStrength,
        "chromatic_aberration_strength":$chromaticAberrationStrength,
        "vignetting_strength":$vignettingStrength
    }""".trimIndent()
}

data class SelectedDocument(
    val uri: Uri,
    val name: String,
    val size: Long?,
)

enum class JobPhase {
    IDLE,
    QUEUED,
    COPYING,
    CONVERTING,
    VERIFYING,
    SAVING,
    COMPLETE,
    FAILED,
    CANCELLED,
}

data class JobState(
    val id: String? = null,
    val phase: JobPhase = JobPhase.IDLE,
    val transferredBytes: Long = 0,
    val outputUri: Uri? = null,
    val outputName: String? = null,
    val detail: String? = null,
) {
    val isRunning: Boolean
        get() = phase in setOf(
            JobPhase.QUEUED,
            JobPhase.COPYING,
            JobPhase.CONVERTING,
            JobPhase.VERIFYING,
            JobPhase.SAVING,
        )
}

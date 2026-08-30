package com.raf3fr.app.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConversionSettingsTest {
    @Test
    fun productDefaultsMatchTheSupportedConversionPath() {
        val settings = ConversionSettings()

        assertEquals(Language.EN, settings.language)
        assertEquals(WhiteBalanceMode.AUTO, settings.whiteBalance)
        assertEquals(SensorMappingMode.ADAPTIVE, settings.sensorMapping)
        assertEquals(PreviewMode.SOURCE, settings.preview)
        assertEquals(DonorLensMode.NEUTRALIZE, settings.donorLens)
        assertEquals(null, settings.donorUri)
        assertEquals(DistortionModel.NATIVE_MATCH, settings.distortionModel)
        assertEquals(IsoPolicy.HNNR_STABLE, settings.isoPolicy)
        assertEquals(1f, settings.distortionStrength)
        assertEquals(1f, settings.chromaticAberrationStrength)
        assertEquals(0f, settings.vignettingStrength)
        assertFalse(settings.inverseCalibration)
    }

    @Test
    fun nativeJsonIncludesEveryConversionPolicy() {
        val json = ConversionSettings().nativeJson()

        assertTrue(json.contains("\"white_balance\":\"auto\""))
        assertTrue(json.contains("\"sensor_mapping\":\"wb-adaptive-bootstrap\""))
        assertTrue(json.contains("\"donor_lens_correction\":\"neutralize\""))
        assertTrue(json.contains("\"distortion_model\":\"native-match\""))
        assertTrue(json.contains("\"iso_policy\":\"hnnr-stable\""))
        assertTrue(json.contains("\"distortion_strength\":1.0"))
        assertTrue(json.contains("\"chromatic_aberration_strength\":1.0"))
        assertTrue(json.contains("\"vignetting_strength\":0.0"))
    }

    @Test
    fun nativeJsonCanSelectLegacyInBoundsGeometry() {
        val json = ConversionSettings(
            distortionModel = DistortionModel.LEGACY_IN_BOUNDS,
        ).nativeJson()

        assertTrue(json.contains("\"distortion_model\":\"legacy-in-bounds\""))
    }

    @Test
    fun nativeJsonPreservesSignedLensStrengths() {
        val json = ConversionSettings(
            distortionStrength = -1f,
            chromaticAberrationStrength = -2f,
            vignettingStrength = -0.5f,
        ).nativeJson()

        assertTrue(json.contains("\"distortion_strength\":-1.0"))
        assertTrue(json.contains("\"chromatic_aberration_strength\":-2.0"))
        assertTrue(json.contains("\"vignetting_strength\":-0.5"))
    }

    @Test
    fun bothLanguagesCoverPrimaryAction() {
        assertEquals("转换并保存 3FR", copy(Language.ZH).convert)
        assertEquals("Convert & Save 3FR", copy(Language.EN).convert)
    }
}

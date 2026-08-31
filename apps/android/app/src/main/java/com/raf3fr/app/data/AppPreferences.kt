package com.raf3fr.app.data

import android.content.Context
import android.net.Uri
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.raf3fr.app.model.ConversionSettings
import com.raf3fr.app.model.DonorLensMode
import com.raf3fr.app.model.DistortionModel
import com.raf3fr.app.model.Language
import com.raf3fr.app.model.IsoPolicy
import com.raf3fr.app.model.PreviewMode
import com.raf3fr.app.model.SelectedDocument
import com.raf3fr.app.model.SensorMappingMode
import com.raf3fr.app.model.WhiteBalanceMode
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "raf3fr_preferences")

class AppPreferences(private val context: Context) {
    private object Keys {
        val language = stringPreferencesKey("language")
        val sourceUri = stringPreferencesKey("source_uri")
        val sourceName = stringPreferencesKey("source_name")
        val sourceSize = longPreferencesKey("source_size")
        val donorUri = stringPreferencesKey("donor_uri")
        val donorName = stringPreferencesKey("donor_name")
        val whiteBalance = stringPreferencesKey("white_balance")
        val sensorMapping = stringPreferencesKey("sensor_mapping")
        val preview = stringPreferencesKey("preview")
        val donorLens = stringPreferencesKey("donor_lens")
        val distortionModel = stringPreferencesKey("distortion_model")
        val isoPolicy = stringPreferencesKey("iso_policy")
        val inverseCalibration = booleanPreferencesKey("inverse_calibration")
        val distortion = floatPreferencesKey("distortion")
        val chromaticAberration = floatPreferencesKey("chromatic_aberration")
        val vignetting = floatPreferencesKey("vignetting")
        val activeWorkId = stringPreferencesKey("active_work_id")
    }

    val settings: Flow<ConversionSettings> = context.dataStore.data.map(::decode)
    val source: Flow<SelectedDocument?> = context.dataStore.data.map { preferences ->
        preferences[Keys.sourceUri]?.let { uri ->
            SelectedDocument(
                uri = Uri.parse(uri),
                name = preferences[Keys.sourceName] ?: "RAF",
                size = preferences[Keys.sourceSize],
            )
        }
    }
    val activeWorkId: Flow<String?> = context.dataStore.data.map { it[Keys.activeWorkId] }

    suspend fun setLanguage(language: Language) = edit { it[Keys.language] = language.name }

    suspend fun setSource(uri: String, name: String, size: Long?) = edit {
        it[Keys.sourceUri] = uri
        it[Keys.sourceName] = name
        if (size == null) it.remove(Keys.sourceSize) else it[Keys.sourceSize] = size
    }

    suspend fun setDonor(uri: String, name: String) = edit {
        it[Keys.donorUri] = uri
        it[Keys.donorName] = name
    }

    suspend fun clearDonor() = edit {
        it.remove(Keys.donorUri)
        it.remove(Keys.donorName)
    }

    suspend fun updateSettings(value: ConversionSettings) = edit {
        it[Keys.whiteBalance] = value.whiteBalance.name
        it[Keys.sensorMapping] = value.sensorMapping.name
        it[Keys.preview] = value.preview.name
        it[Keys.donorLens] = value.donorLens.name
        it[Keys.distortionModel] = value.distortionModel.name
        it[Keys.isoPolicy] = value.isoPolicy.name
        it[Keys.inverseCalibration] = value.inverseCalibration
        it[Keys.distortion] = value.distortionStrength
        it[Keys.chromaticAberration] = value.chromaticAberrationStrength
        it[Keys.vignetting] = value.vignettingStrength
    }

    suspend fun setActiveWorkId(id: String?) = edit {
        if (id == null) it.remove(Keys.activeWorkId) else it[Keys.activeWorkId] = id
    }

    private suspend fun edit(
        block: suspend (androidx.datastore.preferences.core.MutablePreferences) -> Unit,
    ) {
        context.dataStore.edit(block)
    }

    private fun decode(preferences: Preferences): ConversionSettings = ConversionSettings(
        language = enumValue(preferences[Keys.language], Language.EN),
        donorUri = preferences[Keys.donorUri],
        donorName = preferences[Keys.donorName],
        whiteBalance = enumValue(preferences[Keys.whiteBalance], WhiteBalanceMode.AUTO),
        sensorMapping = enumValue(preferences[Keys.sensorMapping], SensorMappingMode.ADAPTIVE),
        preview = enumValue(preferences[Keys.preview], PreviewMode.SOURCE),
        donorLens = enumValue(preferences[Keys.donorLens], DonorLensMode.NEUTRALIZE),
        distortionModel = enumValue(
            preferences[Keys.distortionModel],
            DistortionModel.CAMERA_JPEG,
        ),
        isoPolicy = enumValue(preferences[Keys.isoPolicy], IsoPolicy.HNNR_STABLE),
        inverseCalibration = preferences[Keys.inverseCalibration] ?: false,
        distortionStrength = preferences[Keys.distortion] ?: 1f,
        chromaticAberrationStrength = preferences[Keys.chromaticAberration] ?: 1f,
        vignettingStrength = preferences[Keys.vignetting] ?: 0f,
    )

    private inline fun <reified T : Enum<T>> enumValue(value: String?, fallback: T): T =
        enumValues<T>().firstOrNull { it.name == value } ?: fallback
}

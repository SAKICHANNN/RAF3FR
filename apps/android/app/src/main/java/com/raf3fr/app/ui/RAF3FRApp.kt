package com.raf3fr.app.ui

import android.net.Uri
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.raf3fr.app.BuildConfig
import com.raf3fr.app.RAF3FRViewModel
import com.raf3fr.app.model.ConversionSettings
import com.raf3fr.app.model.DonorLensMode
import com.raf3fr.app.model.DistortionModel
import com.raf3fr.app.model.JobPhase
import com.raf3fr.app.model.JobState
import com.raf3fr.app.model.IsoPolicy
import com.raf3fr.app.model.Language
import com.raf3fr.app.model.PreviewMode
import com.raf3fr.app.model.ProductCopy
import com.raf3fr.app.model.SelectedDocument
import com.raf3fr.app.model.SensorMappingMode
import com.raf3fr.app.model.WhiteBalanceMode
import com.raf3fr.app.model.copy
import com.raf3fr.app.theme.GraphiteLine
import com.raf3fr.app.theme.GraphiteRaised
import com.raf3fr.app.theme.GraphiteSurface
import com.raf3fr.app.theme.InstrumentOrange
import com.raf3fr.app.theme.Muted
import kotlin.math.roundToInt

@Composable
fun RAF3FRApp(
    viewModel: RAF3FRViewModel,
    onChooseSource: () -> Unit,
    onChooseDonor: () -> Unit,
    onChooseOutput: () -> Unit,
    onOpenOutput: (Uri) -> Unit,
) {
    val settings by viewModel.settings.collectAsStateWithLifecycle()
    val source by viewModel.source.collectAsStateWithLifecycle()
    val job by viewModel.job.collectAsStateWithLifecycle()
    val words = copy(settings.language)
    var showSettings by remember { mutableStateOf(false) }

    Scaffold(containerColor = MaterialTheme.colorScheme.background) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .windowInsetsPadding(WindowInsets.safeDrawing),
        ) {
            ProductHeader(
                language = settings.language,
                settingsLabel = words.settings,
                onLanguage = viewModel::setLanguage,
                onSettings = { showSettings = true },
            )
            BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
                val expanded = maxWidth >= 840.dp
                if (expanded) {
                    Row(
                        modifier = Modifier.fillMaxSize().padding(horizontal = 32.dp, vertical = 20.dp),
                        horizontalArrangement = Arrangement.spacedBy(20.dp),
                    ) {
                        TaskPane(
                            modifier = Modifier.weight(1.55f).fillMaxHeight(),
                            source = source,
                            settings = settings,
                            words = words,
                            job = job,
                            onChooseSource = onChooseSource,
                            onUpdateSettings = viewModel::updateSettings,
                            onChooseOutput = onChooseOutput,
                        )
                        StatusPane(
                            modifier = Modifier.weight(0.85f).fillMaxHeight(),
                            job = job,
                            words = words,
                            onCancel = viewModel::cancel,
                            onOpenOutput = onOpenOutput,
                        )
                    }
                } else {
                    Column(
                        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                            .padding(horizontal = 18.dp, vertical = 14.dp),
                        verticalArrangement = Arrangement.spacedBy(14.dp),
                    ) {
                        TaskPane(
                            source = source,
                            settings = settings,
                            words = words,
                            job = job,
                            onChooseSource = onChooseSource,
                            onUpdateSettings = viewModel::updateSettings,
                            onChooseOutput = onChooseOutput,
                        )
                        StatusPane(
                            job = job,
                            words = words,
                            onCancel = viewModel::cancel,
                            onOpenOutput = onOpenOutput,
                        )
                        Spacer(Modifier.height(18.dp))
                    }
                }
            }
        }
    }

    if (showSettings) {
        SettingsSheet(
            settings = settings,
            words = words,
            onChooseDonor = onChooseDonor,
            onUseBundledDonor = viewModel::useBundledDonor,
            onUpdateSettings = viewModel::updateSettings,
            onDismiss = { showSettings = false },
        )
    }
}

@Composable
private fun ProductHeader(
    language: Language,
    settingsLabel: String,
    onLanguage: (Language) -> Unit,
    onSettings: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().height(72.dp).padding(horizontal = 20.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BrandMark()
        Spacer(Modifier.width(12.dp))
        Text("RAF3FR", style = MaterialTheme.typography.titleMedium, letterSpacing = 1.8.sp)
        Text(
            "V ${BuildConfig.VERSION_NAME}",
            modifier = Modifier.padding(start = 10.dp),
            color = Muted,
            style = MaterialTheme.typography.labelSmall,
        )
        Spacer(Modifier.weight(1f))
        LanguageToggle(language, onLanguage)
        Spacer(Modifier.width(8.dp))
        OutlinedButton(
            onClick = onSettings,
            modifier = Modifier.height(48.dp),
            contentPadding = PaddingValues(horizontal = 14.dp),
        ) { Text(settingsLabel) }
    }
    HorizontalDivider(color = GraphiteLine)
}

@Composable
private fun BrandMark() {
    Canvas(modifier = Modifier.size(30.dp).semantics { contentDescription = "RAF3FR" }) {
        val stroke = size.minDimension * 0.09f
        drawRect(
            color = InstrumentOrange,
            topLeft = Offset(stroke, stroke),
            size = androidx.compose.ui.geometry.Size(size.width - stroke * 2, size.height - stroke * 2),
            style = Stroke(width = stroke),
        )
        drawLine(
            color = Color.White,
            start = Offset(size.width * 0.28f, size.height * 0.5f),
            end = Offset(size.width * 0.72f, size.height * 0.5f),
            strokeWidth = stroke,
            cap = StrokeCap.Square,
        )
    }
}

@Composable
private fun LanguageToggle(language: Language, onLanguage: (Language) -> Unit) {
    Row(
        modifier = Modifier.clip(RoundedCornerShape(8.dp)).border(1.dp, GraphiteLine, RoundedCornerShape(8.dp)),
    ) {
        listOf(Language.EN to "En", Language.ZH to "中").forEach { (value, label) ->
            Box(
                modifier = Modifier.height(44.dp).clickable(role = Role.Button) { onLanguage(value) }
                    .background(if (language == value) GraphiteRaised else Color.Transparent)
                    .padding(horizontal = 13.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(label, color = if (language == value) InstrumentOrange else Muted)
            }
        }
    }
}

@Composable
private fun TaskPane(
    modifier: Modifier = Modifier,
    source: SelectedDocument?,
    settings: ConversionSettings,
    words: ProductCopy,
    job: JobState,
    onChooseSource: () -> Unit,
    onUpdateSettings: ((ConversionSettings) -> ConversionSettings) -> Unit,
    onChooseOutput: () -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = GraphiteSurface,
        shape = RoundedCornerShape(18.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, GraphiteLine),
    ) {
        Column(
            modifier = Modifier.padding(22.dp),
            verticalArrangement = Arrangement.spacedBy(22.dp),
        ) {
            SourceSelector(source, words, onChooseSource)
            HorizontalDivider(color = GraphiteLine)
            OptionTitle(words.whiteBalance)
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                ChoiceChip(words.auto, settings.whiteBalance == WhiteBalanceMode.AUTO) {
                    onUpdateSettings { it.copy(whiteBalance = WhiteBalanceMode.AUTO) }
                }
                ChoiceChip(words.asShot, settings.whiteBalance == WhiteBalanceMode.AS_SHOT) {
                    onUpdateSettings { it.copy(whiteBalance = WhiteBalanceMode.AS_SHOT) }
                }
                ChoiceChip(words.donorWb, settings.whiteBalance == WhiteBalanceMode.DONOR) {
                    onUpdateSettings { it.copy(whiteBalance = WhiteBalanceMode.DONOR) }
                }
            }
            OptionTitle(words.lens)
            Text(words.distortionModel, color = Muted, style = MaterialTheme.typography.labelLarge)
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                ChoiceChip(words.cameraJpegMatch, settings.distortionModel == DistortionModel.CAMERA_JPEG) {
                    onUpdateSettings { it.copy(distortionModel = DistortionModel.CAMERA_JPEG) }
                }
                ChoiceChip(words.nativeMatch, settings.distortionModel == DistortionModel.NATIVE_MATCH) {
                    onUpdateSettings { it.copy(distortionModel = DistortionModel.NATIVE_MATCH) }
                }
                ChoiceChip(words.legacyInBounds, settings.distortionModel == DistortionModel.LEGACY_IN_BOUNDS) {
                    onUpdateSettings { it.copy(distortionModel = DistortionModel.LEGACY_IN_BOUNDS) }
                }
            }
            StrengthControl(
                label = words.distortion,
                value = settings.distortionStrength,
                onValue = { value -> onUpdateSettings { it.copy(distortionStrength = value) } },
            )
            StrengthControl(
                label = words.chromaticAberration,
                value = settings.chromaticAberrationStrength,
                onValue = { value -> onUpdateSettings { it.copy(chromaticAberrationStrength = value) } },
            )
            StrengthControl(
                label = words.vignetting,
                value = settings.vignettingStrength,
                onValue = { value -> onUpdateSettings { it.copy(vignettingStrength = value) } },
            )
            Button(
                onClick = onChooseOutput,
                enabled = source != null && !job.isRunning,
                modifier = Modifier.fillMaxWidth().height(62.dp).testTag("convert_action"),
                colors = ButtonDefaults.buttonColors(
                    containerColor = InstrumentOrange,
                    contentColor = Color.Black,
                    disabledContainerColor = GraphiteRaised,
                    disabledContentColor = Muted,
                ),
                shape = RoundedCornerShape(12.dp),
            ) {
                Text(if (job.isRunning) words.preparing else words.convert, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun SourceSelector(source: SelectedDocument?, words: ProductCopy, onChooseSource: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().testTag("source_selector").clip(RoundedCornerShape(12.dp))
            .clickable(role = Role.Button, onClick = onChooseSource)
            .background(GraphiteRaised).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(if (source == null) words.chooseRaf else words.replaceRaf, color = InstrumentOrange, style = MaterialTheme.typography.labelLarge)
        Text(
            text = source?.name ?: words.sourceHint,
            style = MaterialTheme.typography.headlineSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        source?.size?.let { Text(formatBytes(it), color = Muted, style = MaterialTheme.typography.bodyMedium) }
    }
}

@Composable
private fun OptionTitle(text: String) {
    Text(text.uppercase(), color = Muted, style = MaterialTheme.typography.labelLarge)
}

@Composable
private fun ChoiceChip(label: String, selected: Boolean, onClick: () -> Unit) {
    FilterChip(selected = selected, onClick = onClick, label = { Text(label) })
}

@Composable
private fun StrengthControl(label: String, value: Float, onValue: (Float) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, modifier = Modifier.weight(1f))
            Text("${(value * 100).roundToInt()}%", color = Muted)
        }
        Slider(value = value, onValueChange = onValue, valueRange = -2f..2f)
    }
}

@Composable
private fun StatusPane(
    modifier: Modifier = Modifier,
    job: JobState,
    words: ProductCopy,
    onCancel: () -> Unit,
    onOpenOutput: (Uri) -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = GraphiteSurface,
        shape = RoundedCornerShape(18.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, GraphiteLine),
    ) {
        Column(
            modifier = Modifier.padding(22.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            OptionTitle(words.activity)
            Text(phaseLabel(job.phase, words), style = MaterialTheme.typography.headlineSmall)
            if (job.transferredBytes > 0) Text(formatBytes(job.transferredBytes), color = Muted)
            job.outputName?.let {
                Text(it, maxLines = 2, overflow = TextOverflow.Ellipsis, color = Muted)
            }
            job.detail?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Spacer(Modifier.height(8.dp))
            if (job.isRunning) {
                OutlinedButton(onClick = onCancel, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                    Text(words.cancel)
                }
            }
            if (job.phase == JobPhase.COMPLETE && job.outputUri != null) {
                Button(
                    onClick = { onOpenOutput(job.outputUri) },
                    modifier = Modifier.fillMaxWidth().height(52.dp),
                ) { Text(words.open) }
            }
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun SettingsSheet(
    settings: ConversionSettings,
    words: ProductCopy,
    onChooseDonor: () -> Unit,
    onUseBundledDonor: () -> Unit,
    onUpdateSettings: ((ConversionSettings) -> ConversionSettings) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = GraphiteSurface) {
        Column(
            modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                .padding(horizontal = 22.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            Text(words.advanced, style = MaterialTheme.typography.headlineSmall)
            OptionTitle(words.donor)
            OutlinedButton(onClick = onChooseDonor, modifier = Modifier.fillMaxWidth().height(54.dp)) {
                Text(
                    settings.donorName ?: words.bundledSanitized,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (settings.donorUri != null) {
                OutlinedButton(
                    onClick = onUseBundledDonor,
                    modifier = Modifier.fillMaxWidth().height(54.dp),
                ) {
                    Text(words.useBundled)
                }
            }
            OptionTitle(words.sensorMapping)
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                ChoiceChip(words.adaptive, settings.sensorMapping == SensorMappingMode.ADAPTIVE) {
                    onUpdateSettings { it.copy(sensorMapping = SensorMappingMode.ADAPTIVE) }
                }
                ChoiceChip(words.d65, settings.sensorMapping == SensorMappingMode.D65) {
                    onUpdateSettings { it.copy(sensorMapping = SensorMappingMode.D65) }
                }
                ChoiceChip(words.identity, settings.sensorMapping == SensorMappingMode.IDENTITY) {
                    onUpdateSettings { it.copy(sensorMapping = SensorMappingMode.IDENTITY) }
                }
            }
            OptionTitle(words.isoPolicy)
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                ChoiceChip(words.isoHnnrStable, settings.isoPolicy == IsoPolicy.HNNR_STABLE) {
                    onUpdateSettings { it.copy(isoPolicy = IsoPolicy.HNNR_STABLE) }
                }
                ChoiceChip(words.isoNearest, settings.isoPolicy == IsoPolicy.NEAREST_X2D) {
                    onUpdateSettings { it.copy(isoPolicy = IsoPolicy.NEAREST_X2D) }
                }
                ChoiceChip(words.isoCapture, settings.isoPolicy == IsoPolicy.CAPTURE) {
                    onUpdateSettings { it.copy(isoPolicy = IsoPolicy.CAPTURE) }
                }
            }
            OptionTitle(words.preview)
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                ChoiceChip(words.source, settings.preview == PreviewMode.SOURCE) {
                    onUpdateSettings { it.copy(preview = PreviewMode.SOURCE) }
                }
                ChoiceChip(words.donorPreview, settings.preview == PreviewMode.DONOR) {
                    onUpdateSettings { it.copy(preview = PreviewMode.DONOR) }
                }
            }
            OptionTitle(words.donorLens)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ChoiceChip(words.neutralize, settings.donorLens == DonorLensMode.NEUTRALIZE) {
                    onUpdateSettings { it.copy(donorLens = DonorLensMode.NEUTRALIZE) }
                }
                ChoiceChip(words.preserve, settings.donorLens == DonorLensMode.PRESERVE) {
                    onUpdateSettings { it.copy(donorLens = DonorLensMode.PRESERVE) }
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(words.inverseCalibration, modifier = Modifier.weight(1f))
                Switch(
                    checked = settings.inverseCalibration,
                    onCheckedChange = { value -> onUpdateSettings { it.copy(inverseCalibration = value) } },
                )
            }
            Button(onClick = onDismiss, modifier = Modifier.fillMaxWidth().height(54.dp)) {
                Text(words.close)
            }
            Spacer(Modifier.height(20.dp))
        }
    }
}

private fun phaseLabel(phase: JobPhase, words: ProductCopy): String = when (phase) {
    JobPhase.IDLE -> words.noActivity
    JobPhase.QUEUED -> words.queued
    JobPhase.COPYING -> words.copying
    JobPhase.CONVERTING -> words.converting
    JobPhase.VERIFYING -> words.verifying
    JobPhase.SAVING -> words.saving
    JobPhase.COMPLETE -> words.complete
    JobPhase.FAILED -> words.failed
    JobPhase.CANCELLED -> words.cancelled
}

private fun formatBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024 * 1024 -> "%.2f GB".format(bytes / (1024.0 * 1024 * 1024))
    bytes >= 1024L * 1024 -> "%.1f MB".format(bytes / (1024.0 * 1024))
    bytes >= 1024L -> "%.1f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}

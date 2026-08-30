import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            header
            Rectangle().fill(ProductTheme.line).frame(height: 1)
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    templateSection
                    processingSection
                    renderingSection
                    metadataSection
                    resourceSection
                }
                .padding(.horizontal, 30)
                .padding(.vertical, 26)
            }
        }
        .frame(width: 650, height: 780)
        .background(ProductTheme.workspace)
        .dismissTextFieldOnOutsideClick()
    }

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "camera.aperture")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(ProductTheme.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("RAF / 3FR")
                    .font(.system(size: 9, weight: .bold))
                    .tracking(2)
                    .foregroundStyle(ProductTheme.orange)
                Text(model.t("settings"))
                    .font(.custom("Outfit", size: 21).weight(.medium))
            }
            Spacer()
            Text(ProductVersion.detailed())
                .font(.system(size: 9, weight: .semibold).monospacedDigit())
                .tracking(1)
                .foregroundStyle(ProductTheme.faint)
            Button(model.language.toggleLabel, action: model.toggleLanguage)
                .buttonStyle(SettingsUtilityButtonStyle())
                .accessibilityLabel(model.language.accessibilityToggle)
        }
        .padding(.horizontal, 30)
        .frame(height: 72)
        .background(ProductTheme.rail)
    }

    private var templateSection: some View {
        SettingsSection(title: model.t("x2dContainer"), index: "01") {
            VStack(spacing: 0) {
                HStack(alignment: .center, spacing: 16) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text(model.t("currentSource"))
                            .font(.system(size: 9, weight: .semibold))
                            .tracking(1.2)
                            .foregroundStyle(ProductTheme.muted)
                        Text(model.donorSource == .bundled ? model.t("bundledSanitized") : (model.donorURL?.lastPathComponent ?? model.t("notConfigured")))
                            .font(.system(size: 13, weight: .medium))
                            .lineLimit(1)
                        if let path = model.donorURL?.path, model.donorSource == .external {
                            Text(path)
                                .font(.system(size: 9).monospaced())
                                .foregroundStyle(ProductTheme.faint)
                                .lineLimit(1)
                        }
                    }
                    Spacer()
                    Text(model.donorSource == .bundled ? model.t("bundledSanitized") : model.t("externalOverride"))
                        .font(.system(size: 9, weight: .bold))
                        .tracking(1)
                        .foregroundStyle(ProductTheme.orange)
                }
                .padding(18)

                Rectangle().fill(ProductTheme.line).frame(height: 1)

                HStack(spacing: 10) {
                    Button(model.t("chooseExternalEllipsis"), action: model.chooseDonor)
                        .buttonStyle(SettingsActionButtonStyle(primary: model.donorSource == .bundled))
                    if model.donorSource == .external {
                        Button(model.t("restoreBundled"), action: model.useBundledDonor)
                            .buttonStyle(SettingsActionButtonStyle(primary: false))
                    }
                    Spacer()
                }
                .padding(14)
            }
            .background(ProductTheme.rail)
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))

            if let error = model.blockingError, model.bundledDonorError != nil {
                Text(error)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(Color.red.opacity(0.9))
                    .padding(.top, 8)
            }
        }
    }

    private var processingSection: some View {
        SettingsSection(title: model.t("processing"), index: "02") {
            VStack(spacing: 0) {
                SettingsChoiceRow(
                    title: model.t("sensorMapping"),
                    options: [
                        ("wb-adaptive-bootstrap", model.t("adaptive")),
                        ("identity", "Identity"),
                        ("d65-dnglab-bootstrap", "D65 bootstrap"),
                    ],
                    selection: model.settings.sensorMapping,
                    onSelect: { model.settings.sensorMapping = $0 }
                )
                SettingsChoiceRow(
                    title: model.t("donorLens"),
                    options: [("neutralize", model.t("neutralize")), ("preserve", model.t("preserve"))],
                    selection: model.settings.donorLensCorrection,
                    onSelect: { model.settings.donorLensCorrection = $0 }
                )
                SettingsChoiceRow(
                    title: model.t("distortionModel"),
                    options: DistortionModel.allCases.map { ($0.rawValue, $0.title(model.language)) },
                    selection: model.settings.effectiveDistortionModel.rawValue,
                    footnote: model.t("distortionModelDetail"),
                    onSelect: { model.settings.distortionModel = DistortionModel(rawValue: $0) }
                )
                SettingsToggleRow(title: model.t("inverse"), isOn: $model.settings.inverseCalibration)
                SettingsChoiceRow(
                    title: model.t("isoPolicy"),
                    options: ISOPolicy.allCases.map { ($0.rawValue, $0.title(model.language)) },
                    selection: model.settings.isoPolicy.rawValue,
                    footnote: model.t("isoPolicyDetail"),
                    onSelect: { if let value = ISOPolicy(rawValue: $0) { model.settings.isoPolicy = value } }
                )
                SettingsToggleRow(
                    title: model.t("notifications"),
                    isOn: Binding(
                        get: { model.notificationsEnabled },
                        set: { model.setNotificationsEnabled($0) }
                    ),
                    drawsDivider: false
                )
            }
            .background(ProductTheme.rail)
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
        }
    }

    private var renderingSection: some View {
        SettingsSection(title: model.t("phocusRendering"), index: "03") {
            VStack(spacing: 0) {
                SettingsChoiceRow(
                    title: model.t("exposurePolicy"),
                    options: ExposurePolicy.allCases.map { ($0.rawValue, $0.title(model.language)) },
                    selection: model.settings.exposurePolicy.rawValue,
                    footnote: model.t("exposurePolicyDetail"),
                    onSelect: {
                        if let value = ExposurePolicy(rawValue: $0) {
                            model.settings.exposurePolicy = value
                        }
                    }
                )
                SettingsToggleRow(
                    title: model.t("dynamicRangeMigration"),
                    footnote: model.t("dynamicRangeMigrationDetail"),
                    isOn: $model.settings.dynamicRangeEnabled
                )
                SettingsToggleRow(
                    title: model.t("toneCurveMigration"),
                    footnote: model.t("approximateMigrationDetail"),
                    isOn: $model.settings.toneCurveEnabled
                )
                SettingsToggleRow(
                    title: model.t("grainMigration"),
                    footnote: model.t("approximateMigrationDetail"),
                    isOn: $model.settings.grainEnabled
                )
                SettingsToggleRow(
                    title: model.t("colorRenderingMigration"),
                    footnote: model.t("creativeMigrationDetail"),
                    isOn: $model.settings.colorRenderingEnabled
                )
                SettingsToggleRow(
                    title: model.t("contrastRenderingMigration"),
                    footnote: model.t("creativeMigrationDetail"),
                    isOn: $model.settings.contrastRenderingEnabled
                )
                SettingsToggleRow(
                    title: model.t("clarityRenderingMigration"),
                    footnote: model.t("creativeMigrationDetail"),
                    isOn: $model.settings.clarityRenderingEnabled
                )
                SettingsToggleRow(
                    title: model.t("sharpnessRenderingMigration"),
                    footnote: model.t("sharpnessMigrationDetail"),
                    isOn: $model.settings.sharpnessRenderingEnabled
                )
                SettingsToggleRow(
                    title: model.t("monochromeRenderingMigration"),
                    footnote: model.t("monochromeMigrationDetail"),
                    isOn: $model.settings.monochromeRenderingEnabled,
                    drawsDivider: false
                )
            }
            .background(ProductTheme.rail)
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
        }
    }

    private var resourceSection: some View {
        SettingsSection(title: model.t("hardwareUtilization"), index: "05") {
            VStack(spacing: 0) {
                SettingsValueRow(
                    title: model.t("parallelTaskLimit"),
                    value: model.settings.maxParallelJobs,
                    range: 1...16,
                    unit: model.t("jobs"),
                    onChange: model.setMaxParallelJobs
                )
                SettingsValueRow(
                    title: model.t("cpuCoreLimit"),
                    value: model.settings.maxCPUCores,
                    range: 1...model.processorCount,
                    unit: model.t("cores"),
                    onChange: model.setMaxCPUCores
                )
                SettingsValueRow(
                    title: model.t("memoryLimit"),
                    value: model.settings.memoryLimitGiB,
                    range: 2...model.physicalMemoryGiB,
                    unit: "GB",
                    footnote: "\(model.hardwarePlan.maxConcurrentJobs) \(model.t("effectiveJobs")) · \(model.hardwarePlan.threadsPerJob) \(model.t("threadsPerJob"))\n\(model.t("ramBudgetDetail"))",
                    onChange: model.setMemoryLimitGiB
                )
            }
            .background(ProductTheme.rail)
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
        }
    }

    private var metadataSection: some View {
        SettingsSection(title: model.t("metadataMigration"), index: "04") {
            VStack(spacing: 0) {
                SettingsToggleRow(
                    title: model.t("framingMigration"),
                    footnote: model.t("framingMigrationDetail"),
                    isOn: $model.settings.framingEnabled
                )
                SettingsToggleRow(
                    title: model.t("locationMigration"),
                    footnote: model.t("locationMigrationDetail"),
                    isOn: $model.settings.preserveLocation
                )
                SettingsToggleRow(
                    title: model.t("rightsMigration"),
                    footnote: model.t("rightsMigrationDetail"),
                    isOn: $model.settings.preserveRights
                )
                SettingsToggleRow(
                    title: model.t("provenanceMigration"),
                    footnote: model.t("provenanceMigrationDetail"),
                    isOn: $model.settings.preserveProvenance,
                    drawsDivider: false
                )
            }
            .background(ProductTheme.rail)
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
        }
    }
}

private struct SettingsValueRow: View {
    let title: String
    let value: Int
    let range: ClosedRange<Int>
    let unit: String
    var footnote: String? = nil
    let onChange: (Int) -> Void

    var body: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 5) {
                Text(title)
                    .font(.system(size: 11, weight: .medium))
                if let footnote {
                    Text(footnote)
                        .font(.system(size: 9))
                        .foregroundStyle(ProductTheme.faint)
                }
            }
            Spacer()
            HStack(spacing: 0) {
                valueButton(systemName: "minus", enabled: value > range.lowerBound) {
                    onChange(max(range.lowerBound, value - 1))
                }
                Text("\(value)")
                    .font(.system(size: 11, weight: .semibold).monospacedDigit())
                    .frame(minWidth: 42, minHeight: 40)
                    .background(ProductTheme.canvas.opacity(0.4))
                Text(unit.uppercased())
                    .font(.system(size: 8, weight: .bold))
                    .tracking(0.7)
                    .foregroundStyle(ProductTheme.muted)
                    .frame(minWidth: 46, minHeight: 40)
                    .background(ProductTheme.canvas.opacity(0.4))
                valueButton(systemName: "plus", enabled: value < range.upperBound) {
                    onChange(min(range.upperBound, value + 1))
                }
            }
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
        }
        .padding(18)
        .overlay(alignment: .bottom) { Rectangle().fill(ProductTheme.line).frame(height: 1) }
    }

    private func valueButton(systemName: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 10, weight: .semibold))
                .frame(width: 42, height: 40)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(enabled ? ProductTheme.orange : ProductTheme.faint)
        .disabled(!enabled)
    }
}

private struct SettingsSection<Content: View>: View {
    let title: String
    let index: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(index)
                    .font(.system(size: 9, weight: .bold).monospacedDigit())
                    .foregroundStyle(ProductTheme.orange)
                Text(title.uppercased())
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(1.5)
                    .foregroundStyle(ProductTheme.muted)
                Spacer()
            }
            content
        }
    }
}

private struct SettingsChoiceRow: View {
    let title: String
    let options: [(String, String)]
    let selection: String
    var footnote: String? = nil
    let onSelect: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            Text(title)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(ProductTheme.text)
            HStack(spacing: 0) {
                ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                    Button(action: { onSelect(option.0) }) {
                        Text(option.1)
                            .font(.system(size: 10, weight: option.0 == selection ? .semibold : .regular))
                            .frame(maxWidth: .infinity, minHeight: 40)
                            .contentShape(Rectangle())
                            .foregroundStyle(option.0 == selection ? ProductTheme.text : ProductTheme.muted)
                            .background(option.0 == selection ? ProductTheme.raised : ProductTheme.canvas.opacity(0.4))
                            .overlay(alignment: .bottom) {
                                Rectangle().fill(option.0 == selection ? ProductTheme.orange : Color.clear).frame(height: 2)
                            }
                    }
                    .buttonStyle(.plain)
                }
            }
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
            if let footnote {
                Text(footnote)
                    .font(.system(size: 9))
                    .foregroundStyle(ProductTheme.faint)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(18)
        .overlay(alignment: .bottom) { Rectangle().fill(ProductTheme.line).frame(height: 1) }
    }
}

private struct SettingsToggleRow: View {
    let title: String
    var footnote: String? = nil
    @Binding var isOn: Bool
    var drawsDivider = true

    var body: some View {
        Button(action: { isOn.toggle() }) {
            HStack(spacing: 18) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(title).font(.system(size: 11, weight: .medium))
                    if let footnote {
                        Text(footnote)
                            .font(.system(size: 9))
                            .foregroundStyle(ProductTheme.faint)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer()
                HStack(spacing: 8) {
                    Text(isOn ? "ON" : "OFF")
                        .font(.system(size: 8, weight: .bold).monospaced())
                        .foregroundStyle(isOn ? ProductTheme.orange : ProductTheme.faint)
                    ZStack(alignment: isOn ? .trailing : .leading) {
                        Rectangle().fill(isOn ? ProductTheme.orange.opacity(0.24) : ProductTheme.canvas).frame(width: 34, height: 16)
                        Rectangle().fill(isOn ? ProductTheme.orange : ProductTheme.muted).frame(width: 12, height: 12).padding(2)
                    }
                    .overlay(Rectangle().stroke(isOn ? ProductTheme.orange.opacity(0.55) : ProductTheme.line, lineWidth: 1))
                }
            }
            .padding(18)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .overlay(alignment: .bottom) {
            if drawsDivider { Rectangle().fill(ProductTheme.line).frame(height: 1) }
        }
    }
}

private struct SettingsUtilityButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 9, weight: .semibold))
            .tracking(0.8)
            .foregroundStyle(configuration.isPressed ? ProductTheme.orange : ProductTheme.muted)
            .padding(.horizontal, 11)
            .frame(minWidth: 40, minHeight: 40)
            .contentShape(Rectangle())
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
    }
}

private struct SettingsActionButtonStyle: ButtonStyle {
    let primary: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(primary ? Color.black.opacity(0.88) : ProductTheme.text)
            .padding(.horizontal, 14)
            .frame(minHeight: 40)
            .contentShape(Rectangle())
            .background(primary ? ProductTheme.orange : ProductTheme.raised)
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

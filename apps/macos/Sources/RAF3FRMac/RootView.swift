import AppKit
import SwiftUI

struct RootView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            instrumentBar
            Rectangle().fill(ProductTheme.line).frame(height: 1)
            GeometryReader { geometry in
                HStack(alignment: .top, spacing: 0) {
                    workspace
                        .frame(width: max(650, geometry.size.width * 0.69))
                        .frame(maxHeight: .infinity, alignment: .top)
                    Rectangle().fill(ProductTheme.line).frame(width: 1)
                    activityRail
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
        }
        .background(ProductTheme.canvas)
        .frame(minWidth: 1050, minHeight: 735)
        .dismissTextFieldOnOutsideClick()
        .onOpenURL(perform: model.selectSource)
    }

    private var instrumentBar: some View {
        HStack(spacing: 18) {
            Image(systemName: "camera.aperture")
                .font(.system(size: 15, weight: .medium)).foregroundStyle(ProductTheme.orange)
            Text("RAF").font(.system(size: 12, weight: .bold)).tracking(2.4)
            Text("/").foregroundStyle(ProductTheme.faint)
            Text("3FR").font(.system(size: 12, weight: .bold)).tracking(2.4)
            Rectangle().fill(ProductTheme.line).frame(width: 1, height: 18)
            Text("GFX 100RF  →  X2D 100C")
                .font(.system(size: 10, weight: .medium)).tracking(1.3).foregroundStyle(ProductTheme.muted)
            Text(ProductVersion.short())
                .font(.system(size: 9, weight: .semibold).monospacedDigit())
                .tracking(1.1)
                .foregroundStyle(ProductTheme.faint)
                .accessibilityLabel("RAF 3FR \(ProductVersion.detailed())")
            Spacer()
            Button(model.language.toggleLabel, action: model.toggleLanguage)
                .buttonStyle(InstrumentActionStyle()).accessibilityLabel(model.language.accessibilityToggle)
            Button(action: model.chooseSource) { Label(model.t("openRaf"), systemImage: "plus") }
                .buttonStyle(InstrumentActionStyle())
            SettingsLink { Image(systemName: "slider.horizontal.3") }
                .buttonStyle(InstrumentActionStyle()).accessibilityLabel(model.t("settings"))
        }
        .padding(.horizontal, 24).frame(height: 55).background(ProductTheme.rail)
    }

    private var workspace: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .lastTextBaseline) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("GFX 100RF").font(.system(size: 9, weight: .bold)).tracking(2.2).foregroundStyle(ProductTheme.orange)
                    Text(model.t("convertRaw")).font(.custom("Outfit", size: 29).weight(.medium)).foregroundStyle(ProductTheme.text)
                }
                Spacer()
                if !model.sourceURLs.isEmpty {
                    Button(model.t("clearSelection"), action: model.clearSelection).buttonStyle(QuietTextButtonStyle())
                }
            }
            .padding(.bottom, 17)

            CapturePresentationView(model: model).padding(.bottom, 18)

            HStack(spacing: 18) {
                Text(model.t("whiteBalance"))
                    .font(.system(size: 10, weight: .semibold)).tracking(1.1).foregroundStyle(ProductTheme.muted)
                    .frame(width: 78, alignment: .leading)
                ModeStrip(selection: $model.settings.whiteBalance, language: model.language)
            }
            .frame(height: 42)
            .overlay(alignment: .bottom) { Rectangle().fill(ProductTheme.line).frame(height: 1) }

            VStack(spacing: 0) {
                LensControl(title: model.t("distortion"), enabled: $model.settings.distortionEnabled, strength: $model.settings.distortionStrength)
                LensControl(title: model.t("ca"), enabled: $model.settings.chromaticAberrationEnabled, strength: $model.settings.chromaticAberrationStrength)
                LensControl(title: model.t("vignetting"), enabled: $model.settings.vignettingEnabled, strength: $model.settings.vignettingStrength)
            }

            if let error = model.blockingError {
                HStack(spacing: 8) {
                    Circle().fill(Color.red).frame(width: 6, height: 6)
                    Text(error).font(.caption).foregroundStyle(Color.red.opacity(0.9))
                }.padding(.top, 10)
            }
            Spacer(minLength: 14)
                .frame(maxWidth: .infinity)
                .overlay(alignment: .bottom) {
                    if model.settings.vignettingEnabled, model.settings.vignettingStrength < 0 {
                        NegativeVignetteCompatibility(model: model)
                    }
                }

            if model.phase.isRunning {
                Button(model.t("cancel"), action: model.cancel).buttonStyle(SecondaryActionStyle())
            } else {
                Button(action: model.startConversion) {
                    HStack {
                        Text(model.sourceURLs.count > 1 ? model.t("convertBatch") : model.t("convert3fr"))
                        if model.sourceURLs.count > 1 {
                            Text("· \(model.sourceURLs.count)").font(.system(size: 11, weight: .bold).monospacedDigit())
                        }
                        Spacer()
                        Image(systemName: "arrow.right").font(.system(size: 15, weight: .bold))
                    }
                }
                .buttonStyle(HeroActionStyle()).disabled(!model.canConvert)
                .keyboardShortcut(.return, modifiers: [.command])
            }
        }
        .padding(.horizontal, 30).padding(.top, 25).padding(.bottom, 25)
        .background(ProductTheme.workspace)
    }

    private var activityRail: some View {
        VStack(alignment: .leading, spacing: 0) {
            RailHeading(title: model.t("currentJob"), marker: model.phase.title(model.language))
            BatchStatusView(model: model).padding(.top, 18)
            Rectangle().fill(ProductTheme.line).frame(height: 1).padding(.vertical, 24)
            RailHeading(title: model.t("recent"), marker: "\(model.records.count)")
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(model.records.prefix(10)) { record in RecordRow(record: record, language: model.language) }
                }
            }.padding(.top, 10)
        }
        .padding(.horizontal, 24).padding(.top, 28).padding(.bottom, 20)
        .background(ProductTheme.rail)
    }
}

private struct NegativeVignetteCompatibility: View {
    @ObservedObject var model: AppModel

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "camera.aperture")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(ProductTheme.orange)
            Text(model.t("negativeVignetteCompatibility"))
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(ProductTheme.muted)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            HStack(spacing: 0) {
                ForEach(NegativeVignettePolicy.allCases) { policy in
                    Button(action: { model.settings.negativeVignettePolicy = policy }) {
                        Text(policy.title(model.language))
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(model.settings.negativeVignettePolicy == policy ? ProductTheme.text : ProductTheme.muted)
                            .lineLimit(1)
                            .minimumScaleFactor(0.82)
                            .frame(maxWidth: .infinity, minHeight: 40)
                            .contentShape(Rectangle())
                            .background(model.settings.negativeVignettePolicy == policy ? ProductTheme.raised : ProductTheme.canvas)
                            .overlay(alignment: .bottom) {
                                Rectangle()
                                    .fill(model.settings.negativeVignettePolicy == policy ? ProductTheme.orange : Color.clear)
                                    .frame(height: 2)
                            }
                    }
                    .buttonStyle(.plain)
                }
            }
            .frame(width: 280)
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
        }
        .padding(.horizontal, 12)
        .frame(minHeight: 48)
        .background(ProductTheme.canvas)
        .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
    }
}

private struct CapturePresentationView: View {
    @ObservedObject var model: AppModel
    @State private var targeted = false
    @State private var showsMetadata = false

    var body: some View {
        Group {
            if model.sourceURLs.isEmpty { emptyStage }
            else if model.sourcePresentationLoading { loadingStage }
            else if let presentation = model.sourcePresentation { loadedStage(presentation) }
            else { unavailableStage }
        }
        .frame(maxWidth: .infinity, minHeight: 238, maxHeight: 238)
        .clipped()
        .background(ProductTheme.canvas)
        .overlay(Rectangle().stroke(targeted ? ProductTheme.orange : ProductTheme.line, lineWidth: 1))
        .dropDestination(for: URL.self) { urls, _ in
            let rafs = urls.filter { $0.pathExtension.lowercased() == "raf" }
            guard !rafs.isEmpty else { return false }
            model.selectSources(rafs); return true
        } isTargeted: { targeted = $0 }
        .sheet(isPresented: $showsMetadata) {
            if let presentation = model.sourcePresentation {
                CaptureMetadataSheet(model: model, presentation: presentation)
            }
        }
    }

    private var emptyStage: some View {
        Button(action: model.chooseSource) {
            HStack(spacing: 18) {
                ZStack {
                    Rectangle().stroke(ProductTheme.orange, lineWidth: 1).frame(width: 42, height: 54)
                    Text("R").font(.system(size: 19, weight: .medium)).foregroundStyle(ProductTheme.orange)
                }
                VStack(alignment: .leading, spacing: 7) {
                    Text(model.t("selectRaf")).font(.system(size: 16, weight: .medium))
                    Text(model.t("dropRaf")).font(.caption).foregroundStyle(ProductTheme.muted)
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
        }.buttonStyle(.plain)
    }

    private var loadingStage: some View {
        HStack(spacing: 0) {
            ZStack { ProductTheme.raised; ProgressView().controlSize(.small).tint(ProductTheme.orange) }
                .frame(maxWidth: .infinity)
            VStack(alignment: .leading, spacing: 12) {
                Text(model.t("loadingCapture")).font(.system(size: 11, weight: .semibold)).tracking(1.2)
                Text(model.sourceURLs[model.sourcePresentationIndex].lastPathComponent).font(.caption).foregroundStyle(ProductTheme.muted)
            }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading).padding(22)
        }
    }

    private func loadedStage(_ presentation: SourcePresentation) -> some View {
        GeometryReader { geometry in
            let previewWidth = max(260, geometry.size.width * 0.5)

            HStack(spacing: 0) {
                preview(presentation)
                    .frame(width: previewWidth, height: geometry.size.height)
                    .clipped()
                VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(presentation.camera.model.uppercased())
                            .font(.system(size: 9, weight: .bold)).tracking(1.5).foregroundStyle(ProductTheme.orange)
                        Text(presentation.lens.model).font(.system(size: 13, weight: .medium)).lineLimit(1)
                    }
                    Spacer()
                    Button(action: { showsMetadata = true }) {
                        HStack(spacing: 7) {
                            Text(model.t("metadata"))
                            Image(systemName: "arrow.up.right").font(.system(size: 8, weight: .bold))
                        }
                    }
                    .buttonStyle(MetadataButtonStyle())
                    if model.sourceURLs.count > 1 { BatchCaptureNavigation(model: model) }
                }.padding(.bottom, 10)

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 10) {
                    CaptureFact(label: model.t("shutter"), value: presentation.capture.shutterText)
                    CaptureFact(label: model.t("aperture"), value: presentation.capture.apertureText)
                    CaptureFact(label: "ISO", value: "\(presentation.capture.iso)")
                    CaptureFact(label: model.t("focalLength"), value: presentation.capture.focalLengthText)
                    CaptureFact(label: model.t("exposureCompensation"), value: presentation.capture.compensationText)
                    CaptureFact(label: model.t("phocusCompensation"), value: presentation.capture.phocusCompensationText)
                    CaptureFact(label: model.t("whiteBalance"), value: presentation.capture.whiteBalanceText(model.language))
                    if let dynamicRange = presentation.capture.dynamicRangePercent {
                        CaptureFact(label: model.t("dynamicRange"), value: "DR\(dynamicRange)")
                    }
                    if let tone = presentation.renderingIntent?.toneText {
                        CaptureFact(label: model.t("toneCurve"), value: tone)
                    }
                    if let grain = presentation.renderingIntent?.grainText(model.language) {
                        CaptureFact(label: model.t("grain"), value: grain)
                    }
                    if let film = presentation.renderingIntent?.creative?.filmSimulation?.value {
                        CaptureFact(label: model.t("filmSimulation"), value: film.replacingOccurrences(of: "-", with: " ").capitalized)
                    }
                }
                Spacer(minLength: 4)
                HStack {
                    Text(presentation.capture.captureDateText)
                    Spacer()
                    if presentation.image.width > 0 { Text("\(presentation.image.width) × \(presentation.image.height)") }
                }
                .font(.system(size: 9, weight: .medium).monospacedDigit()).foregroundStyle(ProductTheme.muted)
                }
                .padding(16)
                .frame(width: geometry.size.width - previewWidth, height: geometry.size.height, alignment: .topLeading)
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .clipped()
        }
    }

    @ViewBuilder private func preview(_ presentation: SourcePresentation) -> some View {
        if let path = presentation.preview?.path, let image = NSImage(contentsOfFile: path) {
            Image(nsImage: image).resizable().aspectRatio(contentMode: .fill).accessibilityLabel(presentation.file.name)
        } else {
            ZStack { ProductTheme.raised; Image(systemName: "photo").font(.system(size: 24, weight: .light)).foregroundStyle(ProductTheme.faint) }
        }
    }

    private var unavailableStage: some View {
        Button(action: model.chooseSource) {
            VStack(spacing: 8) {
                Image(systemName: "photo.badge.exclamationmark").foregroundStyle(ProductTheme.orange)
                Text(model.t("captureUnavailable")).font(.system(size: 12, weight: .medium))
                Text(model.sourceURLs.first?.lastPathComponent ?? "").font(.caption2).foregroundStyle(ProductTheme.muted)
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
        }.buttonStyle(.plain)
    }
}

private struct CaptureMetadataSheet: View {
    @ObservedObject var model: AppModel
    let presentation: SourcePresentation
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 14) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("GFX 100RF")
                        .font(.system(size: 9, weight: .bold))
                        .tracking(1.8)
                        .foregroundStyle(ProductTheme.orange)
                    Text(model.t("metadata"))
                        .font(.custom("Outfit", size: 22).weight(.medium))
                }
                Spacer()
                Text(presentation.file.name)
                    .font(.system(size: 9, weight: .medium).monospaced())
                    .foregroundStyle(ProductTheme.muted)
                    .lineLimit(1)
                Button(action: { dismiss() }) {
                    Image(systemName: "xmark")
                        .frame(width: 40, height: 40)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .foregroundStyle(ProductTheme.muted)
                .accessibilityLabel(model.t("close"))
            }
            .padding(.horizontal, 28)
            .frame(height: 70)
            .background(ProductTheme.rail)

            Rectangle().fill(ProductTheme.line).frame(height: 1)

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    section(model.t("capture"), entries: captureEntries)
                    section(model.t("fujifilmRendering"), entries: renderingEntries)
                    section(model.t("framing"), entries: framingEntries)
                    section(model.t("cameraState"), entries: stateEntries)
                    section(model.t("fileAndProvenance"), entries: provenanceEntries)
                }
                .padding(28)
            }
        }
        .frame(width: 760, height: 700)
        .background(ProductTheme.workspace)
    }

    private func section(_ title: String, entries: [MetadataEntry]) -> some View {
        let visible = entries.filter { !$0.value.isEmpty }
        return VStack(alignment: .leading, spacing: 11) {
            HStack(spacing: 10) {
                Rectangle().fill(ProductTheme.orange).frame(width: 18, height: 2)
                Text(title.uppercased())
                    .font(.system(size: 9, weight: .semibold))
                    .tracking(1.4)
                    .foregroundStyle(ProductTheme.muted)
            }
            LazyVGrid(
                columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())],
                alignment: .leading,
                spacing: 0
            ) {
                ForEach(visible) { entry in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(entry.label.uppercased())
                            .font(.system(size: 7, weight: .bold))
                            .tracking(0.7)
                            .foregroundStyle(ProductTheme.faint)
                        Text(entry.value)
                            .font(.system(size: 11, weight: .medium).monospacedDigit())
                            .foregroundStyle(ProductTheme.text)
                            .lineLimit(2)
                    }
                    .frame(maxWidth: .infinity, minHeight: 56, alignment: .topLeading)
                    .padding(12)
                    .background(ProductTheme.rail)
                    .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 0.5))
                }
            }
        }
    }

    private var captureEntries: [MetadataEntry] {
        [
            entry("shutter", presentation.capture.shutterText),
            entry("aperture", presentation.capture.apertureText),
            MetadataEntry(label: "ISO", value: "\(presentation.capture.iso)"),
            entry("focalLength", "\(presentation.capture.focalLengthText) · \(presentation.capture.focalLengthEquivalentMm) mm eq."),
            entry("exposureCompensation", presentation.capture.compensationText),
            entry("phocusCompensation", presentation.capture.phocusCompensationText),
            entry("whiteBalance", presentation.capture.whiteBalanceText(model.language)),
            entry("dynamicRange", presentation.capture.dynamicRangePercent.map { "DR\($0)" } ?? ""),
            entry("captureDetails", presentation.capture.captureDateText),
        ]
    }

    private var renderingEntries: [MetadataEntry] {
        let intent = presentation.renderingIntent
        let creative = intent?.creative
        let monochrome = [
            creative?.monochromeMode?.value.map(displayName),
            signed(creative?.monochromeWarmCool),
            signed(creative?.monochromeMagentaGreen),
        ].compactMap { $0 }.joined(separator: " · ")
        return [
            entry("filmSimulation", creative?.filmSimulation?.value.map(displayName) ?? ""),
            entry("color", signed(creative?.color?.step)),
            entry("monochromeTone", monochrome),
            entry("colorChrome", creative?.colorChrome?.value.map(displayName) ?? ""),
            entry("colorChromeBlue", creative?.colorChromeBlue?.value.map(displayName) ?? ""),
            entry("clarity", signed(creative?.clarity?.step)),
            entry("sharpness", signed(creative?.sharpness?.step)),
            entry("highIsoNoiseReduction", signed(creative?.highIsoNoiseReduction?.step)),
            entry("contrast", creative?.contrast?.value.map(displayName) ?? ""),
            entry("toneCurve", intent?.toneText ?? ""),
            entry("grain", intent?.grainText(model.language) ?? ""),
            entry("lensModulationOptimizer", yesNo(creative?.lensModulationOptimizer?.enabled)),
        ]
    }

    private var framingEntries: [MetadataEntry] {
        let framing = presentation.framing
        let ratio: String
        if let width = framing?.aspectRatio?.width, let height = framing?.aspectRatio?.height {
            ratio = "\(width):\(height)"
        } else { ratio = "" }
        let zoom: String
        if framing?.rawZoom?.active == true, let size = framing?.rawZoom?.size, size.count == 2 {
            let cropMode = framing?.rawZoom?.cropMode.map { " · C\($0)" } ?? ""
            zoom = "\(model.t("active")) · \(size[0]) × \(size[1])\(cropMode)"
        } else { zoom = model.t("inactive") }
        return [
            entry("aspectRatio", ratio),
            entry("digitalTeleconverter", zoom),
            entry("orientation", framing?.orientation.map(String.init) ?? ""),
            entry("resolution", "\(presentation.image.width) × \(presentation.image.height)"),
        ]
    }

    private var stateEntries: [MetadataEntry] {
        let state = presentation.captureState
        let point = state?.focusPixel.flatMap { $0.count == 2 ? "\($0[0]), \($0[1])" : nil } ?? ""
        let attitude: String
        if let elevation = state?.cameraElevationDegrees, let roll = state?.cameraRollDegrees {
            attitude = String(format: "%.1f° / %.1f°", elevation, roll)
        } else { attitude = "" }
        let warnings = state?.warnings.map { "B \($0.blur ?? 0) · F \($0.focus ?? 0) · E \($0.exposure ?? 0)" } ?? ""
        return [
            entry("shutterType", state?.shutterType?.value.map(displayName) ?? ""),
            entry("focusMode", state?.focusMode?.value.map(displayName) ?? ""),
            entry("afMode", state?.afMode?.value.map(displayName) ?? ""),
            entry("focusPoint", point),
            entry("driveMode", state?.driveMode?.value.map(displayName) ?? ""),
            entry("flashCompensation", signed(state?.flashExposureCompensationEv)),
            entry("flickerReduction", state?.flickerReductionCode.map(String.init) ?? ""),
            entry("cameraAttitude", attitude),
            entry("captureWarnings", warnings),
            entry("compositeCapture", state?.compositeImageCode.map(String.init) ?? ""),
        ]
    }

    private var provenanceEntries: [MetadataEntry] {
        let metadata = presentation.standardMetadata
        let location: String
        if metadata?.location?.present == true,
           let latitude = metadata?.location?.latitude,
           let longitude = metadata?.location?.longitude {
            let datum = metadata?.location?.mapDatum.map { " · \($0)" } ?? ""
            location = String(format: "%.6f, %.6f", latitude, longitude) + datum
        } else { location = model.t("none") }
        let encoding: String
        if let bits = presentation.captureState?.sourceEncoding?.bitsPerSample {
            let compression = presentation.captureState?.sourceEncoding?.rafCompressionCode.map { " · C\($0)" } ?? ""
            encoding = "\(bits)-bit\(compression)"
        } else { encoding = "" }
        return [
            entry("sourceFile", presentation.file.name),
            entry("fileSize", ByteCountFormatter.string(fromByteCount: presentation.file.bytes, countStyle: .file)),
            entry("sourceCamera", [metadata?.provenance?.originalMake, metadata?.provenance?.originalModel].compactMap { $0 }.joined(separator: " ")),
            entry("firmware", metadata?.provenance?.sourceFirmware ?? ""),
            entry("captureDetails", exactCaptureTime),
            entry("created", metadata?.time?.createDate ?? ""),
            entry("modified", metadata?.time?.modifyDate ?? ""),
            entry("location", location),
            entry("altitude", metadata?.location?.altitudeM.map { String(format: "%.1f m", $0) } ?? ""),
            entry("gpsTime", [metadata?.location?.gpsDateStamp, metadata?.location?.gpsTimeStamp].compactMap { $0 }.joined(separator: " ")),
            entry("rating", metadata?.rights?.rating.map { "\($0) / 5" } ?? ""),
            entry("artist", metadata?.rights?.artist ?? ""),
            entry("copyright", metadata?.rights?.copyright ?? ""),
            entry("comment", metadata?.rights?.userComment ?? ""),
            entry("sourceEncoding", encoding),
        ]
    }

    private var exactCaptureTime: String {
        guard let time = presentation.standardMetadata?.time else {
            return presentation.capture.captureDateText
        }
        var value = time.dateTimeOriginal ?? presentation.capture.captureDateText
        if let subsecond = time.subsecTimeOriginal { value += ".\(subsecond)" }
        if let offset = time.offsetTimeOriginal, !offset.isEmpty { value += " \(offset)" }
        return value
    }

    private func entry(_ key: String, _ value: String) -> MetadataEntry {
        MetadataEntry(label: model.t(key), value: value)
    }

    private func displayName(_ value: String) -> String {
        value.split(separator: "-").map { $0.capitalized }.joined(separator: " ")
    }

    private func signed<T: BinaryFloatingPoint>(_ value: T?) -> String {
        guard let value else { return "" }
        return String(format: "%+.1f", Double(value))
    }

    private func signed(_ value: Int?) -> String {
        guard let value else { return "" }
        return String(format: "%+d", value)
    }

    private func yesNo(_ value: Bool?) -> String {
        guard let value else { return "" }
        return model.t(value ? "yes" : "no")
    }
}

private struct MetadataEntry: Identifiable {
    let id = UUID()
    let label: String
    let value: String
}

private struct MetadataButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 8, weight: .semibold))
            .tracking(0.7)
            .foregroundStyle(configuration.isPressed ? ProductTheme.orange : ProductTheme.muted)
            .padding(.horizontal, 10)
            .frame(minHeight: 40)
            .contentShape(Rectangle())
            .overlay(Rectangle().stroke(ProductTheme.line, lineWidth: 1))
    }
}

private struct BatchCaptureNavigation: View {
    @ObservedObject var model: AppModel
    var body: some View {
        HStack(spacing: 9) {
            Button(action: model.showPreviousSourcePresentation) { Image(systemName: "chevron.left") }
                .disabled(model.sourcePresentationIndex == 0)
            Text("\(model.sourcePresentationIndex + 1) / \(model.sourceURLs.count)")
                .font(.system(size: 9, weight: .semibold).monospacedDigit()).foregroundStyle(ProductTheme.muted)
            Button(action: model.showNextSourcePresentation) { Image(systemName: "chevron.right") }
                .disabled(model.sourcePresentationIndex + 1 == model.sourceURLs.count)
        }.buttonStyle(IconButtonStyle())
    }
}

private struct CaptureFact: View {
    let label: String
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label.uppercased()).font(.system(size: 7, weight: .bold)).tracking(0.8).foregroundStyle(ProductTheme.muted)
            Text(value)
                .font(.system(size: 12, weight: .medium).monospacedDigit())
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
    }
}

private struct ModeStrip: View {
    @Binding var selection: WhiteBalance
    let language: AppLanguage
    var body: some View {
        HStack(spacing: 0) {
            ForEach(WhiteBalance.allCases) { value in
                Button(action: { selection = value }) {
                    Text(value.title(language))
                        .font(.system(size: 11, weight: selection == value ? .semibold : .medium))
                        .foregroundStyle(selection == value ? ProductTheme.text : ProductTheme.muted)
                        .frame(maxWidth: .infinity, minHeight: 40)
                        .contentShape(Rectangle())
                        .background(alignment: .bottom) { Rectangle().fill(selection == value ? ProductTheme.orange : Color.clear).frame(height: 2) }
                }.buttonStyle(.plain).accessibilityAddTraits(selection == value ? .isSelected : [])
            }
        }.background(ProductTheme.canvas)
    }
}

private struct LensControl: View {
    let title: String
    @Binding var enabled: Bool
    @Binding var strength: Double
    @State private var percentageText: String
    @FocusState private var percentageFocused: Bool

    init(title: String, enabled: Binding<Bool>, strength: Binding<Double>) {
        self.title = title; _enabled = enabled; _strength = strength
        _percentageText = State(initialValue: LensStrengthValue.percentText(strength.wrappedValue))
    }

    var body: some View {
        HStack(spacing: 14) {
            Button(action: { enabled.toggle() }) {
                HStack(spacing: 9) {
                    ZStack {
                        Circle().stroke(enabled ? ProductTheme.orange : ProductTheme.strongLine, lineWidth: 1).frame(width: 15, height: 15)
                        if enabled { Circle().fill(ProductTheme.orange).frame(width: 6, height: 6) }
                    }
                    Text(title).font(.system(size: 11, weight: .medium)).foregroundStyle(enabled ? ProductTheme.text : ProductTheme.muted)
                }
                .frame(width: 108, height: 44, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(enabled ? "On" : "Off")
            SignedInstrumentSlider(value: $strength, enabled: enabled)
            HStack(spacing: 3) {
                TextField("", text: $percentageText)
                    .textFieldStyle(.plain).multilineTextAlignment(.trailing)
                    .font(.system(size: 10, weight: .medium).monospacedDigit()).frame(width: 42, height: 36)
                    .focused($percentageFocused).onSubmit(commitPercentage)
                    .onChange(of: percentageFocused) { _, focused in if !focused { commitPercentage() } }
                    .onChange(of: percentageText) { _, text in
                        guard percentageFocused, let parsed = LensStrengthValue.parsedStrength(text),
                              (LensStrengthValue.minimum...LensStrengthValue.maximum).contains(parsed) else { return }
                        strength = parsed
                    }
                Text("%").font(.system(size: 9, weight: .medium)).foregroundStyle(ProductTheme.muted)
            }
            .padding(.horizontal, 8).frame(height: 36).background(ProductTheme.canvas)
            .overlay(Rectangle().stroke(ProductTheme.line)).opacity(enabled ? 1 : 0.45).disabled(!enabled)
        }
        .frame(minHeight: 48).overlay(alignment: .bottom) { Rectangle().fill(ProductTheme.line).frame(height: 1) }
        .onChange(of: strength) { _, value in if !percentageFocused { percentageText = LensStrengthValue.percentText(value) } }
        .accessibilityElement(children: .contain)
    }

    private func commitPercentage() {
        strength = LensStrengthValue.committedStrength(percentageText, fallback: strength)
        percentageText = LensStrengthValue.percentText(strength)
    }
}

private struct SignedInstrumentSlider: View {
    @Binding var value: Double
    let enabled: Bool
    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            let centre = width / 2
            let x = width * (value - LensStrengthValue.minimum) / (LensStrengthValue.maximum - LensStrengthValue.minimum)
            ZStack(alignment: .leading) {
                Rectangle().fill(ProductTheme.strongLine).frame(height: 1)
                Rectangle().fill(ProductTheme.faint).frame(width: 1, height: 11).offset(x: centre)
                Rectangle().fill(ProductTheme.orange).frame(width: abs(x - centre), height: 2).offset(x: min(x, centre))
                Rectangle().fill(enabled ? ProductTheme.orange : ProductTheme.muted).frame(width: 8, height: 18)
                    .offset(x: min(max(0, x - 4), max(0, width - 8)))
            }
            .frame(width: width, height: geometry.size.height)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { gesture in
                guard enabled, width > 0 else { return }
                let fraction = min(max(gesture.location.x / width, 0), 1)
                value = ((LensStrengthValue.minimum + fraction * (LensStrengthValue.maximum - LensStrengthValue.minimum)) * 100).rounded() / 100
            })
        }
        .frame(height: 40).opacity(enabled ? 1 : 0.35)
        .accessibilityElement().accessibilityLabel("\(LensStrengthValue.percentText(value)) percent")
        .accessibilityValue(LensStrengthValue.percentText(value))
        .accessibilityAdjustableAction { direction in
            guard enabled else { return }
            value = LensStrengthValue.clamped(value + (direction == .increment ? 0.05 : -0.05))
        }
    }
}

private struct RailHeading: View {
    let title: String
    let marker: String
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title.uppercased()).font(.system(size: 9, weight: .bold)).tracking(1.4).foregroundStyle(ProductTheme.muted)
            Spacer()
            Text(marker).font(.system(size: 9, weight: .medium).monospacedDigit()).foregroundStyle(ProductTheme.muted)
        }
    }
}

private struct BatchStatusView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.sourceURLs.count > 1 ? "\(model.sourceURLs.count) \(model.t("files"))" : (model.sourceURL?.lastPathComponent ?? model.phase.title(model.language)))
                .font(.system(size: 14, weight: .medium)).lineLimit(1)
            Text(model.message).font(.caption).foregroundStyle(ProductTheme.muted)
            if model.phase.isRunning {
                GeometryReader { geometry in
                    ZStack(alignment: .leading) {
                        Rectangle().fill(ProductTheme.line)
                        Rectangle().fill(ProductTheme.orange).frame(width: geometry.size.width * model.batchProgress)
                    }
                }.frame(height: 2)
            }
            if model.batchItems.count > 1 {
                ScrollView {
                    LazyVStack(spacing: 0) { ForEach(model.batchItems) { item in BatchItemRow(item: item, language: model.language) } }
                }.frame(maxHeight: 180)
            }
            if model.completedItemCount > 0 || (model.phase == .complete && model.latestOutput != nil) {
                VStack(spacing: 8) {
                    Button(action: model.openLatestInPhocus) {
                        HStack {
                            Image(systemName: "camera.viewfinder")
                            Text(model.t("openPhocus"))
                            Spacer()
                            Image(systemName: "arrow.up.right")
                        }
                    }
                    .buttonStyle(CompletionActionStyle(primary: true))

                    Button(action: model.revealLatest) {
                        HStack {
                            Image(systemName: "folder")
                            Text(model.t("reveal"))
                            Spacer()
                            Image(systemName: "arrow.right")
                        }
                    }
                    .buttonStyle(CompletionActionStyle(primary: false))
                }
                .padding(.top, 4)
            }
        }.frame(maxWidth: .infinity, minHeight: 145, alignment: .topLeading)
    }
}

private struct BatchItemRow: View {
    let item: BatchConversionItem
    let language: AppLanguage
    var body: some View {
        HStack(spacing: 9) {
            Circle().fill(color).frame(width: 5, height: 5)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.sourceURL.lastPathComponent).font(.caption).lineLimit(1)
                if let detail = item.detail { Text(detail).font(.caption2).foregroundStyle(ProductTheme.muted).lineLimit(1) }
            }
            Spacer()
            Text(item.phase.title(language)).font(.caption2).foregroundStyle(ProductTheme.muted)
        }.frame(minHeight: 40).overlay(alignment: .bottom) { Rectangle().fill(ProductTheme.line).frame(height: 1) }
    }
    private var color: Color {
        switch item.phase {
        case .complete: .green
        case .failed: .red
        case .converting, .verifying: ProductTheme.orange
        default: ProductTheme.muted
        }
    }
}

private struct RecordRow: View {
    let record: ConversionRecord
    let language: AppLanguage
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(record.outputURL.lastPathComponent).font(.caption).lineLimit(1)
                Text(record.date.formatted(.dateTime.year().month().day().locale(language.locale)))
                    .font(.caption2).foregroundStyle(ProductTheme.muted)
            }
            Spacer()
            Button(Copy.text("show", language)) { NSWorkspace.shared.activateFileViewerSelecting([record.outputURL]) }
                .buttonStyle(QuietTextButtonStyle())
        }.frame(minHeight: 51).overlay(alignment: .bottom) { Rectangle().fill(ProductTheme.line).frame(height: 1) }
    }
}

private struct HeroActionStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.padding(.horizontal, 20).frame(minHeight: 58)
            .background(ProductTheme.orange.opacity(configuration.isPressed ? 0.78 : 1))
            .foregroundStyle(Color.black).font(.system(size: 13, weight: .bold))
            .opacity(isEnabled ? 1 : 0.26)
    }
}

private struct InstrumentActionStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 10, weight: .semibold))
            .foregroundStyle(configuration.isPressed ? ProductTheme.orange : ProductTheme.muted)
            .padding(.horizontal, 10).frame(minWidth: 40, minHeight: 40)
            .contentShape(Rectangle())
            .background(ProductTheme.canvas.opacity(configuration.isPressed ? 0.8 : 0))
    }
}

private struct QuietTextButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 10, weight: .semibold))
            .foregroundStyle(configuration.isPressed ? ProductTheme.text : ProductTheme.orange)
            .padding(.horizontal, 8).frame(minHeight: 40)
            .contentShape(Rectangle())
    }
}

private struct IconButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 9, weight: .semibold))
            .foregroundStyle(isEnabled ? ProductTheme.muted : ProductTheme.faint)
            .frame(width: 40, height: 40)
            .contentShape(Rectangle())
    }
}

private struct SecondaryActionStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 12, weight: .semibold))
            .frame(maxWidth: .infinity, minHeight: 50).foregroundStyle(ProductTheme.text)
            .overlay(Rectangle().stroke(ProductTheme.strongLine))
            .background(ProductTheme.raised.opacity(configuration.isPressed ? 0.8 : 1))
    }
}

private struct CompletionActionStyle: ButtonStyle {
    let primary: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 11, weight: .bold))
            .padding(.horizontal, 14)
            .frame(maxWidth: .infinity, minHeight: 42)
            .contentShape(Rectangle())
            .foregroundStyle(primary ? Color.black.opacity(0.9) : ProductTheme.text)
            .background(primary ? ProductTheme.orange : ProductTheme.raised)
            .overlay(Rectangle().stroke(primary ? Color.clear : ProductTheme.orange.opacity(0.65), lineWidth: 1))
            .opacity(configuration.isPressed ? 0.72 : 1)
    }
}

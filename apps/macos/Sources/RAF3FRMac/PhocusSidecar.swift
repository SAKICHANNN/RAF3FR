import Foundation

struct PhocusRenderingPlan: Equatable {
    struct Grain: Equatable {
        let amount: Int
        let granularity: Int
        let roughness: Int
    }

    let exposureCompensationEV: Double?
    let highlightRecovery: Int?
    let highlightTone: Double?
    let shadowTone: Double?
    let grain: Grain?
    let saturation: Int?
    let contrast: Int?
    let clarity: Int?
    let sharpnessAmount: Int?
    let neutralMonochrome: Bool
    let framing: PhocusFramingPlan?
    let lensCorrectionMask: Int

    static func make(
        settings: ConversionSettings,
        recommendedExposureEV: Double,
        intent: FujiRenderingIntent?,
        framing: FujiFraming? = nil
    ) -> PhocusRenderingPlan {
        let dynamicRange = settings.dynamicRangeEnabled ? intent?.dynamicRange?.percent : nil
        let highlightRecovery: Int? = switch dynamicRange {
        case 200: 10
        case 400: 20
        default: nil
        }
        let tone = settings.toneCurveEnabled ? intent?.toneCurve : nil
        let grainIntent = settings.grainEnabled ? intent?.grain : nil
        let grain: Grain?
        if grainIntent?.enabled == true, let roughness = grainIntent?.roughness {
            let amount = roughness == "strong" ? 40 : 20
            let granularity = grainIntent?.size == "large" ? 50 : 25
            grain = Grain(amount: amount, granularity: granularity, roughness: 15)
        } else {
            grain = nil
        }
        let creative = intent?.creative
        let saturation = settings.colorRenderingEnabled
            ? creative?.color?.step.map { min(40, max(-40, Int(($0 * 10).rounded()))) }
            : nil
        let contrast: Int? = settings.contrastRenderingEnabled
            ? creative?.contrast?.value.flatMap(Self.contrastValue)
            : nil
        let clarity = settings.clarityRenderingEnabled
            ? creative?.clarity?.step.map { min(50, max(-50, Int(($0 * 10).rounded()))) }
            : nil
        let sharpnessAmount = settings.sharpnessRenderingEnabled
            ? creative?.sharpness?.step.map { min(200, max(0, 100 + Int(($0 * 25).rounded()))) }
            : nil
        let monochromeMode = creative?.monochromeMode?.value
        let neutralMonochrome = settings.monochromeRenderingEnabled
            && monochromeMode != nil
            && monochromeMode != "sepia"
        var lensCorrectionMask = 0
        if settings.effectiveDistortion != 0 { lensCorrectionMask |= 2 }
        if settings.effectiveChromaticAberration != 0 { lensCorrectionMask |= 4 }
        if settings.effectiveVignetting > 0 { lensCorrectionMask |= 1 }
        return PhocusRenderingPlan(
            exposureCompensationEV: settings.exposurePolicy == .matchFujifilm ? recommendedExposureEV : nil,
            highlightRecovery: highlightRecovery,
            highlightTone: tone?.highlight,
            shadowTone: tone?.shadow,
            grain: grain,
            saturation: saturation,
            contrast: contrast,
            clarity: clarity,
            sharpnessAmount: sharpnessAmount,
            neutralMonochrome: neutralMonochrome,
            framing: settings.framingEnabled ? PhocusFramingPlan.make(from: framing) : nil,
            lensCorrectionMask: lensCorrectionMask
        )
    }

    private static func contrastValue(_ value: String) -> Int? {
        switch value {
        case "medium-low": -10
        case "low": -20
        case "normal", "film-simulation": 0
        case "medium-high": 10
        case "high": 20
        default: nil
        }
    }
}

struct PhocusFramingPlan: Equatable {
    let left: Double
    let top: Double
    let right: Double
    let bottom: Double

    static func make(from framing: FujiFraming?) -> PhocusFramingPlan? {
        guard let framing,
              let rawSize = pair(framing.rawCrop?.size),
              rawSize.x > 0, rawSize.y > 0 else { return nil }
        let fullWidth = Double(rawSize.x)
        let fullHeight = Double(rawSize.y)
        var x = 0.0
        var y = 0.0
        var width = fullWidth
        var height = fullHeight

        if framing.rawZoom?.active == true,
           let origin = pair(framing.rawZoom?.topLeft),
           let size = pair(framing.rawZoom?.size),
           origin.x >= 0, origin.y >= 0, size.x > 0, size.y > 0,
           origin.x + size.x <= rawSize.x,
           origin.y + size.y <= rawSize.y {
            x = Double(origin.x)
            y = Double(origin.y)
            width = Double(size.x)
            height = Double(size.y)
        }

        if let ratioWidth = framing.aspectRatio?.width,
           let ratioHeight = framing.aspectRatio?.height,
           ratioWidth > 0, ratioHeight > 0 {
            let target = Double(ratioWidth) / Double(ratioHeight)
            let current = width / height
            if current > target {
                let croppedWidth = height * target
                x += (width - croppedWidth) / 2
                width = croppedWidth
            } else if current < target {
                let croppedHeight = width / target
                y += (height - croppedHeight) / 2
                height = croppedHeight
            }
        }

        let plan = PhocusFramingPlan(
            left: x / fullWidth,
            top: y / fullHeight,
            right: (x + width) / fullWidth,
            bottom: (y + height) / fullHeight
        )
        guard plan.left.isFinite, plan.top.isFinite,
              plan.right.isFinite, plan.bottom.isFinite,
              plan.left >= 0, plan.top >= 0,
              plan.right <= 1, plan.bottom <= 1,
              plan.left < plan.right, plan.top < plan.bottom else { return nil }
        return plan
    }

    private static func pair(_ values: [Int]?) -> (x: Int, y: Int)? {
        guard let values, values.count == 2 else { return nil }
        return (values[0], values[1])
    }
}

enum PhocusSidecarWriter {
    private static let templateName = "CleanPhocusTemplate"
    private static let templateExtension = "phos"

    static func destination(for output: URL) -> URL {
        URL(fileURLWithPath: output.path + ".phos")
    }

    static func linearMultiplier(for exposureCompensationEV: Double) throws -> Double {
        guard exposureCompensationEV.isFinite, (-5...5).contains(exposureCompensationEV) else {
            throw CocoaError(.propertyListReadCorrupt)
        }
        return pow(2, exposureCompensationEV)
    }

    @discardableResult
    static func writeIfAbsent(
        for output: URL,
        plan: PhocusRenderingPlan,
        bundle: Bundle = .main
    ) throws -> URL {
        let exposureMultiplier = try plan.exposureCompensationEV.map(linearMultiplier) ?? 1
        let destination = destination(for: output)
        guard !FileManager.default.fileExists(atPath: destination.path) else {
            throw CocoaError(.fileWriteFileExists)
        }
        guard let template = bundle.url(forResource: templateName, withExtension: templateExtension) else {
            throw CocoaError(.fileNoSuchFile)
        }
        let data = try Data(contentsOf: template)
        guard var plist = try PropertyListSerialization.propertyList(
            from: data,
            options: [],
            format: nil
        ) as? [String: Any],
              var settings = plist["ImageSettings"] as? [[String: Any]],
              settings.count == 1,
              var correction = settings[0]["ImageCorrection"] as? [String: Any],
              var description = settings[0]["ImageDescription"] as? [String: Any],
              correction["ApplyCNFilter"] as? Bool == false,
              correction["ApplyNoiseFilterBias"] as? Bool == false,
              correction["USMAmount"] as? Int == 0 else {
            throw CocoaError(.propertyListReadCorrupt)
        }
        correction["ApplyEV"] = plan.exposureCompensationEV != nil
        correction["EV"] = exposureMultiplier
        correction["ApplyLensCorrection"] = plan.lensCorrectionMask != 0
        correction["LensCorrection"] = plan.lensCorrectionMask
        correction["HighlightRecovery"] = plan.highlightRecovery ?? 0
        if let saturation = plan.saturation { correction["Saturation"] = saturation }
        if let contrast = plan.contrast { correction["Contrast"] = contrast }
        if let clarity = plan.clarity {
            correction["Clarity"] = clarity
            correction["ClarityDetail"] = 0
        }
        if let sharpnessAmount = plan.sharpnessAmount {
            correction["ApplyUSM"] = true
            correction["USMAmount"] = sharpnessAmount
            correction["USMRadius"] = 10
            correction["USMNoiseLimit"] = 0
        }
        correction["ApplyGrayScale"] = plan.neutralMonochrome
        if plan.neutralMonochrome {
            correction["GrayScale"] = [100.0, 21.0, 72.0, 7.0]
        }
        correction["ApplyFilmGrain"] = plan.grain != nil
        if let grain = plan.grain {
            correction["FilmGrainAmount"] = grain.amount
            correction["FilmGrainSize"] = grain.granularity
            correction["FilmGrainRoughness"] = grain.roughness
            correction["FilmGrainColor"] = 0
            correction["FilmGrainType"] = 1
        }
        if plan.highlightTone != nil || plan.shadowTone != nil,
           var gradations = correction["Gradations"] as? [[String: Any]],
           !gradations.isEmpty {
            let highlight = plan.highlightTone ?? 0
            let shadow = plan.shadowTone ?? 0
            gradations[0]["Points"] = Self.toneCurvePoints(highlight: highlight, shadow: shadow)
            correction["Gradations"] = gradations
        }
        if let framing = plan.framing,
           var relativeCrop = description["RelativeCrop"] as? [String: Any] {
            relativeCrop["Left"] = framing.left
            relativeCrop["Top"] = framing.top
            relativeCrop["Right"] = framing.right
            relativeCrop["Bottom"] = framing.bottom
            description["RelativeCrop"] = relativeCrop
            description["CropLeft"] = 0.0
            description["CropTop"] = 0.0
            description["CropRight"] = 0.0
            description["CropBottom"] = 0.0
            description["Rotation"] = 0.0
        }
        settings[0]["ImageCorrection"] = correction
        settings[0]["ImageDescription"] = description
        plist["ImageSettings"] = settings
        plist["GUID"] = UUID().uuidString
        let cleanData = try PropertyListSerialization.data(
            fromPropertyList: plist,
            format: .xml,
            options: 0
        )
        let temporary = destination.deletingLastPathComponent()
            .appendingPathComponent(".\(destination.lastPathComponent).\(UUID().uuidString).partial")
        try cleanData.write(to: temporary, options: .atomic)
        defer { try? FileManager.default.removeItem(at: temporary) }
        try FileManager.default.linkItem(at: temporary, to: destination)
        return destination
    }

    private static func toneCurvePoints(highlight: Double, shadow: Double) -> [[String: Any]] {
        let shadowY = min(255, max(0, Int((64 - shadow * 8).rounded())))
        let highlightY = min(255, max(0, Int((192 + highlight * 8).rounded())))
        return [
            ["X": 0, "Y": 0, "DY": 1],
            ["X": 64, "Y": shadowY, "DY": 1],
            ["X": 192, "Y": highlightY, "DY": 1],
            ["X": 255, "Y": 255, "DY": 1],
        ]
    }
}

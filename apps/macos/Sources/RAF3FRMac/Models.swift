import Foundation

enum WhiteBalance: String, CaseIterable, Codable, Identifiable {
    case auto
    case asShot = "as-shot"
    case donor

    var id: String { rawValue }
    func title(_ language: AppLanguage) -> String {
        switch self {
        case .auto: Copy.text("auto", language)
        case .asShot: Copy.text("asShot", language)
        case .donor: Copy.text("donor", language)
        }
    }
}

enum ISOPolicy: String, CaseIterable, Codable, Identifiable {
    case nearestX2D = "nearest-x2d"
    case hnnrStable = "hnnr-stable"
    case capture

    var id: String { rawValue }
    func title(_ language: AppLanguage) -> String {
        switch self {
        case .nearestX2D: Copy.text("isoNearest", language)
        case .hnnrStable: Copy.text("isoHnnrStable", language)
        case .capture: Copy.text("isoCapture", language)
        }
    }
}

enum ExposurePolicy: String, CaseIterable, Codable, Identifiable {
    case matchFujifilm = "match-fujifilm"
    case preserveLinearRaw = "preserve-linear-raw"

    var id: String { rawValue }
    func title(_ language: AppLanguage) -> String {
        switch self {
        case .matchFujifilm: Copy.text("exposureMatchFujifilm", language)
        case .preserveLinearRaw: Copy.text("exposurePreserveRaw", language)
        }
    }
}

enum NegativeVignettePolicy: String, CaseIterable, Codable, Identifiable {
    case fullPlanePhysical = "fullplane-physical"
    case skipExtraVignette = "skip-extra-vignette"

    var id: String { rawValue }
    func title(_ language: AppLanguage) -> String {
        switch self {
        case .fullPlanePhysical: Copy.text("physicalExtraVignette", language)
        case .skipExtraVignette: Copy.text("skipExtraVignette", language)
        }
    }
}

enum DistortionModel: String, CaseIterable, Codable, Identifiable {
    case cameraJpeg = "camera-jpeg"
    case nativeMatch = "native-match"
    case legacyInBounds = "legacy-in-bounds"

    var id: String { rawValue }
    func title(_ language: AppLanguage) -> String {
        switch self {
        case .cameraJpeg: Copy.text("cameraJpegMatch", language)
        case .nativeMatch: Copy.text("nativeMatch", language)
        case .legacyInBounds: Copy.text("legacyInBounds", language)
        }
    }
}

struct HardwarePlan: Equatable {
    let maxConcurrentJobs: Int
    let threadsPerJob: Int

    init(
        requestedParallelJobs: Int,
        cpuCoreLimit: Int,
        memoryLimitGiB: Int,
        processorCount: Int,
        physicalMemory: UInt64
    ) {
        let gib = UInt64(1_073_741_824)
        let processors = max(1, processorCount)
        let cores = min(max(1, cpuCoreLimit), processors)
        let requestedMemory = UInt64(max(2, memoryLimitGiB)) * gib
        let availableMemory = max(2 * gib, min(requestedMemory, physicalMemory))
        let memorySlots = max(1, Int(availableMemory / (4 * gib)))
        maxConcurrentJobs = min(max(1, requestedParallelJobs), cores, memorySlots)
        threadsPerJob = max(1, cores / maxConcurrentJobs)
    }

    var environment: [String: String] {
        let count = String(threadsPerJob)
        return [
            "OMP_NUM_THREADS": count,
            "OPENBLAS_NUM_THREADS": count,
            "VECLIB_MAXIMUM_THREADS": count,
            "NUMEXPR_NUM_THREADS": count,
            "RAYON_NUM_THREADS": count,
        ]
    }
}

struct ConversionSettings: Codable, Equatable {
    var whiteBalance: WhiteBalance = .auto
    var distortionEnabled = true
    var distortionModel: DistortionModel? = .cameraJpeg
    var distortionStrength = 1.0
    var chromaticAberrationEnabled = true
    var chromaticAberrationStrength = 1.0
    var vignettingEnabled = false
    var vignettingStrength = 1.0
    var inverseCalibration = false
    var isoPolicy: ISOPolicy = .hnnrStable
    var exposurePolicy: ExposurePolicy = .matchFujifilm
    var dynamicRangeEnabled = true
    var toneCurveEnabled = true
    var grainEnabled = true
    var colorRenderingEnabled = true
    var contrastRenderingEnabled = true
    var clarityRenderingEnabled = true
    var sharpnessRenderingEnabled = true
    var monochromeRenderingEnabled = true
    var framingEnabled = true
    var preserveLocation = true
    var preserveRights = true
    var preserveProvenance = true
    var negativeVignettePolicy: NegativeVignettePolicy = .fullPlanePhysical
    var maxParallelJobs = 2
    var maxCPUCores = 8
    var memoryLimitGiB = 16
    var sensorMapping = "wb-adaptive-bootstrap"
    var donorLensCorrection = "neutralize"

    var effectiveDistortion: Double { distortionEnabled ? distortionStrength : 0 }
    var effectiveDistortionModel: DistortionModel { distortionModel ?? .cameraJpeg }
    var effectiveChromaticAberration: Double {
        chromaticAberrationEnabled ? chromaticAberrationStrength : 0
    }
    var effectiveVignetting: Double {
        guard vignettingEnabled else { return 0 }
        if vignettingStrength < 0, negativeVignettePolicy == .skipExtraVignette { return 0 }
        return vignettingStrength
    }

    func convertArguments(source: URL, donor: URL, output: URL) -> [String] {
        [
            "convert", source.path,
            "--template", donor.path,
            "--output", output.path,
            "--white-balance", whiteBalance.rawValue,
            "--iso-policy", isoPolicy.rawValue,
            "--sensor-mapping", sensorMapping,
            "--donor-lens-correction", donorLensCorrection,
            "--distortion-model", effectiveDistortionModel.rawValue,
            "--distortion-strength", Self.number(effectiveDistortion),
            "--ca-strength", Self.number(effectiveChromaticAberration),
            "--vignetting-strength", Self.number(effectiveVignetting),
        ]
        + (inverseCalibration ? ["--inverse-x2d-calibration"] : [])
        + (preserveLocation ? [] : ["--remove-location"])
        + (preserveRights ? [] : ["--remove-rights"])
        + (preserveProvenance ? [] : ["--remove-provenance"])
    }

    private static func number(_ value: Double) -> String {
        String(format: "%.4f", locale: Locale(identifier: "en_US_POSIX"), value)
    }
}

struct FujiRenderingIntent: Decodable, Equatable {
    struct CodedLabel: Decodable, Equatable {
        let code: Int?
        let value: String?
    }

    struct CodedStep: Decodable, Equatable {
        let code: Int?
        let step: Double?
    }

    struct Creative: Decodable, Equatable {
        struct LensModulationOptimizer: Decodable, Equatable {
            let code: Int?
            let enabled: Bool?
        }

        let filmSimulation: CodedLabel?
        let color: CodedStep?
        let monochromeMode: CodedLabel?
        let monochromeWarmCool: Int?
        let monochromeMagentaGreen: Int?
        let colorChrome: CodedLabel?
        let colorChromeBlue: CodedLabel?
        let clarity: CodedStep?
        let sharpness: CodedStep?
        let highIsoNoiseReduction: CodedStep?
        let contrast: CodedLabel?
        let lensModulationOptimizer: LensModulationOptimizer?
    }

    struct DynamicRange: Decodable, Equatable {
        let percent: Int?
        let source: String?
        let priorityMode: String?
        let priorityLevel: String?
    }

    struct ToneCurve: Decodable, Equatable {
        let highlight: Double?
        let shadow: Double?
    }

    struct Grain: Decodable, Equatable {
        let enabled: Bool?
        let roughness: String?
        let size: String?
    }

    let dynamicRange: DynamicRange?
    let toneCurve: ToneCurve?
    let grain: Grain?
    let creative: Creative?

    var toneText: String? {
        guard let toneCurve, toneCurve.highlight != nil || toneCurve.shadow != nil else { return nil }
        func value(_ number: Double?) -> String {
            guard let number else { return "—" }
            return String(format: "%+.1f", locale: Locale(identifier: "en_US_POSIX"), number)
        }
        return "H \(value(toneCurve.highlight)) · S \(value(toneCurve.shadow))"
    }

    func grainText(_ language: AppLanguage) -> String? {
        guard let grain, let roughness = grain.roughness else { return nil }
        if grain.enabled != true || roughness == "off" { return Copy.text("off", language) }
        let strength = roughness == "strong" ? Copy.text("strong", language) : Copy.text("weak", language)
        let size = grain.size == "large" ? Copy.text("large", language) : Copy.text("small", language)
        return "\(strength) · \(size)"
    }
}

struct FujiStandardMetadata: Decodable, Equatable {
    struct Time: Decodable, Equatable {
        let dateTimeOriginal: String?
        let createDate: String?
        let modifyDate: String?
        let offsetTime: String?
        let offsetTimeOriginal: String?
        let offsetTimeDigitized: String?
        let subsecTime: Int?
        let subsecTimeOriginal: Int?
        let subsecTimeDigitized: Int?
    }

    struct Location: Decodable, Equatable {
        let present: Bool?
        let latitude: Double?
        let longitude: Double?
        let altitudeM: Double?
        let gpsDateStamp: String?
        let gpsTimeStamp: String?
        let mapDatum: String?
    }

    struct Rights: Decodable, Equatable {
        let rating: Int?
        let artist: String?
        let copyright: String?
        let userComment: String?
    }

    struct Provenance: Decodable, Equatable {
        let originalMake: String?
        let originalModel: String?
        let sourceFirmware: String?
    }

    let time: Time?
    let location: Location?
    let rights: Rights?
    let provenance: Provenance?
}

struct FujiCaptureState: Decodable, Equatable {
    struct CodedLabel: Decodable, Equatable {
        let code: Int?
        let value: String?
    }

    struct Warnings: Decodable, Equatable {
        let blur: Int?
        let focus: Int?
        let exposure: Int?
    }

    struct SourceEncoding: Decodable, Equatable {
        let rafCompressionCode: Int?
        let bitsPerSample: Int?
    }

    let shutterType: CodedLabel?
    let focusMode: CodedLabel?
    let afMode: CodedLabel?
    let focusPixel: [Int]?
    let driveMode: CodedLabel?
    let flashExposureCompensationEv: Double?
    let flickerReductionCode: Int?
    let cameraElevationDegrees: Double?
    let cameraRollDegrees: Double?
    let compositeImageCode: Int?
    let warnings: Warnings?
    let sourceEncoding: SourceEncoding?
}

struct FujiFraming: Decodable, Equatable {
    struct AspectRatio: Decodable, Equatable {
        let width: Int?
        let height: Int?
        let source: String?
    }

    struct RawZoom: Decodable, Equatable {
        let active: Bool?
        let topLeft: [Int]?
        let size: [Int]?
        let cropMode: Int?
    }

    struct RawCrop: Decodable, Equatable {
        let topLeft: [Int]?
        let size: [Int]?
    }

    let orientation: Int?
    let aspectRatio: AspectRatio?
    let rawZoom: RawZoom?
    let rawCrop: RawCrop?
    let source: String?
}

struct SourcePresentation: Decodable, Equatable {
    struct FileFacts: Decodable, Equatable { let name: String; let bytes: Int64 }
    struct CameraFacts: Decodable, Equatable { let make: String; let model: String }
    struct LensFacts: Decodable, Equatable { let make: String; let model: String }
    struct CaptureFacts: Decodable, Equatable {
        let exposureTimeSeconds: Double
        let fNumber: Double
        let iso: Int
        let isoSource: String
        let focalLengthMm: Double
        let focalLengthEquivalentMm: Int
        let exposureCompensationEv: Double
        let rawExposureBiasEv: Double?
        let recommendedPhocusCompensationEv: Double?
        let dynamicRangePercent: Int?
        let dateTimeOriginal: String
        let offsetTimeOriginal: String
        let whiteBalanceCode: Int
        let colorTemperatureKelvin: Double?

        var shutterText: String {
            if exposureTimeSeconds > 0, exposureTimeSeconds < 1 {
                return "1/\(Int((1 / exposureTimeSeconds).rounded()))"
            }
            return Self.number(exposureTimeSeconds) + "s"
        }
        var apertureText: String { "ƒ/" + Self.number(fNumber) }
        var focalLengthText: String { Self.number(focalLengthMm) + " mm" }
        var compensationText: String {
            if abs(exposureCompensationEv) < 0.005 { return "0 EV" }
            return String(format: "%+.2f EV", locale: Locale(identifier: "en_US_POSIX"), exposureCompensationEv)
        }
        var phocusCompensationText: String {
            let value = recommendedPhocusCompensationEv ?? -(rawExposureBiasEv ?? 0)
            return String(
                format: "%+.2f EV",
                locale: Locale(identifier: "en_US_POSIX"),
                value
            )
        }
        var captureDateText: String {
            let value = dateTimeOriginal.replacingOccurrences(of: ":", with: ".", options: [], range: dateTimeOriginal.startIndex..<dateTimeOriginal.index(dateTimeOriginal.startIndex, offsetBy: min(10, dateTimeOriginal.count)))
            return offsetTimeOriginal.isEmpty ? value : "\(value)  \(offsetTimeOriginal)"
        }
        func whiteBalanceText(_ language: AppLanguage) -> String {
            if let colorTemperatureKelvin, colorTemperatureKelvin > 0 {
                return "\(Int(colorTemperatureKelvin.rounded())) K"
            }
            return whiteBalanceCode == 0 ? Copy.text("auto", language) : "WB \(whiteBalanceCode)"
        }
        private static func number(_ value: Double) -> String {
            value.rounded() == value ? String(Int(value)) : String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), value)
        }
    }
    struct ImageFacts: Decodable, Equatable { let width: Int; let height: Int }
    struct PreviewFacts: Decodable, Equatable { let path: String; let bytes: Int64 }

    let schemaVersion: Int
    let file: FileFacts
    let camera: CameraFacts
    let lens: LensFacts
    let capture: CaptureFacts
    let renderingIntent: FujiRenderingIntent?
    let framing: FujiFraming?
    let standardMetadata: FujiStandardMetadata?
    let captureState: FujiCaptureState?
    let image: ImageFacts
    let preview: PreviewFacts?

    static func decode(_ data: Data) throws -> SourcePresentation {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(SourcePresentation.self, from: data)
    }

    static func exiftool(_ data: Data, source: URL, preview: URL?) throws -> SourcePresentation {
        guard let rows = try JSONSerialization.jsonObject(with: data) as? [[String: Any]],
              let row = rows.first else { throw SourcePresentationError.invalidMetadata }
        func number(_ keys: String...) -> Double? {
            for key in keys {
                if let value = row[key] as? NSNumber { return value.doubleValue }
                if let value = row[key] as? String, let parsed = Double(value) { return parsed }
            }
            return nil
        }
        func string(_ keys: String..., fallback: String = "") -> String {
            for key in keys { if let value = row[key] as? String, !value.isEmpty { return value } }
            return fallback
        }
        let focalLength = number("ExifIFD:FocalLength") ?? 0
        let equivalent = number("ExifIFD:FocalLengthIn35mmFormat", "Composite:FocalLength35efl")
            ?? focalLength * hypot(36, 24) / hypot(43.8, 32.9)
        let rawSize = string("RAF:RawImageCroppedSize").split(separator: " ").compactMap { Int(Double($0) ?? 0) }
        let developmentDynamicRange = number("FujiFilm:DevelopmentDynamicRange")
        let autoDynamicRange = number("FujiFilm:AutoDynamicRange")
        let priorityModeCode = number("FujiFilm:DRangePriority").map { Int($0.rounded()) }
        let priorityLevelCode = number("FujiFilm:DRangePriorityFixed", "FujiFilm:DRangePriorityAuto").map { Int($0.rounded()) }
        let priorityLevel: String? = switch priorityLevelCode {
        case 1: "weak"
        case 2: "strong"
        case 3: "plus"
        default: nil
        }
        let inferredDynamicRange = priorityLevel == "weak" ? 200 : ((priorityLevel == "strong" || priorityLevel == "plus") ? 400 : nil)
        let dynamicRange = developmentDynamicRange ?? autoDynamicRange
        let dynamicRangePercent = dynamicRange.map { Int($0.rounded()) } ?? inferredDynamicRange
        func toneStep(_ key: String) -> Double? {
            guard let raw = number(key) else { return nil }
            let decoded = -raw / 16
            guard (-2...4).contains(decoded), abs(decoded * 2 - (decoded * 2).rounded()) < 0.000_001 else { return nil }
            return decoded
        }
        func grainLabel(_ key: String, labels: [Int: String]) -> String? {
            guard let code = number(key).map({ Int($0.rounded()) }) else { return nil }
            return labels[code]
        }
        let grainRoughness = grainLabel("FujiFilm:GrainEffectRoughness", labels: [0: "off", 32: "weak", 64: "strong"])
        let grainSize = grainLabel("FujiFilm:GrainEffectSize", labels: [0: "off", 16: "small", 32: "large"])
        let attributes = try FileManager.default.attributesOfItem(atPath: source.path)
        let fileBytes = (attributes[.size] as? NSNumber)?.int64Value ?? 0
        let previewFacts: PreviewFacts?
        if let preview, FileManager.default.fileExists(atPath: preview.path) {
            let previewAttributes = try FileManager.default.attributesOfItem(atPath: preview.path)
            previewFacts = PreviewFacts(path: preview.path, bytes: (previewAttributes[.size] as? NSNumber)?.int64Value ?? 0)
        } else {
            previewFacts = nil
        }
        return SourcePresentation(
            schemaVersion: 1,
            file: FileFacts(name: source.lastPathComponent, bytes: fileBytes),
            camera: CameraFacts(make: string("IFD0:Make", fallback: "FUJIFILM"), model: string("IFD0:Model", fallback: "GFX100RF")),
            lens: LensFacts(make: string("ExifIFD:LensMake", fallback: "FUJIFILM"), model: string("ExifIFD:LensModel", fallback: "35mm F4")),
            capture: CaptureFacts(
                exposureTimeSeconds: number("ExifIFD:ExposureTime") ?? 0,
                fNumber: number("ExifIFD:FNumber") ?? 0,
                iso: Int((number("ExifIFD:StandardOutputSensitivity") ?? number("ExifIFD:ISO") ?? 0).rounded()),
                isoSource: row["ExifIFD:StandardOutputSensitivity"] == nil ? "ExifIFD:ISO" : "ExifIFD:StandardOutputSensitivity",
                focalLengthMm: focalLength,
                focalLengthEquivalentMm: Int(equivalent.rounded()),
                exposureCompensationEv: number("ExifIFD:ExposureCompensation") ?? 0,
                rawExposureBiasEv: number("RAF:RawExposureBias"),
                recommendedPhocusCompensationEv: number("RAF:RawExposureBias").map { -$0 },
                dynamicRangePercent: dynamicRangePercent,
                dateTimeOriginal: string("ExifIFD:DateTimeOriginal"),
                offsetTimeOriginal: string("ExifIFD:OffsetTimeOriginal"),
                whiteBalanceCode: Int((number("FujiFilm:WhiteBalance", "ExifIFD:WhiteBalance") ?? 0).rounded()),
                colorTemperatureKelvin: number("FujiFilm:ColorTemperature")
            ),
            renderingIntent: FujiRenderingIntent(
                dynamicRange: .init(
                    percent: dynamicRangePercent,
                    source: developmentDynamicRange != nil ? "FujiFilm:DevelopmentDynamicRange" : (autoDynamicRange != nil ? "FujiFilm:AutoDynamicRange" : (inferredDynamicRange != nil ? "inferred_from_priority" : nil)),
                    priorityMode: priorityModeCode == 0 ? "auto" : (priorityModeCode == 1 ? "fixed" : nil),
                    priorityLevel: priorityLevel
                ),
                toneCurve: .init(highlight: toneStep("FujiFilm:HighlightTone"), shadow: toneStep("FujiFilm:ShadowTone")),
                grain: .init(enabled: grainRoughness.map { $0 != "off" }, roughness: grainRoughness, size: grainSize),
                creative: nil
            ),
            framing: nil,
            standardMetadata: nil,
            captureState: nil,
            image: ImageFacts(width: rawSize.first ?? 0, height: rawSize.dropFirst().first ?? 0),
            preview: previewFacts
        )
    }
}

enum SourcePresentationError: Error { case toolUnavailable, invalidMetadata, invalidPreview }

struct BatchConversionItem: Identifiable, Equatable {
    let id: UUID
    let sourceURL: URL
    var outputURL: URL?
    var phase: JobPhase
    var detail: String?

    init(sourceURL: URL) {
        id = UUID()
        self.sourceURL = sourceURL
        outputURL = nil
        phase = .selected
        detail = nil
    }
}

enum BatchSelectionRemovalPlan {
    static func nextIndex(removing currentIndex: Int, fromCount count: Int) -> Int? {
        guard count > 1, (0..<count).contains(currentIndex) else { return nil }
        return min(currentIndex, count - 2)
    }
}

enum BatchOutputPlanner {
    static func destinations(
        sources: [URL],
        directory: URL,
        isUnavailable: (URL) -> Bool
    ) -> [URL] {
        var reserved = Set<String>()
        return sources.map { source in
            let stem = source.deletingPathExtension().lastPathComponent
            var suffix = 1
            while true {
                let name = suffix == 1 ? "\(stem)-HNCS.3FR" : "\(stem)-HNCS-\(suffix).3FR"
                let candidate = directory.appendingPathComponent(name)
                let manifest = candidate.appendingPathExtension("json")
                if !reserved.contains(candidate.standardizedFileURL.path),
                   !isUnavailable(candidate), !isUnavailable(manifest) {
                    reserved.insert(candidate.standardizedFileURL.path)
                    return candidate
                }
                suffix += 1
            }
        }
    }
}

enum LensStrengthValue {
    static let minimum = -2.0
    static let maximum = 2.0

    static func clamped(_ strength: Double) -> Double {
        min(max(strength, minimum), maximum)
    }

    static func percentText(_ strength: Double) -> String {
        let percent = clamped(strength) * 100
        if percent.rounded() == percent {
            return String(Int(percent))
        }
        return String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"), percent)
    }

    static func parsedStrength(_ text: String) -> Double? {
        let normalized = text
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: ",", with: ".")
        guard let percent = Double(normalized), percent.isFinite else { return nil }
        return percent / 100
    }

    static func committedStrength(_ text: String, fallback: Double) -> Double {
        guard let parsed = parsedStrength(text) else { return clamped(fallback) }
        return clamped(parsed)
    }
}

enum JobPhase: String, Codable {
    case idle
    case selected
    case converting
    case verifying
    case complete
    case failed
    case cancelled

    func title(_ language: AppLanguage) -> String {
        switch self {
        case .idle: Copy.text("ready", language)
        case .selected: Copy.text("selected", language)
        case .converting: Copy.text("converting", language)
        case .verifying: Copy.text("verifying", language)
        case .complete: Copy.text("complete", language)
        case .failed: Copy.text("failed", language)
        case .cancelled: Copy.text("cancelled", language)
        }
    }

    var isRunning: Bool { self == .converting || self == .verifying }
}

struct ConversionRecord: Codable, Identifiable, Equatable {
    let id: UUID
    let sourceName: String
    let outputPath: String
    let date: Date
    let outputSHA256: String?

    var outputURL: URL { URL(fileURLWithPath: outputPath) }
}

struct EngineResponse: Decodable {
    struct Output: Decodable { let sha256: String? }
    struct CaptureMetadata: Decodable {
        struct ExposureMatching: Decodable {
            let recommendedPhocusCompensationEv: Double?
        }
        let exposureMatching: ExposureMatching?
        let renderingIntent: FujiRenderingIntent?
        let framing: FujiFraming?
    }
    let output: Output?
    let captureMetadata: CaptureMetadata?
}

enum EngineError: LocalizedError {
    case unavailable
    case failed(String)
    case cancelled

    var errorDescription: String? {
        switch self {
        case .unavailable: "转换引擎不可用"
        case .failed(let message): message.isEmpty ? "转换引擎失败" : message
        case .cancelled: "转换已取消"
        }
    }
}

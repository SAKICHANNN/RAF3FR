import Foundation

@main
enum ModelChecks {
    static func main() {
        let defaults = ConversionSettings()
        precondition(defaults.effectiveDistortion == 1)
        precondition(defaults.effectiveDistortionModel == .cameraJpeg)
        precondition(defaults.effectiveChromaticAberration == 1)
        precondition(defaults.effectiveVignetting == 0)
        precondition(defaults.whiteBalance == .auto)
        precondition(defaults.isoPolicy == .hnnrStable)
        precondition(defaults.exposurePolicy == .matchFujifilm)
        precondition(defaults.dynamicRangeEnabled)
        precondition(defaults.toneCurveEnabled)
        precondition(defaults.grainEnabled)
        precondition(defaults.colorRenderingEnabled)
        precondition(defaults.contrastRenderingEnabled)
        precondition(defaults.clarityRenderingEnabled)
        precondition(defaults.sharpnessRenderingEnabled)
        precondition(defaults.monochromeRenderingEnabled)
        precondition(defaults.framingEnabled)
        precondition(defaults.preserveLocation)
        precondition(defaults.preserveRights)
        precondition(defaults.preserveProvenance)
        precondition(defaults.negativeVignettePolicy == .fullPlanePhysical)
        let constrained = HardwarePlan(
            requestedParallelJobs: 4, cpuCoreLimit: 8, memoryLimitGiB: 10,
            processorCount: 12, physicalMemory: 32 * 1_073_741_824
        )
        precondition(constrained.maxConcurrentJobs == 2)
        precondition(constrained.threadsPerJob == 4)
        precondition(constrained.environment["RAYON_NUM_THREADS"] == "4")
        precondition(BatchSelectionRemovalPlan.nextIndex(removing: 0, fromCount: 3) == 0)
        precondition(BatchSelectionRemovalPlan.nextIndex(removing: 1, fromCount: 3) == 1)
        precondition(BatchSelectionRemovalPlan.nextIndex(removing: 2, fromCount: 3) == 1)
        precondition(BatchSelectionRemovalPlan.nextIndex(removing: 1, fromCount: 2) == 0)
        precondition(BatchSelectionRemovalPlan.nextIndex(removing: 0, fromCount: 1) == nil)
        precondition(BatchSelectionRemovalPlan.nextIndex(removing: 3, fromCount: 3) == nil)
        let planned = BatchOutputPlanner.destinations(
            sources: [
                URL(fileURLWithPath: "/a/DSCF0001.RAF"),
                URL(fileURLWithPath: "/b/DSCF0001.RAF"),
            ],
            directory: URL(fileURLWithPath: "/output"),
            isUnavailable: { $0.lastPathComponent == "DSCF0001-HNCS.3FR" }
        )
        precondition(planned.map(\.lastPathComponent) == ["DSCF0001-HNCS-2.3FR", "DSCF0001-HNCS-3.3FR"])

        var settings = defaults
        settings.distortionEnabled = false
        settings.chromaticAberrationStrength = 1.25
        settings.vignettingEnabled = true
        settings.vignettingStrength = 0.7
        let arguments = settings.convertArguments(
            source: URL(fileURLWithPath: "/tmp/input.RAF"),
            donor: URL(fileURLWithPath: "/tmp/donor.3FR"),
            output: URL(fileURLWithPath: "/tmp/output.3FR")
        )
        for expected in ["0.0000", "1.2500", "0.7000", "wb-adaptive-bootstrap"] {
            precondition(arguments.contains(expected), "missing argument \(expected)")
        }
        precondition(arguments.contains("camera-jpeg"))
        settings.distortionModel = .nativeMatch
        precondition(settings.convertArguments(
            source: URL(fileURLWithPath: "/tmp/input.RAF"),
            donor: URL(fileURLWithPath: "/tmp/donor.3FR"),
            output: URL(fileURLWithPath: "/tmp/output.3FR")
        ).contains("native-match"))
        settings.distortionModel = .legacyInBounds
        precondition(settings.convertArguments(
            source: URL(fileURLWithPath: "/tmp/input.RAF"),
            donor: URL(fileURLWithPath: "/tmp/donor.3FR"),
            output: URL(fileURLWithPath: "/tmp/output.3FR")
        ).contains("legacy-in-bounds"))
        precondition(Copy.text("convertRaw", .zh) == "转换 RAW")
        precondition(Copy.text("convertRaw", .en) == "Convert RAW")
        precondition(Copy.text("removeCurrentSelection", .zh) == "从选择中移除当前 RAF")
        precondition(Copy.text("removeCurrentSelection", .en) == "Remove current RAF from selection")
        settings.isoPolicy = .hnnrStable
        let stableArguments = settings.convertArguments(
            source: URL(fileURLWithPath: "/tmp/input.RAF"),
            donor: URL(fileURLWithPath: "/tmp/donor.3FR"),
            output: URL(fileURLWithPath: "/tmp/output.3FR")
        )
        precondition(stableArguments.contains("--iso-policy"))
        precondition(stableArguments.contains("hnnr-stable"))
        var privateSettings = settings
        privateSettings.preserveLocation = false
        privateSettings.preserveRights = false
        privateSettings.preserveProvenance = false
        let privateArguments = privateSettings.convertArguments(
            source: URL(fileURLWithPath: "/tmp/input.RAF"),
            donor: URL(fileURLWithPath: "/tmp/donor.3FR"),
            output: URL(fileURLWithPath: "/tmp/output.3FR")
        )
        for flag in ["--remove-location", "--remove-rights", "--remove-provenance"] {
            precondition(privateArguments.contains(flag))
        }
        settings.vignettingStrength = -0.7
        settings.negativeVignettePolicy = .skipExtraVignette
        let safeArguments = settings.convertArguments(
            source: URL(fileURLWithPath: "/tmp/input.RAF"),
            donor: URL(fileURLWithPath: "/tmp/donor.3FR"),
            output: URL(fileURLWithPath: "/tmp/output.3FR")
        )
        precondition(safeArguments.contains("0.0000"))
        settings.negativeVignettePolicy = .fullPlanePhysical
        let vignetteArguments = settings.convertArguments(
            source: URL(fileURLWithPath: "/tmp/input.RAF"),
            donor: URL(fileURLWithPath: "/tmp/donor.3FR"),
            output: URL(fileURLWithPath: "/tmp/output.3FR")
        )
        precondition(vignetteArguments.contains("-0.7000"))
        precondition(EngineCommand.locate(bundle: Bundle(for: Marker.self), environment: [:]) == nil)
        precondition(DonorSelectionPolicy.source(useExternalOverride: false, hasExternalDonor: false) == .bundled)
        precondition(DonorSelectionPolicy.source(useExternalOverride: false, hasExternalDonor: true) == .bundled)
        precondition(DonorSelectionPolicy.source(useExternalOverride: true, hasExternalDonor: true) == .external)
        precondition(DonorSelectionPolicy.source(useExternalOverride: true, hasExternalDonor: false) == .bundled)
        precondition(AppDefaults.launch(environment: [:], arguments: []) === UserDefaults.standard)
        let isolatedSuite = "app.raf3fr.converter.test.model-checks-v060"
        let isolatedDefaults = AppDefaults.launch(
            environment: [:],
            arguments: ["--raf3fr-test-defaults-suite=\(isolatedSuite)"]
        )
        precondition(isolatedDefaults !== UserDefaults.standard)
        precondition(isolatedDefaults.data(forKey: "conversionRecords") == Data("[]".utf8))
        precondition(isolatedDefaults.bool(forKey: "useExternalX2DDonor") == false)
        precondition(isolatedDefaults.string(forKey: "appLanguage") == "en")
        precondition(LensStrengthValue.percentText(1) == "100")
        precondition(LensStrengthValue.parsedStrength("125.5") == 1.255)
        precondition(LensStrengthValue.parsedStrength("125,5") == 1.255)
        precondition(LensStrengthValue.committedStrength("-100", fallback: 1) == -1)
        precondition(LensStrengthValue.committedStrength("-250", fallback: 1) == -2)
        precondition(LensStrengthValue.committedStrength("250", fallback: 1) == 2)
        precondition(LensStrengthValue.committedStrength("bad", fallback: 1.25) == 1.25)
        let sourceJSON = Data("""
        {
          "schema_version": 2,
          "file": {"name":"DSCF0001.RAF","bytes":123},
          "camera": {"make":"FUJIFILM","model":"GFX100RF"},
          "lens": {"make":"FUJIFILM","model":"35mm F4"},
          "capture": {"exposure_time_seconds":0.004,"f_number":4,"iso":6400,"iso_source":"ExifIFD:StandardOutputSensitivity","focal_length_mm":35,"focal_length_equivalent_mm":28,"exposure_compensation_ev":-0.67,"raw_exposure_bias_ev":-1.72,"recommended_phocus_compensation_ev":1.72,"dynamic_range_percent":200,"date_time_original":"2026:08:28 13:44:50","offset_time_original":"+08:00","white_balance_code":0,"color_temperature_kelvin":null},
          "rendering_intent": {"dynamic_range":{"percent":200,"source":"FujiFilm:DevelopmentDynamicRange","priority_mode":null,"priority_level":null},"tone_curve":{"highlight":1.0,"shadow":-0.5},"grain":{"enabled":true,"roughness":"strong","size":"large"},"creative":{"film_simulation":{"code":1281,"value":"pro-neg-hi"},"color":{"code":192,"step":3},"monochrome_mode":{"code":192,"value":null},"monochrome_warm_cool":null,"monochrome_magenta_green":null,"color_chrome":{"code":64,"value":"strong"},"color_chrome_blue":{"code":32,"value":"weak"},"clarity":{"code":1000,"step":1},"sharpness":{"code":132,"step":1},"high_iso_noise_reduction":{"code":640,"step":-1},"contrast":{"code":0,"value":"normal"},"lens_modulation_optimizer":{"code":1,"enabled":true}}},
          "framing": {"orientation":1,"aspect_ratio":{"width":4,"height":3,"source":"RAF:RawImageAspectRatio"},"raw_zoom":{"active":true,"top_left":[1296,972],"size":[9056,6792],"crop_mode":8},"raw_crop":{"top_left":[7,8],"size":[11648,8736]},"source":"Fujifilm RAF framing metadata"},
          "standard_metadata": {"time":{"date_time_original":"2026:08:28 13:44:50","create_date":"2026:08:28 13:44:50","modify_date":"2026:08:28 13:44:50","offset_time":"+08:00","offset_time_original":"+08:00","offset_time_digitized":"+08:00","subsec_time":79,"subsec_time_original":79,"subsec_time_digitized":79},"location":{"present":true,"latitude":30.2440888889,"longitude":120.1619713889,"altitude_m":20,"gps_date_stamp":"2026:08:28","gps_time_stamp":"05:44:50","map_datum":"WGS-84"},"rights":{"rating":4,"artist":"Miao","copyright":"Copyright Miao","user_comment":"note"},"provenance":{"original_make":"FUJIFILM","original_model":"GFX100RF","source_firmware":"0112"}},
          "capture_state": {"shutter_type":{"code":0,"value":"mechanical"},"focus_mode":{"code":0,"value":"auto"},"af_mode":{"code":1,"value":"single-point"},"focus_pixel":[2107,1499],"drive_mode":{"code":0,"value":"single"},"flash_exposure_compensation_ev":0,"flicker_reduction_code":0,"camera_elevation_degrees":12.4,"camera_roll_degrees":0,"composite_image_code":1,"warnings":{"blur":0,"focus":0,"exposure":0},"source_encoding":{"raf_compression_code":2,"bits_per_sample":16}},
          "image": {"width":11648,"height":8736},
          "preview": {"path":"/tmp/preview.jpg","bytes":456}
        }
        """.utf8)
        let sourcePresentation = try! SourcePresentation.decode(sourceJSON)
        precondition(sourcePresentation.capture.shutterText == "1/250")
        precondition(sourcePresentation.capture.apertureText == "ƒ/4")
        precondition(sourcePresentation.capture.compensationText == "-0.67 EV")
        precondition(sourcePresentation.capture.phocusCompensationText == "+1.72 EV")
        precondition(sourcePresentation.capture.dynamicRangePercent == 200)
        precondition(sourcePresentation.renderingIntent?.toneText == "H +1.0 · S -0.5")
        precondition(sourcePresentation.renderingIntent?.grainText(.en) == "Strong · Large")
        precondition(sourcePresentation.renderingIntent?.creative?.filmSimulation?.value == "pro-neg-hi")
        precondition(sourcePresentation.renderingIntent?.creative?.clarity?.step == 1)
        precondition(sourcePresentation.standardMetadata?.location?.latitude == 30.2440888889)
        precondition(sourcePresentation.standardMetadata?.rights?.rating == 4)
        precondition(sourcePresentation.captureState?.cameraElevationDegrees == 12.4)
        precondition(sourcePresentation.captureState?.sourceEncoding?.bitsPerSample == 16)
        precondition(sourcePresentation.capture.whiteBalanceText(.zh) == "自动")
        let defaultRenderingPlan = PhocusRenderingPlan.make(
            settings: defaults,
            recommendedExposureEV: 1.72,
            intent: sourcePresentation.renderingIntent,
            framing: sourcePresentation.framing
        )
        precondition(defaultRenderingPlan.lensCorrectionMask == 6)
        var positiveVignetteSettings = defaults
        positiveVignetteSettings.vignettingEnabled = true
        positiveVignetteSettings.vignettingStrength = 1
        precondition(PhocusRenderingPlan.make(
            settings: positiveVignetteSettings,
            recommendedExposureEV: 0,
            intent: nil
        ).lensCorrectionMask == 7)
        var negativeVignetteSettings = positiveVignetteSettings
        negativeVignetteSettings.vignettingStrength = -1
        precondition(PhocusRenderingPlan.make(
            settings: negativeVignetteSettings,
            recommendedExposureEV: 0,
            intent: nil
        ).lensCorrectionMask == 6)
        precondition(defaultRenderingPlan.exposureCompensationEV == 1.72)
        precondition(defaultRenderingPlan.highlightRecovery == 15)
        precondition(defaultRenderingPlan.shadowFill == nil)
        precondition(defaultRenderingPlan.highlightTone == 1)
        precondition(defaultRenderingPlan.shadowTone == -0.5)
        precondition(defaultRenderingPlan.grain == .init(amount: 40, granularity: 50, roughness: 15))
        precondition(defaultRenderingPlan.saturation == 15)
        precondition(defaultRenderingPlan.contrast == 0)
        precondition(defaultRenderingPlan.clarity == 10)
        precondition(defaultRenderingPlan.sharpnessAmount == 125)
        precondition(!defaultRenderingPlan.neutralMonochrome)
        precondition(abs((defaultRenderingPlan.framing?.left ?? -1) - (1296.0 / 11648.0)) < 1e-12)
        precondition(abs((defaultRenderingPlan.framing?.top ?? -1) - (972.0 / 8736.0)) < 1e-12)
        precondition(abs((defaultRenderingPlan.framing?.right ?? -1) - (10352.0 / 11648.0)) < 1e-12)
        precondition(abs((defaultRenderingPlan.framing?.bottom ?? -1) - (7764.0 / 8736.0)) < 1e-12)
        let panoramicFraming = FujiFraming(
            orientation: 1,
            aspectRatio: .init(width: 65, height: 24, source: "RAF:RawImageAspectRatio"),
            rawZoom: .init(active: false, topLeft: [0, 0], size: [11648, 8736], cropMode: 0),
            rawCrop: .init(topLeft: [7, 8], size: [11648, 8736]),
            source: "Fujifilm RAF framing metadata"
        )
        let panoramicPlan = PhocusFramingPlan.make(from: panoramicFraming)!
        precondition(abs((panoramicPlan.right - panoramicPlan.left) / (panoramicPlan.bottom - panoramicPlan.top) - 65.0 / 24.0 * 8736.0 / 11648.0) < 1e-12)
        precondition(abs(panoramicPlan.top - (1 - panoramicPlan.bottom)) < 1e-12)
        let squareFraming = FujiFraming(
            orientation: 8,
            aspectRatio: .init(width: 1, height: 1, source: "RAF:RawImageAspectRatio"),
            rawZoom: .init(active: false, topLeft: [0, 0], size: [11648, 8736], cropMode: 0),
            rawCrop: .init(topLeft: [7, 8], size: [11648, 8736]),
            source: "Fujifilm RAF framing metadata"
        )
        let squarePlan = PhocusFramingPlan.make(from: squareFraming)!
        precondition(abs(squarePlan.left - (1 - squarePlan.right)) < 1e-12)
        precondition(squarePlan.top == 0 && squarePlan.bottom == 1)
        let monochromeData = Data("""
        {"creative":{"monochrome_mode":{"code":1281,"value":"acros-red-filter"}}}
        """.utf8)
        let monochromeDecoder = JSONDecoder()
        monochromeDecoder.keyDecodingStrategy = .convertFromSnakeCase
        let monochromeIntent = try! monochromeDecoder.decode(FujiRenderingIntent.self, from: monochromeData)
        let monochromePlan = PhocusRenderingPlan.make(
            settings: defaults,
            recommendedExposureEV: 0,
            intent: monochromeIntent
        )
        precondition(monochromePlan.neutralMonochrome)
        var linearSettings = defaults
        linearSettings.exposurePolicy = .preserveLinearRaw
        linearSettings.dynamicRangeEnabled = false
        let linearPlan = PhocusRenderingPlan.make(
            settings: linearSettings,
            recommendedExposureEV: 1.72,
            intent: sourcePresentation.renderingIntent
        )
        precondition(linearPlan.exposureCompensationEV == nil)
        precondition(linearPlan.highlightRecovery == nil)
        precondition(linearPlan.shadowFill == nil)
        precondition(abs((try! PhocusSidecarWriter.linearMultiplier(for: 0.72)) - 1.6471820345) < 1e-9)
        precondition(abs((try! PhocusSidecarWriter.linearMultiplier(for: 1.72)) - 3.2943640691) < 1e-9)
        do {
            _ = try PhocusSidecarWriter.linearMultiplier(for: 6)
            preconditionFailure("out-of-range sidecar exposure must fail")
        } catch {}
        if let appPath = ProcessInfo.processInfo.environment["RAF3FR_APP_BUNDLE"],
           let appBundle = Bundle(path: appPath) {
            precondition(ProductVersion.short(in: appBundle) == "V 0.9.7")
            precondition(ProductVersion.detailed(in: appBundle) == "V 0.9.7  ·  BUILD 18")
            let probeDirectory = FileManager.default.temporaryDirectory
                .appendingPathComponent("raf3fr-sidecar-\(UUID().uuidString)", isDirectory: true)
            try! FileManager.default.createDirectory(at: probeDirectory, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: probeDirectory) }
            let probeOutput = probeDirectory.appendingPathComponent("DSCF0001.3FR")
            var renderingSettings = defaults
            renderingSettings.toneCurveEnabled = true
            renderingSettings.grainEnabled = true
            let renderingPlan = PhocusRenderingPlan.make(
                settings: renderingSettings,
                recommendedExposureEV: 1.72,
                intent: sourcePresentation.renderingIntent,
                framing: sourcePresentation.framing
            )
            precondition(renderingPlan.highlightRecovery == 15)
            precondition(renderingPlan.grain == .init(amount: 40, granularity: 50, roughness: 15))
            let sidecar = try! PhocusSidecarWriter.writeIfAbsent(
                for: probeOutput,
                plan: renderingPlan,
                bundle: appBundle
            )
            let sidecarData = try! Data(contentsOf: sidecar)
            let sidecarPlist = try! PropertyListSerialization.propertyList(
                from: sidecarData, options: [], format: nil
            ) as! [String: Any]
            let imageSettings = sidecarPlist["ImageSettings"] as! [[String: Any]]
            let correction = imageSettings[0]["ImageCorrection"] as! [String: Any]
            precondition(abs((correction["EV"] as! Double) - 3.2943640691) < 1e-9)
            precondition(correction["ApplyEV"] as? Bool == true)
            precondition(correction["HighlightRecovery"] as? Int == 15)
            precondition(correction["ShadowFill"] as? Int == 0)
            precondition(correction["ApplyFilmGrain"] as? Bool == true)
            precondition(correction["FilmGrainAmount"] as? Int == 40)
            precondition(correction["FilmGrainSize"] as? Int == 50)
            precondition(correction["Saturation"] as? Int == 15)
            precondition(correction["Contrast"] as? Int == 0)
            precondition(correction["Clarity"] as? Int == 10)
            precondition(correction["USMAmount"] as? Int == 125)
            precondition(correction["ApplyUSM"] as? Bool == true)
            precondition(correction["ApplyGrayScale"] as? Bool == false)
            let gradations = correction["Gradations"] as! [[String: Any]]
            let points = gradations[0]["Points"] as! [[String: Any]]
            precondition(points[1]["Y"] as? Int == 69)
            precondition(points[2]["Y"] as? Int == 202)
            precondition(correction["ApplyCNFilter"] as? Bool == false)
            precondition(correction["ApplyNoiseFilterBias"] as? Bool == false)
            precondition(correction["ApplyLensCorrection"] as? Bool == true)
            precondition(correction["LensCorrection"] as? Int == 6)
            let description = imageSettings[0]["ImageDescription"] as! [String: Any]
            let relativeCrop = description["RelativeCrop"] as! [String: Any]
            precondition(abs((relativeCrop["Left"] as! Double) - 1296.0 / 11648.0) < 1e-12)
            precondition(abs((relativeCrop["Top"] as! Double) - 972.0 / 8736.0) < 1e-12)
            precondition(description["Rotation"] as? Double == 0)

            let monochromeOutput = probeDirectory.appendingPathComponent("DSCF0002.3FR")
            let monochromeSidecar = try! PhocusSidecarWriter.writeIfAbsent(
                for: monochromeOutput,
                plan: monochromePlan,
                bundle: appBundle
            )
            let monochromePlist = try! PropertyListSerialization.propertyList(
                from: Data(contentsOf: monochromeSidecar), options: [], format: nil
            ) as! [String: Any]
            let monochromeCorrection = (monochromePlist["ImageSettings"] as! [[String: Any]])[0]["ImageCorrection"] as! [String: Any]
            precondition(monochromeCorrection["ApplyGrayScale"] as? Bool == true)
            precondition(monochromeCorrection["GrayScale"] as? [Double] == [100, 21, 72, 7])
            precondition(monochromeCorrection["ApplyCNFilter"] as? Bool == false)
            precondition(monochromeCorrection["ApplyNoiseFilterBias"] as? Bool == false)
        }
        let responseJSON = Data("""
        {"output":{"sha256":"abc"},"capture_metadata":{"exposure_matching":{"recommended_phocus_compensation_ev":1.72},"rendering_intent":{"dynamic_range":{"percent":400},"tone_curve":{"highlight":0.0,"shadow":0.0},"grain":{"enabled":false}},"framing":{"orientation":8,"aspect_ratio":{"width":1,"height":1},"raw_zoom":{"active":false,"top_left":[0,0],"size":[11648,8736],"crop_mode":0},"raw_crop":{"top_left":[7,8],"size":[11648,8736]}}}}
        """.utf8)
        let responseDecoder = JSONDecoder()
        responseDecoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try! responseDecoder.decode(EngineResponse.self, from: responseJSON)
        precondition(response.captureMetadata?.exposureMatching?.recommendedPhocusCompensationEv == 1.72)
        precondition(response.captureMetadata?.renderingIntent?.dynamicRange?.percent == 400)
        let dr400Plan = PhocusRenderingPlan.make(
            settings: defaults,
            recommendedExposureEV: 2.72,
            intent: response.captureMetadata?.renderingIntent
        )
        precondition(dr400Plan.highlightRecovery == 30)
        precondition(dr400Plan.shadowFill == nil)
        let dr100Intent = try! responseDecoder.decode(
            FujiRenderingIntent.self,
            from: Data("{\"dynamic_range\":{\"percent\":100}}".utf8)
        )
        let dr100Plan = PhocusRenderingPlan.make(
            settings: defaults,
            recommendedExposureEV: 0.72,
            intent: dr100Intent
        )
        precondition(dr100Plan.highlightRecovery == nil)
        let priorityJSON = Data("""
        {"dynamic_range":{"percent":400,"priority_mode":"fixed","priority_level":"strong"}}
        """.utf8)
        let priorityIntent = try! responseDecoder.decode(FujiRenderingIntent.self, from: priorityJSON)
        let priorityPlan = PhocusRenderingPlan.make(
            settings: defaults,
            recommendedExposureEV: 2.72,
            intent: priorityIntent
        )
        precondition(priorityPlan.highlightRecovery == 30)
        precondition(priorityPlan.shadowFill == 20)
        if let donorPath = ProcessInfo.processInfo.environment["RAF3FR_BUNDLED_DONOR"] {
            try! BundledDonor.validate(URL(fileURLWithPath: donorPath))
        }
        do {
            try BundledDonor.validate(URL(fileURLWithPath: "/tmp/raf3fr-missing-template.3FR"))
            preconditionFailure("missing donor must fail validation")
        } catch BundledDonorError.unreadable {
        } catch {
            preconditionFailure("unexpected missing donor error: \(error)")
        }
        let truncatedDonor = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("raf3fr-truncated-template.3FR")
        try! Data("not a donor".utf8).write(to: truncatedDonor, options: .atomic)
        do {
            try BundledDonor.validate(truncatedDonor)
            preconditionFailure("truncated donor must fail validation")
        } catch BundledDonorError.wrongSize {
        } catch {
            preconditionFailure("unexpected truncated donor error: \(error)")
        }
        print("macOS model checks passed")
    }
}

private final class Marker {}

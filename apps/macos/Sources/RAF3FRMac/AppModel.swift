import AppKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers
import UserNotifications

@MainActor
final class AppModel: ObservableObject {
    @Published var sourceURLs: [URL] = []
    @Published var batchItems: [BatchConversionItem] = []
    @Published var donorURL: URL?
    @Published private(set) var donorSource: DonorSource = .bundled
    @Published private(set) var externalDonorURL: URL?
    @Published private(set) var bundledDonorError: BundledDonorError?
    @Published var settings = ConversionSettings()
    @Published var phase: JobPhase = .idle
    @Published var message = "Select a RAF to begin"
    @Published var errorMessage: String?
    @Published var latestOutput: URL?
    @Published var records: [ConversionRecord] = []
    @Published private(set) var sourcePresentation: SourcePresentation?
    @Published private(set) var sourcePresentationLoading = false
    @Published private(set) var sourcePresentationUnavailable = false
    @Published private(set) var sourcePresentationIndex = 0
    @Published private(set) var notificationsEnabled: Bool
    @Published var language: AppLanguage {
        didSet { refreshMessageForLanguage() }
    }

    private var runners: [UUID: EngineRunner] = [:]
    private var conversionTask: Task<Void, Never>?
    private var sourcePresentationTask: Task<Void, Never>?
    private var sourcePresentationRunner: SourcePresentationLoader?
    private var sourcePresentationToken = UUID()
    private var sourcePreviewURL: URL?
    private let defaults: UserDefaults
    private let bookmarkKey = "x2dDonorBookmark"
    private let donorPathKey = "x2dDonorPath"
    private let externalOverrideKey = "useExternalX2DDonor"
    private let recordsKey = "conversionRecords"
    private let notificationsKey = "completionNotifications"
    private let maxParallelJobsKey = "maxParallelJobs"
    private let maxCPUCoresKey = "maxCPUCores"
    private let memoryLimitGiBKey = "memoryLimitGiB"

    init(defaults: UserDefaults = .standard, bundle: Bundle = .main) {
        self.defaults = defaults
        language = .en
        notificationsEnabled = defaults.bool(forKey: notificationsKey)
        let machineCores = max(1, ProcessInfo.processInfo.activeProcessorCount)
        let machineMemoryGiB = max(2, Int(ProcessInfo.processInfo.physicalMemory / 1_073_741_824))
        settings.maxParallelJobs = defaults.object(forKey: maxParallelJobsKey) == nil
            ? min(2, machineCores)
            : max(1, defaults.integer(forKey: maxParallelJobsKey))
        settings.maxCPUCores = defaults.object(forKey: maxCPUCoresKey) == nil
            ? machineCores
            : min(machineCores, max(1, defaults.integer(forKey: maxCPUCoresKey)))
        settings.memoryLimitGiB = defaults.object(forKey: memoryLimitGiBKey) == nil
            ? max(2, machineMemoryGiB - min(8, max(2, machineMemoryGiB / 4)))
            : min(machineMemoryGiB, max(2, defaults.integer(forKey: memoryLimitGiBKey)))
        do {
            donorURL = try BundledDonor.resolve(in: bundle)
        } catch let error as BundledDonorError {
            bundledDonorError = error
        } catch {
            bundledDonorError = .unreadable
        }
        restoreExternalDonor()
        let selectedSource = DonorSelectionPolicy.source(
            useExternalOverride: defaults.bool(forKey: externalOverrideKey),
            hasExternalDonor: externalDonorURL != nil
        )
        if selectedSource == .external, let externalDonorURL {
            donorURL = externalDonorURL
            donorSource = .external
        } else {
            defaults.set(false, forKey: externalOverrideKey)
        }
        restoreRecords()
        refreshMessageForLanguage()
    }

    var canConvert: Bool {
        !sourceURLs.isEmpty && donorURL != nil && bundledDonorError == nil && !phase.isRunning
    }
    var sourceURL: URL? { sourceURLs.first }
    var completedItemCount: Int { batchItems.filter { $0.phase == .complete }.count }
    var terminalItemCount: Int {
        batchItems.filter { [.complete, .failed, .cancelled].contains($0.phase) }.count
    }
    var batchProgress: Double {
        batchItems.isEmpty ? 0 : Double(terminalItemCount) / Double(batchItems.count)
    }
    var hardwarePlan: HardwarePlan {
        HardwarePlan(
            requestedParallelJobs: settings.maxParallelJobs,
            cpuCoreLimit: settings.maxCPUCores,
            memoryLimitGiB: settings.memoryLimitGiB,
            processorCount: ProcessInfo.processInfo.activeProcessorCount,
            physicalMemory: ProcessInfo.processInfo.physicalMemory
        )
    }
    var blockingError: String? {
        if let bundledDonorError { return t(bundledDonorError.localizationKey) }
        return errorMessage
    }
    func t(_ key: String) -> String { Copy.text(key, language) }
    func toggleLanguage() { language = language == .zh ? .en : .zh }
    var processorCount: Int { max(1, ProcessInfo.processInfo.activeProcessorCount) }
    var physicalMemoryGiB: Int { max(2, Int(ProcessInfo.processInfo.physicalMemory / 1_073_741_824)) }
    func setMaxParallelJobs(_ value: Int) {
        settings.maxParallelJobs = min(16, max(1, value))
        defaults.set(settings.maxParallelJobs, forKey: maxParallelJobsKey)
    }
    func setMaxCPUCores(_ value: Int) {
        settings.maxCPUCores = min(processorCount, max(1, value))
        defaults.set(settings.maxCPUCores, forKey: maxCPUCoresKey)
    }
    func setMemoryLimitGiB(_ value: Int) {
        settings.memoryLimitGiB = min(physicalMemoryGiB, max(2, value))
        defaults.set(settings.memoryLimitGiB, forKey: memoryLimitGiBKey)
    }
    func setNotificationsEnabled(_ enabled: Bool) {
        guard enabled else {
            notificationsEnabled = false
            defaults.set(false, forKey: notificationsKey)
            return
        }
        Task { await requestNotifications() }
    }

    func chooseSource() {
        guard !phase.isRunning else { return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "raf")!]
        panel.allowsMultipleSelection = true
        panel.message = t("chooseRafPanel")
        if panel.runModal() == .OK { selectSources(panel.urls) }
    }

    func selectSource(_ url: URL) {
        selectSources([url])
    }

    func selectSources(_ urls: [URL]) {
        guard !phase.isRunning else { return }
        var seen = Set<String>()
        let valid = urls.filter { url in
            guard url.pathExtension.lowercased() == "raf" else { return false }
            return seen.insert(url.standardizedFileURL.path).inserted
        }
        guard !valid.isEmpty else {
            errorMessage = t("invalidRaf")
            return
        }
        sourceURLs = valid
        batchItems = valid.map(BatchConversionItem.init)
        phase = .selected
        message = selectionMessage
        errorMessage = nil
        loadSourcePresentation(at: 0)
    }

    func clearSelection() {
        guard !phase.isRunning else { return }
        sourceURLs = []
        batchItems = []
        phase = .idle
        message = t("selectToStart")
        errorMessage = nil
        clearSourcePresentation()
    }

    func showPreviousSourcePresentation() {
        guard !sourceURLs.isEmpty else { return }
        loadSourcePresentation(at: max(0, sourcePresentationIndex - 1))
    }

    func showNextSourcePresentation() {
        guard !sourceURLs.isEmpty else { return }
        loadSourcePresentation(at: min(sourceURLs.count - 1, sourcePresentationIndex + 1))
    }

    private func loadSourcePresentation(at index: Int) {
        guard sourceURLs.indices.contains(index) else { return }
        sourcePresentationTask?.cancel()
        sourcePresentationRunner?.cancel()
        let token = UUID()
        sourcePresentationToken = token
        sourcePresentationIndex = index
        sourcePresentation = nil
        sourcePresentationLoading = true
        sourcePresentationUnavailable = false
        let source = sourceURLs[index]
        let preview = FileManager.default.temporaryDirectory
            .appendingPathComponent("RAF3FR-preview-\(UUID().uuidString).jpg")
        let runner = SourcePresentationLoader()
        sourcePresentationRunner = runner
        sourcePresentationTask = Task { [weak self] in
            guard let self else { return }
            do {
                let presentation = try await runner.load(source: source, preview: preview)
                guard !Task.isCancelled, sourcePresentationToken == token else {
                    try? FileManager.default.removeItem(at: preview)
                    return
                }
                if let old = sourcePreviewURL, old != preview { try? FileManager.default.removeItem(at: old) }
                sourcePreviewURL = preview
                sourcePresentation = presentation
                sourcePresentationLoading = false
                sourcePresentationUnavailable = false
            } catch {
                try? FileManager.default.removeItem(at: preview)
                guard !Task.isCancelled, sourcePresentationToken == token else { return }
                sourcePresentation = nil
                sourcePresentationLoading = false
                sourcePresentationUnavailable = true
            }
            sourcePresentationRunner = nil
        }
    }

    private func clearSourcePresentation() {
        sourcePresentationTask?.cancel()
        sourcePresentationRunner?.cancel()
        sourcePresentationTask = nil
        sourcePresentationRunner = nil
        sourcePresentationToken = UUID()
        sourcePresentation = nil
        sourcePresentationLoading = false
        sourcePresentationUnavailable = false
        sourcePresentationIndex = 0
        if let sourcePreviewURL { try? FileManager.default.removeItem(at: sourcePreviewURL) }
        sourcePreviewURL = nil
    }

    func chooseDonor() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "3fr")!]
        panel.allowsMultipleSelection = false
        panel.message = t("chooseDonorPanel")
        if panel.runModal() == .OK, let url = panel.url { setDonor(url) }
    }

    func setDonor(_ url: URL) {
        guard url.pathExtension.lowercased() == "3fr" else {
            errorMessage = t("invalidDonor")
            return
        }
        donorURL = url
        externalDonorURL = url
        donorSource = .external
        defaults.set(true, forKey: externalOverrideKey)
        do {
            let data = try url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil, relativeTo: nil)
            defaults.set(data, forKey: bookmarkKey)
            defaults.set(url.path, forKey: donorPathKey)
            errorMessage = nil
        } catch {
            errorMessage = "\(t("permissionError")): \(error.localizedDescription)"
        }
    }

    func useBundledDonor() {
        do {
            donorURL = try BundledDonor.resolve()
            bundledDonorError = nil
            donorSource = .bundled
            defaults.set(false, forKey: externalOverrideKey)
            errorMessage = nil
        } catch let error as BundledDonorError {
            bundledDonorError = error
            donorURL = nil
        } catch {
            bundledDonorError = .unreadable
            donorURL = nil
        }
    }

    func startConversion() {
        guard !sourceURLs.isEmpty, let donorURL, !phase.isRunning else { return }
        let outputs: [URL]
        if sourceURLs.count == 1, let sourceURL {
            let save = NSSavePanel()
            save.allowedContentTypes = [UTType(filenameExtension: "3fr")!]
            save.nameFieldStringValue = sourceURL.deletingPathExtension().lastPathComponent + "-HNCS.3FR"
            save.directoryURL = sourceURL.deletingLastPathComponent()
            guard save.runModal() == .OK, let outputURL = save.url else { return }
            guard !FileManager.default.fileExists(atPath: outputURL.path),
                  !FileManager.default.fileExists(atPath: outputURL.appendingPathExtension("json").path),
                  !FileManager.default.fileExists(atPath: PhocusSidecarWriter.destination(for: outputURL).path) else {
                errorMessage = t("outputExists")
                return
            }
            outputs = [outputURL]
        } else {
            let panel = NSOpenPanel()
            panel.canChooseFiles = false
            panel.canChooseDirectories = true
            panel.canCreateDirectories = true
            panel.allowsMultipleSelection = false
            panel.directoryURL = sourceURL?.deletingLastPathComponent()
            panel.message = t("chooseOutputFolder")
            guard panel.runModal() == .OK, let directory = panel.url else { return }
            outputs = BatchOutputPlanner.destinations(
                sources: sourceURLs,
                directory: directory,
                isUnavailable: {
                    FileManager.default.fileExists(atPath: $0.path)
                        || FileManager.default.fileExists(atPath: $0.appendingPathExtension("json").path)
                        || FileManager.default.fileExists(atPath: PhocusSidecarWriter.destination(for: $0).path)
                }
            )
        }
        batchItems = zip(sourceURLs, outputs).map { source, output in
            var item = BatchConversionItem(sourceURL: source)
            item.outputURL = output
            return item
        }
        conversionTask = Task { [weak self] in
            guard let self else { return }
            await self.convertBatch(donor: donorURL)
        }
    }

    func cancel() {
        conversionTask?.cancel()
        for runner in runners.values { runner.cancel() }
    }

    func revealLatest() {
        let outputs = completedOutputs
        guard !outputs.isEmpty else { return }
        NSWorkspace.shared.activateFileViewerSelecting(outputs)
    }

    func openLatestInPhocus() {
        let outputs = completedOutputs
        guard !outputs.isEmpty else { return }
        guard let phocus = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "dk.hasselblad.phocus") else {
            for output in outputs { NSWorkspace.shared.open(output) }
            return
        }
        let configuration = NSWorkspace.OpenConfiguration()
        NSWorkspace.shared.open(outputs, withApplicationAt: phocus, configuration: configuration)
    }

    private func convertBatch(donor: URL) async {
        let jobs = batchItems.compactMap { item -> BatchJob? in
            guard let output = item.outputURL else { return nil }
            let runner = EngineRunner()
            runners[item.id] = runner
            return BatchJob(id: item.id, source: item.sourceURL, output: output, runner: runner)
        }
        let settingsSnapshot = settings
        let plan = hardwarePlan
        phase = .converting
        errorMessage = nil
        message = batchRunningMessage
        var nextIndex = 0
        await withTaskGroup(of: BatchResult.self) { group in
            func enqueue(_ job: BatchJob) {
                group.addTask { [weak self] in
                    guard let self else { return .cancelled(job.id) }
                    return await self.convertItem(
                        job, donor: donor, settings: settingsSnapshot,
                        environment: plan.environment
                    )
                }
            }
            while nextIndex < min(plan.maxConcurrentJobs, jobs.count) {
                enqueue(jobs[nextIndex])
                nextIndex += 1
            }
            while let result = await group.next() {
                apply(result)
                if !Task.isCancelled, nextIndex < jobs.count {
                    enqueue(jobs[nextIndex])
                    nextIndex += 1
                }
            }
        }
        if Task.isCancelled {
            for index in batchItems.indices where ![.complete, .failed].contains(batchItems[index].phase) {
                batchItems[index].phase = .cancelled
                batchItems[index].detail = nil
            }
            phase = .cancelled
            message = t("cancelled")
        } else {
            let failures = batchItems.filter { $0.phase == .failed }.count
            phase = failures == 0 ? .complete : .failed
            message = batchCompletionMessage(failures: failures)
            if failures > 0 { errorMessage = message }
            if let output = batchItems.first(where: { $0.phase == .complete })?.outputURL {
                latestOutput = output
            }
            await sendCompletionNotification(message)
        }
        runners.removeAll()
        conversionTask = nil
    }

    private func convertItem(
        _ job: BatchJob,
        donor: URL,
        settings: ConversionSettings,
        environment: [String: String]
    ) async -> BatchResult {
        updateItem(job.id, phase: .converting)
        let sourceAccess = job.source.startAccessingSecurityScopedResource()
        let donorAccess = donor.startAccessingSecurityScopedResource()
        let outputAccess = job.output.deletingLastPathComponent().startAccessingSecurityScopedResource()
        defer {
            if sourceAccess { job.source.stopAccessingSecurityScopedResource() }
            if donorAccess { donor.stopAccessingSecurityScopedResource() }
            if outputAccess { job.output.deletingLastPathComponent().stopAccessingSecurityScopedResource() }
        }
        do {
            try Task.checkCancellation()
            let payload = try await job.runner.run(
                settings.convertArguments(source: job.source, donor: donor, output: job.output),
                environmentOverrides: environment
            )
            updateItem(job.id, phase: .verifying)
            _ = try await job.runner.run(
                ["verify", donor.path, job.output.path],
                environmentOverrides: environment
            )
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let response = try? decoder.decode(EngineResponse.self, from: payload)
            let recommendedExposure = response?.captureMetadata?.exposureMatching?
                .recommendedPhocusCompensationEv ?? 0
            let renderingPlan = PhocusRenderingPlan.make(
                settings: settings,
                recommendedExposureEV: recommendedExposure,
                intent: response?.captureMetadata?.renderingIntent,
                framing: response?.captureMetadata?.framing
            )
            try PhocusSidecarWriter.writeIfAbsent(
                for: job.output,
                plan: renderingPlan
            )
            return .success(job.id, source: job.source, output: job.output, sha256: response?.output?.sha256)
        } catch is CancellationError {
            return .cancelled(job.id)
        } catch EngineError.cancelled {
            return .cancelled(job.id)
        } catch {
            return .failure(job.id, detail: describe(error))
        }
    }

    private func apply(_ result: BatchResult) {
        switch result {
        case .success(let id, let source, let output, let sha256):
            updateItem(id, phase: .complete, detail: output.lastPathComponent)
            records.insert(ConversionRecord(
                id: UUID(), sourceName: source.lastPathComponent, outputPath: output.path,
                date: Date(), outputSHA256: sha256
            ), at: 0)
            records = Array(records.prefix(20))
            latestOutput = output
            persistRecords()
        case .failure(let id, let detail):
            updateItem(id, phase: .failed, detail: detail)
        case .cancelled(let id):
            updateItem(id, phase: .cancelled)
        }
        message = batchRunningMessage
    }

    private func updateItem(_ id: UUID, phase: JobPhase, detail: String? = nil) {
        guard let index = batchItems.firstIndex(where: { $0.id == id }) else { return }
        batchItems[index].phase = phase
        batchItems[index].detail = detail
    }

    private func restoreExternalDonor() {
        if let data = defaults.data(forKey: bookmarkKey) {
            var stale = false
            if let url = try? URL(resolvingBookmarkData: data, options: .withSecurityScope, relativeTo: nil, bookmarkDataIsStale: &stale) {
                externalDonorURL = url
                if stale {
                    if let refreshed = try? url.bookmarkData(
                        options: .withSecurityScope,
                        includingResourceValuesForKeys: nil,
                        relativeTo: nil
                    ) {
                        defaults.set(refreshed, forKey: bookmarkKey)
                    }
                }
                return
            }
        }
        if let path = defaults.string(forKey: donorPathKey), FileManager.default.fileExists(atPath: path) {
            externalDonorURL = URL(fileURLWithPath: path)
        }
    }

    private func restoreRecords() {
        guard let data = defaults.data(forKey: recordsKey),
              let decoded = try? JSONDecoder().decode([ConversionRecord].self, from: data) else { return }
        records = decoded.filter { FileManager.default.fileExists(atPath: $0.outputPath) }
        latestOutput = records.first?.outputURL
    }

    private func persistRecords() {
        if let data = try? JSONEncoder().encode(records) { defaults.set(data, forKey: recordsKey) }
    }

    private func refreshMessageForLanguage() {
        switch phase {
        case .idle: message = t("selectToStart")
        case .selected: message = selectionMessage
        case .converting, .verifying: message = batchRunningMessage
        case .complete:
            message = batchItems.count > 1 ? batchCompletionMessage(failures: 0) : (latestOutput?.lastPathComponent ?? t("complete"))
        case .failed:
            let failures = batchItems.filter { $0.phase == .failed }.count
            message = batchItems.isEmpty ? t("failed") : batchCompletionMessage(failures: failures)
            if !batchItems.isEmpty { errorMessage = message }
        case .cancelled: message = t("cancelled")
        }
    }

    private func describe(_ error: Error) -> String {
        switch error {
        case EngineError.unavailable: return t("engineUnavailable")
        case EngineError.failed(let detail): return detail.isEmpty ? t("engineFailed") : detail
        case EngineError.cancelled: return t("cancelled")
        default: return error.localizedDescription
        }
    }

    private func requestNotifications() async {
        do {
            let granted = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
            notificationsEnabled = granted
            defaults.set(granted, forKey: notificationsKey)
            if !granted { errorMessage = t("notificationDenied") }
        } catch {
            notificationsEnabled = false
            defaults.set(false, forKey: notificationsKey)
            errorMessage = error.localizedDescription
        }
    }

    private var selectionMessage: String {
        sourceURLs.count == 1 ? (sourceURL?.lastPathComponent ?? t("selected"))
            : "\(sourceURLs.count) \(t("filesSelected"))"
    }

    private var completedOutputs: [URL] {
        let batch = batchItems.compactMap { $0.phase == .complete ? $0.outputURL : nil }
        if !batch.isEmpty { return batch }
        return latestOutput.map { [$0] } ?? []
    }

    private var batchRunningMessage: String {
        if batchItems.count <= 1 { return t("processingActive") }
        return "\(terminalItemCount) / \(batchItems.count) · \(t("batchProcessing"))"
    }

    private func batchCompletionMessage(failures: Int) -> String {
        if failures == 0 { return "\(completedItemCount) \(t("batchComplete"))" }
        return "\(completedItemCount) \(t("batchComplete")) · \(failures) \(t("batchFailed"))"
    }

    private func sendCompletionNotification(_ detail: String) async {
        guard notificationsEnabled else { return }
        let content = UNMutableNotificationContent()
        content.title = t("notificationTitle")
        content.body = detail
        content.sound = .default
        try? await UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        )
    }
}

private struct BatchJob {
    let id: UUID
    let source: URL
    let output: URL
    let runner: EngineRunner
}

private enum BatchResult {
    case success(UUID, source: URL, output: URL, sha256: String?)
    case failure(UUID, detail: String)
    case cancelled(UUID)
}

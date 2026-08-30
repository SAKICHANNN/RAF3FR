import Foundation

final class SourcePresentationLoader: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?

    func load(source: URL, preview: URL) async throws -> SourcePresentation {
        let exiftool = try locateExiftool()
        let tags = [
            "Make", "Model", "LensMake", "LensModel", "ExposureTime", "FNumber",
            "ISO", "SensitivityType", "StandardOutputSensitivity", "DateTimeOriginal",
            "OffsetTimeOriginal", "ExposureCompensation", "FocalLength",
            "RawExposureBias", "DevelopmentDynamicRange", "AutoDynamicRange",
            "DynamicRangeSetting", "DRangePriority", "DRangePriorityAuto", "DRangePriorityFixed",
            "HighlightTone", "ShadowTone", "GrainEffectRoughness", "GrainEffectSize",
            "FocalLengthIn35mmFormat", "FocalLength35efl", "WhiteBalance",
            "ColorTemperature", "RawImageCroppedSize",
        ]
        let metadata = try await run(
            executable: exiftool,
            arguments: ["-j", "-n", "-G1", "-s"] + tags.map { "-\($0)" } + [source.path]
        )
        let partial = preview.appendingPathExtension("partial")
        try? FileManager.default.removeItem(at: partial)
        do {
            try await runToFile(
                executable: exiftool,
                arguments: ["-PreviewImage", "-b", source.path],
                destination: partial
            )
            let handle = try FileHandle(forReadingFrom: partial)
            let head = try handle.read(upToCount: 2) ?? Data()
            try handle.seekToEnd()
            let size = try handle.offset()
            try handle.seek(toOffset: size > 2 ? size - 2 : 0)
            let tail = try handle.read(upToCount: 2) ?? Data()
            try handle.close()
            guard head == Data([0xff, 0xd8]), tail == Data([0xff, 0xd9]) else {
                throw SourcePresentationError.invalidPreview
            }
            try? FileManager.default.removeItem(at: preview)
            try FileManager.default.moveItem(at: partial, to: preview)
        } catch {
            try? FileManager.default.removeItem(at: partial)
            if Task.isCancelled { throw error }
        }
        return try SourcePresentation.exiftool(
            metadata,
            source: source,
            preview: FileManager.default.fileExists(atPath: preview.path) ? preview : nil
        )
    }

    func cancel() {
        lock.withSourcePresentationLock {
            guard let process, process.isRunning else { return }
            process.terminate()
        }
    }

    private func locateExiftool() throws -> URL {
        let environment = ProcessInfo.processInfo.environment
        let candidates = [
            Bundle.main.resourceURL?.appendingPathComponent("Tools/bin/exiftool"),
            environment["RAF2HNCS_TOOL_DIR"].map { URL(fileURLWithPath: $0).appendingPathComponent("exiftool") },
            environment["RAF2HNCS_REPO_ROOT"].map { URL(fileURLWithPath: $0).appendingPathComponent(".tools/bin/exiftool") },
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent(".tools/bin/exiftool"),
        ].compactMap { $0 }
        guard let found = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0.path) }) else {
            throw SourcePresentationError.toolUnavailable
        }
        return found
    }

    private func run(executable: URL, arguments: [String]) async throws -> Data {
        let pipe = Pipe()
        return try await launch(executable: executable, arguments: arguments, standardOutput: pipe) {
            pipe.fileHandleForReading.readDataToEndOfFile()
        }
    }

    private func runToFile(executable: URL, arguments: [String], destination: URL) async throws {
        FileManager.default.createFile(atPath: destination.path, contents: nil)
        let handle = try FileHandle(forWritingTo: destination)
        _ = try await launch(executable: executable, arguments: arguments, standardOutput: handle) {
            try handle.close()
            return Data()
        }
    }

    private func launch(
        executable: URL,
        arguments: [String],
        standardOutput: Any,
        collect: @escaping @Sendable () throws -> Data
    ) async throws -> Data {
        let task = Process()
        let stderr = Pipe()
        task.executableURL = executable
        task.arguments = arguments
        task.standardOutput = standardOutput
        task.standardError = stderr
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                task.terminationHandler = { [weak self] completed in
                    self?.lock.withSourcePresentationLock { self?.process = nil }
                    do {
                        let output = try collect()
                        if completed.terminationStatus == 0 {
                            continuation.resume(returning: output)
                        } else {
                            continuation.resume(throwing: EngineError.failed(String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""))
                        }
                    } catch { continuation.resume(throwing: error) }
                }
                do {
                    try task.run()
                    lock.withSourcePresentationLock { process = task }
                } catch { continuation.resume(throwing: error) }
            }
        }, onCancel: { [weak self] in self?.cancel() })
    }
}

private extension NSLock {
    func withSourcePresentationLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock(); defer { unlock() }
        return try operation()
    }
}

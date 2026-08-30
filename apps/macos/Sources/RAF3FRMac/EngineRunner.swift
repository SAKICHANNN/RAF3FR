import Foundation

struct EngineCommand: Equatable {
    let executable: URL
    let prefixArguments: [String]
    let environment: [String: String]

    static func locate(bundle: Bundle = .main, environment: [String: String] = ProcessInfo.processInfo.environment) -> EngineCommand? {
        if let helper = bundle.url(forAuxiliaryExecutable: "raf2hncs-engine") {
            var values = environment
            if let resourceURL = bundle.resourceURL {
                values["RAF2HNCS_TOOL_DIR"] = resourceURL.appendingPathComponent("Tools/bin").path
            }
            return EngineCommand(executable: helper, prefixArguments: [], environment: values)
        }
        if let explicit = environment["RAF2HNCS_ENGINE"], !explicit.isEmpty {
            return EngineCommand(executable: URL(fileURLWithPath: explicit), prefixArguments: [], environment: environment)
        }
        if let root = environment["RAF2HNCS_REPO_ROOT"], !root.isEmpty {
            var values = environment
            values["PYTHONPATH"] = URL(fileURLWithPath: root).appendingPathComponent("src").path
            values["RAF2HNCS_TOOL_DIR"] = URL(fileURLWithPath: root).appendingPathComponent(".tools/bin").path
            return EngineCommand(
                executable: URL(fileURLWithPath: "/usr/bin/env"),
                prefixArguments: ["python3", "-m", "raf2hncs.cli"],
                environment: values
            )
        }
        return nil
    }
}

final class EngineRunner: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?

    func run(_ arguments: [String], environmentOverrides: [String: String] = [:]) async throws -> Data {
        guard let command = EngineCommand.locate() else { throw EngineError.unavailable }
        let task = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        task.executableURL = command.executable
        task.arguments = command.prefixArguments + arguments
        task.environment = command.environment.merging(environmentOverrides) { _, override in override }
        task.standardOutput = stdout
        task.standardError = stderr

        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                task.terminationHandler = { [weak self] completed in
                    let output = stdout.fileHandleForReading.readDataToEndOfFile()
                    let errorData = stderr.fileHandleForReading.readDataToEndOfFile()
                    self?.lock.withLock { self?.process = nil }
                    if completed.terminationReason == .uncaughtSignal || completed.terminationStatus == 15 {
                        continuation.resume(throwing: EngineError.cancelled)
                    } else if completed.terminationStatus != 0 {
                        let message = String(data: errorData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                        continuation.resume(throwing: EngineError.failed(message))
                    } else {
                        continuation.resume(returning: output)
                    }
                }
                do {
                    try task.run()
                    lock.withLock { process = task }
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }, onCancel: { [weak self] in self?.cancel() })
    }

    func cancel() {
        lock.withLock {
            guard let process, process.isRunning else { return }
            process.terminate()
        }
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock(); defer { unlock() }
        return try operation()
    }
}

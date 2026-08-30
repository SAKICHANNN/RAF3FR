import CryptoKit
import Foundation

enum AppDefaults {
    static func launch(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        arguments: [String] = CommandLine.arguments
    ) -> UserDefaults {
        let argumentPrefix = "--raf3fr-test-defaults-suite="
        let argumentSuite = arguments.first(where: { $0.hasPrefix(argumentPrefix) })
            .map { String($0.dropFirst(argumentPrefix.count)) }
        guard let suite = argumentSuite ?? environment["RAF3FR_TEST_DEFAULTS_SUITE"],
              suite.hasPrefix("app.raf3fr.converter.test."),
              let defaults = UserDefaults(suiteName: suite) else {
            return .standard
        }
        if !defaults.bool(forKey: "cleanInstallTestInitialized") {
            defaults.set(Data("[]".utf8), forKey: "conversionRecords")
            defaults.set(Data(), forKey: "x2dDonorBookmark")
            defaults.set("", forKey: "x2dDonorPath")
            defaults.set(false, forKey: "useExternalX2DDonor")
            defaults.set("en", forKey: "appLanguage")
            defaults.set(false, forKey: "completionNotifications")
            defaults.set(true, forKey: "cleanInstallTestInitialized")
        }
        return defaults
    }
}

enum DonorSource: String {
    case bundled
    case external
}

enum DonorSelectionPolicy {
    static func source(useExternalOverride: Bool, hasExternalDonor: Bool) -> DonorSource {
        useExternalOverride && hasExternalDonor ? .external : .bundled
    }
}

enum BundledDonorError: Error, Equatable {
    case missing
    case unreadable
    case wrongSize(Int64)
    case wrongHash(String)

    var localizationKey: String {
        switch self {
        case .missing: "bundledDonorMissing"
        case .unreadable: "bundledDonorUnreadable"
        case .wrongSize, .wrongHash: "bundledDonorCorrupt"
        }
    }
}

enum BundledDonor {
    static let resourceName = "SanitizedX2DTemplate"
    static let resourceExtension = "3FR"
    static let expectedSize: Int64 = 213_311_488
    static let expectedSHA256 = "1e7373384843a803eb986b42bf75e044142f029805db86018fa2f68b47643fd6"

    static func resolve(in bundle: Bundle = .main) throws -> URL {
        guard let url = bundle.url(forResource: resourceName, withExtension: resourceExtension) else {
            throw BundledDonorError.missing
        }
        try validate(url)
        return url
    }

    static func validate(_ url: URL) throws {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = attributes[.size] as? NSNumber else {
            throw BundledDonorError.unreadable
        }
        guard size.int64Value == expectedSize else {
            throw BundledDonorError.wrongSize(size.int64Value)
        }
        guard let handle = try? FileHandle(forReadingFrom: url) else {
            throw BundledDonorError.unreadable
        }
        defer { try? handle.close() }
        var digest = SHA256()
        do {
            while let data = try handle.read(upToCount: 1024 * 1024), !data.isEmpty {
                digest.update(data: data)
            }
        } catch {
            throw BundledDonorError.unreadable
        }
        let actual = digest.finalize().map { String(format: "%02x", $0) }.joined()
        guard actual == expectedSHA256 else {
            throw BundledDonorError.wrongHash(actual)
        }
    }
}

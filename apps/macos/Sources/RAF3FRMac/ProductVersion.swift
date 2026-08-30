import Foundation

enum ProductVersion {
    static func short(in bundle: Bundle = .main) -> String {
        guard let version = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
              !version.isEmpty else { return "DEV" }
        return "V \(version)"
    }

    static func detailed(in bundle: Bundle = .main) -> String {
        let version = short(in: bundle)
        guard let build = bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String,
              !build.isEmpty else { return version }
        return "\(version)  ·  BUILD \(build)"
    }
}

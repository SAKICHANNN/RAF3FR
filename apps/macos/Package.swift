// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "RAF3FRMac",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "RAF3FRMac", targets: ["RAF3FRMac"])],
    targets: [
        .executableTarget(name: "RAF3FRMac"),
    ]
)

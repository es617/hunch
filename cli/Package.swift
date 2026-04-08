// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "hunch",
    platforms: [.macOS(.v26)],
    targets: [
        .target(
            name: "HunchLib",
            path: "Sources/HunchLib"
        ),
        .executableTarget(
            name: "hunch",
            dependencies: ["HunchLib"],
            path: "Sources/Hunch",
            linkerSettings: [
                .linkedFramework("FoundationModels"),
            ]
        ),
        .testTarget(
            name: "HunchTests",
            dependencies: ["HunchLib"],
            path: "Tests",
            resources: [
                .copy("Fixtures/test_bank.db"),
            ]
        ),
    ]
)

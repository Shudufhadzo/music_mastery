// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "MusicMasteryMacOS",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "MusicMasteryMacOS", targets: ["MusicMasteryMacOS"]),
        .library(name: "MusicMasteryCore", targets: ["MusicMasteryCore"])
    ],
    targets: [
        .target(name: "MusicMasteryCore"),
        .executableTarget(
            name: "MusicMasteryMacOS",
            dependencies: ["MusicMasteryCore"]
        ),
        .testTarget(
            name: "MusicMasteryCoreTests",
            dependencies: ["MusicMasteryCore"]
        )
    ]
)

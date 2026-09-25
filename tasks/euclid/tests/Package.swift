// swift-tools-version:5.9
//
// Hidden grading harness for the Euclid WRG task. A separate SwiftPM package uploaded to /tests at
// grading time; it path-depends on the agent's /app implementation and links its `Euclid` library
// product. The only fixed contract is that /app exposes a library product named `Euclid` importable
// as `import Euclid`. Path-dependency package identity is the basename of the path, i.e. "app".
import PackageDescription

let package = Package(
    name: "EuclidTestHarness",
    dependencies: [
        .package(path: "/app"),
    ],
    targets: [
        .testTarget(
            name: "EuclidTests",
            dependencies: [
                .product(name: "Euclid", package: "app"),
            ],
            path: "Tests/EuclidTests"
        ),
    ]
)

// swift-tools-version:5.9
// Grader package. test.sh copies the candidate's library sources into Sources/Plot/ and one
// hidden test file into Tests/PlotTests/, then runs `swift test`. The library is a local target
// with no dependencies, so the build is fully offline.
//
// tools-version 5.9 builds under the Swift 5 language mode (lenient concurrency checking), so a
// functionally-correct candidate library compiles even on the Swift 6 toolchain in the image.
import PackageDescription

let package = Package(
    name: "PlotGrader",
    products: [
        .library(name: "Plot", targets: ["Plot"]),
    ],
    targets: [
        .target(name: "Plot", path: "Sources/Plot"),
        .testTarget(
            name: "PlotTests",
            dependencies: ["Plot"],
            path: "Tests/PlotTests"
        ),
    ]
)

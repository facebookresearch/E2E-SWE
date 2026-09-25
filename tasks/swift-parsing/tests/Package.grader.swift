// swift-tools-version:5.9
// Grader package. test.sh copies the candidate's library sources into Sources/Parsing/ and one
// or more hidden test files into Tests/ParsingTests/, then builds + runs `swift test`. The
// library is a local target with no external dependencies, so the build is fully offline.
//
// tools-version 5.9 builds under the Swift 5 language mode (lenient concurrency checking), so a
// functionally-correct candidate library compiles even on the Swift 6 toolchain in the image.
// The pinned reference (swift-parsing 0.14.1) is itself a tools-version:5.9 package.
import PackageDescription

let package = Package(
    name: "ParsingGrader",
    products: [
        .library(name: "Parsing", targets: ["Parsing"]),
    ],
    targets: [
        .target(name: "Parsing", path: "Sources/Parsing"),
        .testTarget(
            name: "ParsingTests",
            dependencies: ["Parsing"],
            path: "Tests/ParsingTests"
        ),
    ]
)

// swift-tools-version:5.9
// Grader package. test.sh copies the candidate's library sources into Sources/Splash/ and one
// hidden test file into Tests/SplashTests/, then runs `swift test`. The library is a local target
// with no dependencies, so the build is fully offline.
//
// tools-version 5.9 builds under the Swift 5 language mode (lenient concurrency checking), so a
// functionally-correct candidate library compiles even on the Swift 6 toolchain in the image.
import PackageDescription

let package = Package(
    name: "SplashGrader",
    products: [
        .library(name: "Splash", targets: ["Splash"]),
    ],
    targets: [
        .target(name: "Splash", path: "Sources/Splash"),
        .testTarget(
            name: "SplashTests",
            dependencies: ["Splash"],
            path: "Tests/SplashTests"
        ),
    ]
)

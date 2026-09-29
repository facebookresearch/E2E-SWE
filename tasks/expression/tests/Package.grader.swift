// swift-tools-version:5.7
// Grader package. test.sh copies the candidate's library sources into Sources/Expression/
// and one hidden test file into Tests/ExpressionTests/, then runs `swift test`. The library
// is a local target (no dependencies), so the build is fully offline.
import PackageDescription

let package = Package(
    name: "ExpressionGrader",
    products: [
        .library(name: "Expression", targets: ["Expression"]),
    ],
    targets: [
        .target(name: "Expression", path: "Sources/Expression"),
        .testTarget(
            name: "ExpressionTests",
            dependencies: ["Expression"],
            path: "Tests/ExpressionTests"
        ),
    ]
)

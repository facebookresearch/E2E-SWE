// swift-tools-version:6.0
// Grader package. test.sh copies the candidate's library sources into Sources/ArgumentParser/
// and one hidden test file into Tests/ArgumentParserTests/, then builds + runs `swift test`.
// The library is a local target with no external dependencies, so the build is fully offline.
//
// Swift 6 language features the reference relies on (typed throws `throws(ParserError)`,
// access-level `internal import`) must compile, so tools-version is 6.0. But grading a
// candidate's implementation under STRICT Swift 6 concurrency checking would unfairly fail
// functionally-correct code, so both targets pin the Swift 5 language mode (lenient concurrency)
// while enabling the AccessLevelOnImport feature that `internal import` needs in that mode.
// The pin only ever ADDS leniency: neither mode subsumes the other, so test.sh rebuilds with this
// manifest's `.v5` swapped for `.v6` whenever a build fails, and a candidate is only recorded as
// non-compiling when both language modes reject it.
import PackageDescription

let graderSettings: [SwiftSetting] = [
  .swiftLanguageMode(.v5),
  .enableExperimentalFeature("AccessLevelOnImport"),
]

let package = Package(
  name: "ArgumentParserGrader",
  products: [
    .library(name: "ArgumentParser", targets: ["ArgumentParser"])
  ],
  targets: [
    .target(
      name: "ArgumentParser",
      path: "Sources/ArgumentParser",
      swiftSettings: graderSettings),
    .testTarget(
      name: "ArgumentParserTests",
      dependencies: ["ArgumentParser"],
      path: "Tests/ArgumentParserTests",
      swiftSettings: graderSettings),
  ]
)

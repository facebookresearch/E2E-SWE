import ArgumentParser
import XCTest

private struct UpToNext: ParsableArguments {
  @Option(parsing: .upToNextOption) var files: [String] = []
  @Flag var verbose = false
}

final class OptUpToNextTests: XCTestCase {
  /// `.upToNextOption` greedily consumes consecutive values until the next dash-prefixed option.
  func testOptionUpToNextOptionStrategy() throws {
    let a = try UpToNext.parse(["--files", "foo", "bar"])
    XCTAssertEqual(a.files, ["foo", "bar"])
    XCTAssertEqual(a.verbose, false)
    let b = try UpToNext.parse(["--files", "foo", "bar", "--verbose"])
    XCTAssertEqual(b.files, ["foo", "bar"])
    XCTAssertEqual(b.verbose, true)
  }
}

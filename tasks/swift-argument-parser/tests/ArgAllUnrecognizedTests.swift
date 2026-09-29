import ArgumentParser
import XCTest

private struct AllUnrecognized: ParsableArguments {
  @Flag var verbose = false
  @Argument var name: String
  @Argument(parsing: .allUnrecognized) var other: [String] = []
}

final class ArgAllUnrecognizedTests: XCTestCase {
  /// `.allUnrecognized` captures any input not matched by a known flag/option or the leading
  /// positional, suppressing "unexpected argument".
  func testArgumentAllUnrecognizedStrategy() throws {
    let a = try AllUnrecognized.parse(["--verbose", "Negin", "one", "two"])
    XCTAssertEqual(a.verbose, true)
    XCTAssertEqual(a.name, "Negin")
    XCTAssertEqual(a.other, ["one", "two"])
    let b = try AllUnrecognized.parse(["Asa", "--verbose", "--other", "-zzz"])
    XCTAssertEqual(b.name, "Asa")
    XCTAssertEqual(b.verbose, true)
    XCTAssertEqual(b.other, ["--other", "-zzz"])
  }
}

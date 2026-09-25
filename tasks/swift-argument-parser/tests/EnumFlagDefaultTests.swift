import ArgumentParser
import XCTest

private enum Output: String, EnumerableFlag {
  case stats, count, list
}

private struct WithDefaultEnumFlag: ParsableArguments {
  @Flag var output: Output = .list
}

final class EnumFlagDefaultTests: XCTestCase {
  /// An `EnumerableFlag` enum exposes each case as a flag; the property takes the selected case,
  /// or its declared default when omitted.
  func testEnumerableFlagWithDefault() throws {
    XCTAssertEqual(try WithDefaultEnumFlag.parse([]).output, .list)
    XCTAssertEqual(try WithDefaultEnumFlag.parse(["--stats"]).output, .stats)
    XCTAssertEqual(try WithDefaultEnumFlag.parse(["--count"]).output, .count)
  }
}

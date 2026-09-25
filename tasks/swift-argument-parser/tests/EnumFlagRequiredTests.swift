import ArgumentParser
import XCTest

private enum Mode: String, EnumerableFlag {
  case fast, slow
}

private struct WithRequiredEnumFlag: ParsableArguments {
  @Flag var mode: Mode
}

final class EnumFlagRequiredTests: XCTestCase {
  /// A required `EnumerableFlag` (no default) must be supplied via one of its case flags.
  func testEnumerableFlagRequired() throws {
    XCTAssertEqual(try WithRequiredEnumFlag.parse(["--fast"]).mode, .fast)
    XCTAssertEqual(try WithRequiredEnumFlag.parse(["--slow"]).mode, .slow)
    XCTAssertThrowsError(try WithRequiredEnumFlag.parse([]))
  }
}

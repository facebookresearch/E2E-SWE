import ArgumentParser
import XCTest

private struct Exclusive: ParsableArguments {
  @Flag(inversion: .prefixedNo, exclusivity: .exclusive) var force: Bool = false
}

final class ExclusiveFlagTests: XCTestCase {
  /// `.exclusive` makes a flag/inverse conflict an error instead of last-wins.
  func testExclusiveInversionConflicts() throws {
    XCTAssertEqual(try Exclusive.parse(["--force"]).force, true)
    XCTAssertEqual(try Exclusive.parse(["--no-force"]).force, false)
    XCTAssertThrowsError(try Exclusive.parse(["--force", "--no-force"]))
  }
}

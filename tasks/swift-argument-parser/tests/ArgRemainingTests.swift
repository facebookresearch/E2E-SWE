import ArgumentParser
import XCTest

private struct RemainingArgs: ParsableArguments {
  @Argument var items: [String] = []
}

final class ArgRemainingTests: XCTestCase {
  /// A positional array uses the default `.remaining` strategy; input after `--` is positional.
  func testArgumentRemainingStrategy() throws {
    XCTAssertEqual(try RemainingArgs.parse(["one", "two", "three"]).items, ["one", "two", "three"])
    XCTAssertEqual(
      try RemainingArgs.parse(["one", "two", "--", "--verbose", "--other"]).items,
      ["one", "two", "--verbose", "--other"])
  }
}

import ArgumentParser
import XCTest

private struct Counted: ParsableArguments {
  @Flag(name: .shortAndLong) var verbose: Int
}

final class CountedFlagTests: XCTestCase {
  /// An `Int`-typed flag counts occurrences: `-vvv` and `-v -v -v` both give 3.
  func testFlagCounting() throws {
    XCTAssertEqual(try Counted.parse([]).verbose, 0)
    XCTAssertEqual(try Counted.parse(["-v"]).verbose, 1)
    XCTAssertEqual(try Counted.parse(["-vvv"]).verbose, 3)
    XCTAssertEqual(try Counted.parse(["-v", "-v", "-v"]).verbose, 3)
    XCTAssertEqual(try Counted.parse(["--verbose", "--verbose"]).verbose, 2)
  }
}

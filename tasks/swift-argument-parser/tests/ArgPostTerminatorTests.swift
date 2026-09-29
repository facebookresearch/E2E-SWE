import ArgumentParser
import XCTest

private struct PostTerminator: ParsableArguments {
  @Flag var verbose = false
  @Argument var name = ""
  @Argument(parsing: .postTerminator) var words: [String] = []
}

final class ArgPostTerminatorTests: XCTestCase {
  /// `.postTerminator` captures only inputs after `--`; a stray positional before `--` is still
  /// an unexpected-argument error.
  func testArgumentPostTerminatorStrategy() throws {
    let a = try PostTerminator.parse(["--verbose", "Asa", "--", "one", "two", "--other"])
    XCTAssertEqual(a.verbose, true)
    XCTAssertEqual(a.name, "Asa")
    XCTAssertEqual(a.words, ["one", "two", "--other"])
    XCTAssertThrowsError(try PostTerminator.parse(["Asa", "Extra", "--", "one", "two"]))
  }
}

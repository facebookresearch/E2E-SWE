import ArgumentParser
import XCTest

private struct WithTerminator: ParsableArguments {
  @Option var name: String
  @Argument var items: [String] = []
}

final class TerminatorTests: XCTestCase {
  /// The `--` terminator forces every following token to be a positional value, even
  /// option-looking ones.
  func testTerminatorForcesPositional() throws {
    let r = try WithTerminator.parse(["--name", "n", "--", "--not-an-option", "-x", "plain"])
    XCTAssertEqual(r.name, "n")
    XCTAssertEqual(r.items, ["--not-an-option", "-x", "plain"])
  }
}

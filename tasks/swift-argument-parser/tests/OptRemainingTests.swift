import ArgumentParser
import XCTest

private struct Passthrough: ParsableArguments {
  @Option(parsing: .remaining) var passthrough: [String] = []
}

final class OptRemainingTests: XCTestCase {
  /// `.remaining` captures every input after the option unparsed (pass-through).
  func testOptionRemainingStrategy() throws {
    let a = try Passthrough.parse(["--passthrough", "--foo", "1", "--bar", "2", "-xvf"])
    XCTAssertEqual(a.passthrough, ["--foo", "1", "--bar", "2", "-xvf"])
  }
}

import ArgumentParser
import XCTest

private struct Joined: ParsableArguments {
  @Option(name: [.customShort("n", allowingJoined: true), .long]) var name: String
  @Option(name: [.customShort("v", allowingJoined: true), .long]) var value: Int
}

final class JoinedTests: XCTestCase {
  /// Alternative value-attachment syntaxes: `--long=value`, `-n value` (spaced short), and
  /// `-nvalue` (joined short, via `allowingJoined`), all equivalent to the spaced long form.
  func testEqualsAndJoinedSyntax() throws {
    let eq = try Joined.parse(["--name=Bar", "--value=10"])
    XCTAssertEqual(eq.name, "Bar")
    XCTAssertEqual(eq.value, 10)

    let joinedShort = try Joined.parse(["-nBar", "-v10"])
    XCTAssertEqual(joinedShort.name, "Bar")
    XCTAssertEqual(joinedShort.value, 10)

    let spaced = try Joined.parse(["-n", "Bar", "-v", "10"])
    XCTAssertEqual(spaced.name, "Bar")
    XCTAssertEqual(spaced.value, 10)
  }
}

import ArgumentParser
import XCTest

private enum Format: String, ExpressibleByArgument, CaseIterable {
  case text, json, csv
}

private struct Coordinate: ExpressibleByArgument, Equatable {
  var x: Int
  var y: Int
  init?(argument: String) {
    let parts = argument.split(separator: ",")
    guard parts.count == 2, let x = Int(parts[0]), let y = Int(parts[1]) else { return nil }
    self.x = x
    self.y = y
  }
}

private struct WithCustomTypes: ParsableArguments {
  @Option var format: Format
  @Option var origin: Coordinate
}

final class ExpressibleByArgTests: XCTestCase {
  /// A raw-value enum and a custom `ExpressibleByArgument` type parse via `init?(argument:)`;
  /// an unparseable value throws.
  func testExpressibleByArgument() throws {
    let ok = try WithCustomTypes.parse(["--format", "json", "--origin", "3,4"])
    XCTAssertEqual(ok.format, .json)
    XCTAssertEqual(ok.origin, Coordinate(argument: "3,4"))
    XCTAssertEqual(ok.origin.x, 3)
    XCTAssertEqual(ok.origin.y, 4)
    XCTAssertThrowsError(try WithCustomTypes.parse(["--format", "png", "--origin", "3,4"]))
    XCTAssertThrowsError(try WithCustomTypes.parse(["--format", "json", "--origin", "nope"]))
  }
}

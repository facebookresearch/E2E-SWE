import ArgumentParser
import XCTest

private struct Defaults: ParsableArguments {
  @Option var host: String = "localhost"
  @Option var port: Int = 8080
  @Option var label: String?
  @Flag var force: Bool = false
  @Argument var extras: [String] = []
}

final class DefaultsTests: XCTestCase {
  /// With no arguments every property takes its declared default (optionals nil, arrays empty);
  /// supplying values overrides each default.
  func testOptionalsAndDefaults() throws {
    let empty = try Defaults.parse([])
    XCTAssertEqual(empty.host, "localhost")
    XCTAssertEqual(empty.port, 8080)
    XCTAssertNil(empty.label)
    XCTAssertEqual(empty.force, false)
    XCTAssertEqual(empty.extras, [])

    let full = try Defaults.parse([
      "--host", "example.com", "--port", "443", "--label", "prod", "--force", "a", "b",
    ])
    XCTAssertEqual(full.host, "example.com")
    XCTAssertEqual(full.port, 443)
    XCTAssertEqual(full.label, "prod")
    XCTAssertEqual(full.force, true)
    XCTAssertEqual(full.extras, ["a", "b"])
  }
}

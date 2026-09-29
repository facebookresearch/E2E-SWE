import ArgumentParser
import XCTest

private struct Connection: ParsableArguments {
  @Option var host: String = "localhost"
  @Option var port: Int = 80
}

private struct Composed: ParsableArguments {
  @OptionGroup var connection: Connection
  @Flag var verbose = false
  @Argument var path: String
}

final class OptionGroupTests: XCTestCase {
  /// `@OptionGroup` merges another type's properties in so they parse as if declared inline.
  func testOptionGroupComposition() throws {
    let a = try Composed.parse(["--host", "example.com", "--port", "443", "--verbose", "/tmp"])
    XCTAssertEqual(a.connection.host, "example.com")
    XCTAssertEqual(a.connection.port, 443)
    XCTAssertEqual(a.verbose, true)
    XCTAssertEqual(a.path, "/tmp")

    let defaults = try Composed.parse(["/only-path"])
    XCTAssertEqual(defaults.connection.host, "localhost")
    XCTAssertEqual(defaults.connection.port, 80)
    XCTAssertEqual(defaults.verbose, false)
    XCTAssertEqual(defaults.path, "/only-path")
  }
}

import ArgumentParser
import XCTest

private struct SingleValueArray: ParsableArguments {
  @Option(parsing: .singleValue) var read: [String] = []
  @Option var name: String?
}

final class OptSingleValueTests: XCTestCase {
  /// `.singleValue` parses one value per option occurrence, joining repeats and distinguishing
  /// values from options.
  func testOptionSingleValueStrategy() throws {
    XCTAssertEqual(try SingleValueArray.parse(["--read", "foo", "--read", "bar"]).read, ["foo", "bar"])
    XCTAssertEqual(try SingleValueArray.parse(["--read=foo", "--read=bar"]).read, ["foo", "bar"])
    let c = try SingleValueArray.parse(["--read", "foo", "--name", "Foo"])
    XCTAssertEqual(c.read, ["foo"])
    XCTAssertEqual(c.name, "Foo")
    XCTAssertEqual(try SingleValueArray.parse([]).read, [])
    XCTAssertThrowsError(try SingleValueArray.parse(["--read"]))
  }
}

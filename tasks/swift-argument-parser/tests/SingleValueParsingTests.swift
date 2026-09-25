import ArgumentParser
import XCTest

private struct SingleValues: ParsableArguments {
  @Option var name: String
  @Option var count: Int
  @Argument var phrase: String
}

final class SingleValueParsingTests: XCTestCase {
  /// Two options plus a positional argument parse from a valid invocation; the parser rejects
  /// the full range of malformed inputs (missing option, missing value, wrong type, extras).
  func testSingleValueOptionsAndArgument() throws {
    let parsed = try SingleValues.parse(["--name", "Bar", "--count", "42", "hello"])
    XCTAssertEqual(parsed.name, "Bar")
    XCTAssertEqual(parsed.count, 42)
    XCTAssertEqual(parsed.phrase, "hello")

    let spaced = try SingleValues.parse(["--name", " foo ", "--count", "1", "x"])
    XCTAssertEqual(spaced.name, " foo ")

    XCTAssertThrowsError(try SingleValues.parse([]))
    XCTAssertThrowsError(try SingleValues.parse(["--name", "Bar", "hello"]))
    XCTAssertThrowsError(try SingleValues.parse(["--name", "--count", "42", "hello"]))
    XCTAssertThrowsError(try SingleValues.parse(["--name", "Bar", "--count", "a", "hello"]))
    XCTAssertThrowsError(try SingleValues.parse(["--name", "Bar", "--count", "42", "hello", "extra"]))
    XCTAssertThrowsError(try SingleValues.parse(["--name", "Bar", "--count", "42", "hello", "--x"]))
  }
}

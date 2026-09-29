import ArgumentParser
import XCTest

private func assertMessage<T: ParsableArguments>(
  _ type: T.Type, _ args: [String], _ expected: String,
  file: StaticString = #filePath, line: UInt = #line
) {
  do {
    _ = try type.parse(args)
    XCTFail("Parsing should have failed.", file: file, line: line)
  } catch {
    XCTAssertEqual(type.message(for: error), expected, file: file, line: line)
  }
}

private struct Bar: ParsableArguments {
  @Option() var name: String
  @Option(name: [.short, .long]) var format: String
}

final class ErrorBasicTests: XCTestCase {
  /// Precise diagnostics for the common failure modes: missing required option, unknown option,
  /// missing value, and one or more unexpected arguments.
  func testBasicErrorMessages() {
    assertMessage(Bar.self, [], "Missing expected argument '--name <name>'")
    assertMessage(Bar.self, ["--name", "a"], "Missing expected argument '--format <format>'")
    assertMessage(Bar.self, ["--name", "a", "--format", "b", "--verbose"], "Unknown option '--verbose'")
    assertMessage(Bar.self, ["--name", "a", "--format"], "Missing value for '--format <format>'")
    assertMessage(Bar.self, ["--name", "a", "--format", "f", "b"], "Unexpected argument 'b'")
    assertMessage(Bar.self, ["--name", "a", "--format", "f", "b", "baz"], "2 unexpected arguments: 'b', 'baz'")
  }
}

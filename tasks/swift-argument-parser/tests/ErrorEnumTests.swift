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

private enum Format: String, Equatable, ExpressibleByArgument, CaseIterable {
  case text, json, csv
}

private enum Name: String, Equatable, ExpressibleByArgument, CaseIterable {
  case bruce, clint, hulk, natasha, steve, thor, tony
}

private struct Foo: ParsableArguments {
  @Option(name: [.short, .long]) var format: Format
  @Option(name: [.short, .long]) var name: Name?
}

final class ErrorEnumTests: XCTestCase {
  /// An invalid enum value lists valid values inline ("one of ...") for few cases and as a
  /// bulleted list for many.
  func testInvalidEnumValueMessages() {
    assertMessage(
      Foo.self, ["--format", "png"],
      "The value 'png' is invalid for '--format <format>'. Please provide one of 'text', 'json' or 'csv'.")
    assertMessage(
      Foo.self, ["-f", "text", "--name", "loki"],
      """
      The value 'loki' is invalid for '--name <name>'. Please provide one of the following:
        - bruce
        - clint
        - hulk
        - natasha
        - steve
        - thor
        - tony
      """)
  }
}

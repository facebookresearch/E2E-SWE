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

private struct DupOptions: ParsableArguments {
  enum OutputBehaviour: String, EnumerableFlag {
    case stats, count, list
    static func name(for value: OutputBehaviour) -> NameSpecification { .shortAndLong }
  }
  @Flag(help: "Program output") var behaviour: OutputBehaviour = .list
  @Flag(inversion: .prefixedNo, exclusivity: .exclusive) var bool: Bool
}

final class ErrorDuplicateTests: XCTestCase {
  /// Mutually-exclusive flags report a conflict naming both the offending flag and the one that
  /// already set the value.
  func testDuplicateFlagMessages() {
    assertMessage(
      DupOptions.self, ["--list", "--bool", "-s"],
      "Value to be set with flag '-s' had already been set with flag '--list'")
    assertMessage(
      DupOptions.self, ["--no-bool", "--bool"],
      "Value to be set with flag '--bool' had already been set with flag '--no-bool'")
  }
}

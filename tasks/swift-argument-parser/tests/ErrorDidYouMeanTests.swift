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

private struct Qwz: ParsableArguments {
  @Option() var name: String?
  @Option(name: [.customLong("title", withSingleDash: true)]) var title: String?
}

final class ErrorDidYouMeanTests: XCTestCase {
  /// An unknown option close (by edit distance) to a known one appends a suggestion matching the
  /// token's dash style; a distant token gets none.
  func testDidYouMeanSuggestions() {
    assertMessage(Qwz.self, ["--nme"], "Unknown option '--nme'. Did you mean '--name'?")
    assertMessage(Qwz.self, ["-ttle"], "Unknown option '-ttle'. Did you mean '-title'?")
    assertMessage(Qwz.self, ["--not-similar"], "Unknown option '--not-similar'")
  }
}

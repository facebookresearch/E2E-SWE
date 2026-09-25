import ArgumentParser
import XCTest

private struct Issue27: ParsableArguments {
  @Option var two: String = "42"
  @Option(help: "The third option") var three: String
  @Option(help: "A fourth option") var four: String?
  @Option(help: "A fifth option") var five: String = ""
}

final class HelpDefaultsTests: XCTestCase {
  /// Options with default values but no help show "(default: ...)"; options with help show it.
  func testHelpWithDefaults() {
    XCTAssertEqual(
      Issue27.helpMessage(includeHidden: false, columns: 80),
      """
      USAGE: issue27 [--two <two>] --three <three> [--four <four>] [--five <five>]

      OPTIONS:
        --two <two>             (default: 42)
        --three <three>         The third option
        --four <four>           A fourth option
        --five <five>           A fifth option
        -h, --help              Show help information.

      """)
  }
}

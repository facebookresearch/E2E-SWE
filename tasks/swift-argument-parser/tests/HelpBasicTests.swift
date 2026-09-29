import ArgumentParser
import XCTest

private struct A: ParsableArguments {
  @Option(help: "Your name") var name: String
  @Option(help: "Your title") var title: String?
}

final class HelpBasicTests: XCTestCase {
  /// The help screen lays out USAGE and OPTIONS, bracketing optional entries, aligning
  /// descriptions, and appending the built-in help entry.
  func testHelpBasic() {
    XCTAssertEqual(
      A.helpMessage(includeHidden: false, columns: 80),
      """
      USAGE: a --name <name> [--title <title>]

      OPTIONS:
        --name <name>           Your name
        --title <title>         Your title
        -h, --help              Show help information.

      """)
  }
}

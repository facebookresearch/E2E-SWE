import ArgumentParser
import XCTest

private struct C: ParsableArguments {
  @Option(help: ArgumentHelp("Your name.", discussion: "Your name is used to greet you and say hello."))
  var name: String
}

final class HelpDiscussionTests: XCTestCase {
  /// A help entry with a discussion renders the abstract on the entry line and the discussion as
  /// an indented paragraph beneath it.
  func testHelpWithDiscussion() {
    XCTAssertEqual(
      C.helpMessage(includeHidden: false, columns: 80),
      """
      USAGE: c --name <name>

      OPTIONS:
        --name <name>           Your name.
              Your name is used to greet you and say hello.
        -h, --help              Show help information.

      """)
  }
}

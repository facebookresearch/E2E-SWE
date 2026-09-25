import Parsing
import XCTest

private struct WhoopsError: LocalizedError {
  var errorDescription: String? { "whoops!" }
}

private struct ThrowingParser: Parser {
  func parse(_ input: inout Substring) throws {
    throw WhoopsError()
  }
}

final class NotPipeCustomErrorTests: XCTestCase {
  // `Not` renders a range caret with its own label; `pipe` reports the sub-input it could not
  // fully consume; and a thrown non-library error is wrapped with position information.
  func testNotPipeAndCustomError() {
    var comment = """
      // a comment
      let foo = true
      """[...]
    let uncommentedLine = Parse(input: Substring.self) {
      Not { "//" }
      Prefix { $0 != "\n" }
    }
    XCTAssertThrowsError(try uncommentedLine.parse(&comment)) { error in
      XCTAssertEqual(
        """
        error: unexpected input
         --> input:1:1-2
        1 | // a comment
          | ^^ expected not to be processed
        """,
        "\(error)"
      )
    }

    var piped = "true Hello, world!"[...].utf8
    XCTAssertThrowsError(try Prefix(10).pipe { Bool.parser() }.parse(&piped)) { error in
      XCTAssertEqual(
        """
        error: unexpected input
         --> input:1:5-10
        1 | true Hello, world!
          |     ^^^^^^ expected end of pipe
        """,
        "\(error)"
      )
    }

    var custom = "123 Blob"[...]
    XCTAssertThrowsError(
      try Parse(input: Substring.self) {
        Int.parser()
        ThrowingParser()
      }
      .parse(&custom)
    ) { error in
      XCTAssertEqual(
        """
        error: whoops!
         --> input:1:4
        1 | 123 Blob
          |    ^
        """,
        "\(error)"
      )
    }
  }
}

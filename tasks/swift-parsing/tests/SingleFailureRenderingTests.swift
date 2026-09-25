import Parsing
import XCTest

final class SingleFailureRenderingTests: XCTestCase {
  // A single failure points at the exact line/column with a caret and an "expected ..." label;
  // trailing whitespace on the source line renders as ␣.
  func testSingleFailureLocationAndCaret() {
    XCTAssertThrowsError(try Int.parser().parse("Hello")) { error in
      XCTAssertEqual(
        """
        error: unexpected input
         --> input:1:1
        1 | Hello
          | ^ expected integer
        """,
        "\(error)"
      )
    }

    XCTAssertThrowsError(try Int.parser().parse("123   ")) { error in
      XCTAssertEqual(
        """
        error: unexpected input
         --> input:1:4
        1 | 123␣␣␣
          |    ^ expected end of input
        """,
        "\(error)"
      )
    }

    var input = "Hello, world!"[...]
    XCTAssertThrowsError(try End().parse(&input)) { error in
      XCTAssertEqual(
        """
        error: unexpected input
         --> input:1:1
        1 | Hello, world!
          | ^ expected end of input
        """,
        "\(error)"
      )
    }
  }
}

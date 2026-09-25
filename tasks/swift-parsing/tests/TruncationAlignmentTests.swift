import Parsing
import XCTest

final class TruncationAlignmentTests: XCTestCase {
  // Long source lines are windowed around the failure and truncated with … markers; multi-digit
  // line numbers keep the gutter aligned.
  func testTruncationAndLineAlignment() {
    XCTAssertThrowsError(
      try Many(101...) { "hello" }.parse(
        String(repeating: "hello", count: 100) + "world"
      )
    ) { error in
      XCTAssertEqual(
        """
        error: unexpected input
         --> input:1:501
        1 | …hellohellohellohelloworld
          |                      ^ expected 1 more value of "()"
        """,
        "\(error)"
      )
    }

    let parser = Many(101...) {
      "Hello"
    } separator: {
      "\n"
    }
    XCTAssertThrowsError(
      try parser.parse(String(repeating: "Hello\n", count: 100) + "World")
    ) { error in
      XCTAssertEqual(
        """
        error: unexpected input
           --> input:100:6
        100 | Hello
            |      ^ expected 1 more value of "()"
        """,
        "\(error)"
      )
    }
  }
}

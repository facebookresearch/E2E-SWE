import Parsing
import XCTest

final class MultipleFailureRenderingTests: XCTestCase {
  // Alternatives failing at the same position are grouped under stacked carets; alternatives
  // failing at different positions are ranked (furthest progress first) under a "multiple failures
  // occurred" banner.
  func testGroupedAndRankedFailures() {
    var grouped = "London, Hello!"[...]
    XCTAssertThrowsError(
      try OneOf {
        "New York"
        "Berlin"
      }
      .parse(&grouped)
    ) { error in
      XCTAssertEqual(
        """
        error: unexpected input
         --> input:1:1
        1 | London, Hello!
          | ^ expected "New York"
          | ^ expected "Berlin"
        """,
        "\(error)"
      )
    }

    var ranked = "Berkeley, Hello!"[...]
    XCTAssertThrowsError(
      try OneOf {
        Parse {
          "New "
          "York"
        }
        Parse {
          "Ber"
          "lin"
        }
      }
      .parse(&ranked)
    ) { error in
      XCTAssertEqual(
        """
        error: multiple failures occurred

        error: unexpected input
         --> input:1:4
        1 | Berkeley, Hello!
          |    ^ expected "lin"

        error: unexpected input
         --> input:1:1
        1 | Berkeley, Hello!
          | ^ expected "New "
        """,
        "\(error)"
      )
    }
  }
}

import Parsing
import XCTest

final class ManyPrintTests: XCTestCase {
  // `Many` prints a collection by decumulating in reverse, interleaving separators; bounds are
  // enforced when printing (too few values fails).
  func testManyPrintRoundTrip() throws {
    let ints = ParsePrint(input: Substring.self) {
      Many { Int.parser() } separator: { "," }
    }
    XCTAssertEqual(try ints.print([1, 2, 3]), "1,2,3")

    let sixOrMore = ParsePrint(input: Substring.self) {
      Many(6...) { Int.parser() } separator: { "," }
    }
    XCTAssertThrowsError(try sixOrMore.print([1, 2, 3, 4, 5])) { error in
      XCTAssertEqual(
        """
        error: round-trip expectation failed

        A "Many" parser that requires at least 6 values of Int was given only 5 values to print.
        """,
        "\(error)"
      )
    }
  }
}

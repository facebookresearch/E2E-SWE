import Parsing
import XCTest

final class DigitsTests: XCTestCase {
  // Digits parses a fixed count of ASCII digits into an Int and, as a printer, zero-pads to the
  // width and refuses to print a value with more digits than allowed. Printing is exercised through
  // a `Substring` parser-printer (as it is normally used).
  func testDigits() throws {
    var d = "201801"[...].utf8
    XCTAssertEqual(2018, try Digits(4).parse(&d))
    XCTAssertEqual("01", String(d))

    let twoDigits = ParsePrint(input: Substring.self) { Digits(2) }
    XCTAssertEqual(try twoDigits.print(1), "01")

    XCTAssertThrowsError(try twoDigits.print(255)) { error in
      XCTAssertEqual(
        """
        error: round-trip expectation failed

        A "Digits" parser configured to parse at most 2 digits tried to print 255 (3 digits).
        """,
        "\(error)"
      )
    }
  }
}

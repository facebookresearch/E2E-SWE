import Parsing
import XCTest

final class PrinterRoundTripErrorsTests: XCTestCase {
  // Printers report round-trip violations: `End` refuses to print when input remains, `Rest`
  // refuses to print an empty value.
  func testPrinterRoundTripErrors() {
    var input = "Hello, world!"[...]
    XCTAssertThrowsError(try End().print(into: &input)) { error in
      XCTAssertEqual(
        """
        error: round-trip expectation failed

        An "End" parser-printer expected no more input, but more was printed.

        "Hello, world!"

        During a round-trip, the "End" parser-printer would have failed to parse at this \
        remaining input.
        """,
        "\(error)"
      )
    }

    XCTAssertThrowsError(try Rest().print(""[...])) { error in
      XCTAssertEqual(
        """
        error: round-trip expectation failed

        A "Rest" parser-printer attempted to print an empty Substring.

        During a round-trip, the "Rest" parser-printer would have failed to parse an empty input.
        """,
        "\(error)"
      )
    }
  }
}

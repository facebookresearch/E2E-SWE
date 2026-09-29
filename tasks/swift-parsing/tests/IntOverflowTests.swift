import Parsing
import XCTest

final class IntOverflowTests: XCTestCase {
  // Overflowing a fixed-width type is a diagnosed failure naming the type and the overflowed bound.
  func testIntOverflowError() {
    var input = "1234 Hello"[...].utf8
    XCTAssertThrowsError(try UInt8.parser(of: Substring.UTF8View.self).parse(&input)) { error in
      XCTAssertEqual(
        """
        error: failed to process "UInt8"
         --> input:1:1-4
        1 | 1234 Hello
          | ^^^^ overflowed 255
        """,
        "\(error)"
      )
    }
    XCTAssertEqual(" Hello", String(input))
  }
}

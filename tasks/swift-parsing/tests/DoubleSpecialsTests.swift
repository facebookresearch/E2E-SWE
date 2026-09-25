import Parsing
import XCTest

final class DoubleSpecialsTests: XCTestCase {
  // Case-insensitive infinity/nan, plus underflow-to-zero and overflow-to-infinity of the exponent.
  func testDoubleSpecialValues() throws {
    let parser = Double.parser(of: Substring.UTF8View.self)

    var input = "inf x"[...].utf8
    XCTAssertEqual(.infinity, try parser.parse(&input))

    input = "-iNfInItY x"[...].utf8
    XCTAssertEqual(-.infinity, try parser.parse(&input))

    input = "nan x"[...].utf8
    XCTAssert(try parser.parse(&input).isNaN)

    input = "1.23e-9999 x"[...].utf8
    XCTAssertEqual(0, try parser.parse(&input))

    input = "1.23e17802 x"[...].utf8
    XCTAssertEqual(.infinity, try parser.parse(&input))
  }
}

import Parsing
import XCTest

final class DoubleFormatsTests: XCTestCase {
  // Doubles accept plain decimals, a trailing dot, scientific exponents (with optional sign), hex
  // floats, and a leading-dot fraction; a bare trailing `E` is not consumed.
  func testDoubleFormats() throws {
    let parser = Double.parser(of: Substring.UTF8View.self)

    var input = "123.123 x"[...].utf8
    XCTAssertEqual(123.123, try parser.parse(&input))
    XCTAssertEqual(" x", String(input))

    input = "123. x"[...].utf8
    XCTAssertEqual(123, try parser.parse(&input))
    XCTAssertEqual(" x", String(input))

    input = "123.123E-2 x"[...].utf8
    XCTAssertEqual(123.123E-2, try parser.parse(&input))

    input = "123.123E+2 x"[...].utf8
    XCTAssertEqual(123.123E+2, try parser.parse(&input))

    input = "123E x"[...].utf8
    XCTAssertEqual(123, try parser.parse(&input))
    XCTAssertEqual("E x", String(input))

    input = "0x1c.6 x"[...].utf8
    XCTAssertEqual(28.375, try parser.parse(&input))

    input = "-.123 x"[...].utf8
    XCTAssertEqual(-0.123, try parser.parse(&input))
  }
}

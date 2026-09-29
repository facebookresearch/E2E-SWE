import Parsing
import XCTest

final class IntParserTests: XCTestCase {
  // Integers parse an optional +/- sign then digits; `radix` selects the base; Int.max/Int.min
  // parse exactly.
  func testIntSignsBoundsAndRadix() throws {
    let parser = Int.parser(of: Substring.UTF8View.self)

    var input = "123 Hello"[...].utf8
    XCTAssertEqual(123, try parser.parse(&input))
    XCTAssertEqual(" Hello", String(input))

    input = "-123 x"[...].utf8
    XCTAssertEqual(-123, try parser.parse(&input))

    input = "+123 x"[...].utf8
    XCTAssertEqual(123, try parser.parse(&input))

    input = "\(Int.max)"[...].utf8
    XCTAssertEqual(Int.max, try parser.parse(&input))

    input = "\(Int.min)"[...].utf8
    XCTAssertEqual(Int.min, try parser.parse(&input))

    let hex = Int.parser(of: Substring.UTF8View.self, radix: 16)
    var h = "ff!"[...].utf8
    XCTAssertEqual(255, try hex.parse(&h))
    XCTAssertEqual("!", String(h))
  }
}

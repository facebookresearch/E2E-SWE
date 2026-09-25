import Parsing
import XCTest

final class BoolTests: XCTestCase {
  // Bool parses and prints the literals `true` / `false`.
  func testBool() throws {
    var b = "true x"[...].utf8
    XCTAssertEqual(true, try Bool.parser().parse(&b))
    XCTAssertEqual(" x", Substring(b))

    b = "false x"[...].utf8
    XCTAssertEqual(false, try Bool.parser().parse(&b))

    var out = "!"[...]
    XCTAssertNoThrow(try Bool.parser().print(true, into: &out.utf8))
    XCTAssertEqual(out, "true!")
  }
}

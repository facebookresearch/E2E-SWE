import Parsing
import XCTest

final class NestedParsePrintTests: XCTestCase {
  // Nested parser-printers flatten their tuples per level, so a printer built from two 2-tuple
  // printers plus a middle one prints the reversed, correctly-destructured output.
  func testNestedParsePrintLayouts() throws {
    let p1 = ParsePrint(input: Substring.self) {
      Digits()
      ","
      Digits()
    }
    let p2 = ParsePrint(input: Substring.self) {
      Digits()
      ","
      Digits()
    }
    let p3 = ParsePrint(input: Substring.self) {
      p1
      ","
      p2
    }
    var input = ""[...]
    try p3.print((1, 2, (3, 4)), into: &input)
    XCTAssertEqual(input, "1,2,3,4")
  }
}

import Parsing
import XCTest

final class ManyBoundsTests: XCTestCase {
  // `Many` runs an element parser repeatedly with a separator; a terminator proves full
  // consumption; a maximum stops early; a minimum that isn't met fails.
  func testManySeparatorTerminatorBounds() throws {
    let ints = Parse(input: Substring.self) {
      Many { Int.parser() } separator: { "," } terminator: { End() }
    }
    var input = "1,2,3"[...]
    XCTAssertEqual([1, 2, 3], try ints.parse(&input))
    XCTAssertEqual("", input)

    let atMostThree = Parse(input: Substring.self) {
      Many(...3) { Int.parser() } separator: { "," }
    }
    var input2 = "1,2,3,4,5"[...]
    XCTAssertEqual([1, 2, 3], try atMostThree.parse(&input2))
    XCTAssertEqual(",4,5", input2)

    let sixOrMore = Parse(input: Substring.self) {
      Many(6...) { Int.parser() } separator: { "," }
    }
    var input3 = "1,2,3"[...]
    XCTAssertThrowsError(try sixOrMore.parse(&input3))
  }
}

import Parsing
import XCTest

final class TransformOperatorsTests: XCTestCase {
  // `map` transforms output; `compactMap` transforms and fails on `nil`; `filter` fails when the
  // predicate is not satisfied.
  func testMapCompactMapFilter() throws {
    let doubled = Parse(input: Substring.self) { Int.parser() }.map { $0 * 2 }
    XCTAssertEqual(try doubled.parse("21"), 42)

    let evens = Parse(input: Substring.self) { Int.parser() }
      .compactMap { $0.isMultiple(of: 2) ? $0 : Int?.none }
    XCTAssertEqual(try evens.parse("8"), 8)
    XCTAssertThrowsError(try evens.parse("7"))

    let positive = Parse(input: Substring.self) { Int.parser() }.filter { $0 > 0 }
    XCTAssertEqual(try positive.parse("5"), 5)
    XCTAssertThrowsError(try positive.parse("-5"))
  }
}

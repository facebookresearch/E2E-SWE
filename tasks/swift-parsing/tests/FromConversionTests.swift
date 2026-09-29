import Parsing
import XCTest

final class FromConversionTests: XCTestCase {
  // `From(.substring)` enters the grapheme-aware Substring domain from a UTF-8 parser, so a
  // literal matches across different Unicode normalizations of the same character.
  func testFromSubstringConversion() throws {
    let parser = Parse(input: Substring.UTF8View.self) {
      "caf".utf8
      From(.substring) { "é" }
    }

    var precomposed = "caf\u{00E9}"[...].utf8
    XCTAssertNoThrow(try parser.parse(&precomposed))
    XCTAssert(precomposed.isEmpty)

    var decomposed = "cafe\u{0301}"[...].utf8
    XCTAssertNoThrow(try parser.parse(&decomposed))
    XCTAssert(decomposed.isEmpty)
  }
}

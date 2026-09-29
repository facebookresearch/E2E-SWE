import Foundation
import Parsing
import XCTest

final class CharacterSetTests: XCTestCase {
  // `CharacterSet` is a parser over `Substring`: it consumes the leading run of members and never
  // fails (may return an empty match).
  func testCharacterSetParsing() throws {
    var alnum = "42abc;."[...]
    XCTAssertEqual("42abc", try CharacterSet.alphanumerics.parse(&alnum))
    XCTAssertEqual(";.", alnum)

    var custom = "23456789"[...]
    XCTAssertEqual("23", try CharacterSet(charactersIn: "0123").parse(&custom))
    XCTAssertEqual("456789", custom)
  }
}

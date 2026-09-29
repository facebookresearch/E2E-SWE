import Parsing
import XCTest

final class StringEnumTests: XCTestCase {
  // String raw values: the longer raw value ("Blob Jr") is attempted before the shorter prefix
  // ("Blob"), so both orders parse correctly; an unknown value fails.
  func testStringRawValueEnum() throws {
    enum Person: String, CaseIterable {
      case blob = "Blob"
      case blobJr = "Blob Jr"
    }

    let people = Parse(input: Substring.UTF8View.self) {
      Many {
        Person.parser()
      } separator: {
        ",".utf8
      } terminator: {
        End()
      }
    }

    var input = "Blob,Blob Jr"[...].utf8
    XCTAssertEqual(try people.parse(&input), [.blob, .blobJr])

    input = "Blob Jr,Blob"[...].utf8
    XCTAssertEqual(try people.parse(&input), [.blobJr, .blob])

    input = "Blob,Mr Blob"[...].utf8
    XCTAssertThrowsError(try people.parse(&input))
  }
}

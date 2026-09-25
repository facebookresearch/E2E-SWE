import Parsing
import XCTest

final class IntEnumTests: XCTestCase {
  // Integer raw values, including negatives: "-42" is attempted before "-4" so that "-42" is not
  // mis-parsed as "-4" followed by "2".
  func testIntRawValueEnum() throws {
    enum Person: Int, CaseIterable {
      case blob = -4
      case blobJr = -42
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

    var input = "-4,-42"[...].utf8
    XCTAssertEqual(try people.parse(&input), [.blob, .blobJr])

    input = "-42,-4"[...].utf8
    XCTAssertEqual(try people.parse(&input), [.blobJr, .blob])

    input = "-42,-100"[...].utf8
    XCTAssertThrowsError(try people.parse(&input))
  }
}

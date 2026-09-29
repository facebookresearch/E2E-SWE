import Parsing
import XCTest

final class UTF8ScalarsTests: XCTestCase {
  // Parsing directly against the UTF-8 view and the Unicode-scalar view of a string.
  func testUTF8AndUnicodeScalars() throws {
    var utf8 = "123 rest"[...].utf8
    XCTAssertEqual(123, try Int.parser(of: Substring.UTF8View.self).parse(&utf8))
    XCTAssertEqual(" rest", String(utf8))

    var scalars = "🇺🇸 Hello"[...].unicodeScalars
    let flag = "🇺".unicodeScalars
    XCTAssertNoThrow(try flag.parse(&scalars))
    XCTAssertEqual("🇸 Hello", Substring(scalars))
  }
}

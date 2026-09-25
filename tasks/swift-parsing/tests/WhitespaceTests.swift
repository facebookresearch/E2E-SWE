import Parsing
import XCTest

final class WhitespaceTests: XCTestCase {
  // `Whitespace` consumes Unicode whitespace, configurable to all / horizontal / vertical.
  func testWhitespaceConfigurations() throws {
    var input = "    \r \t\t \r\n \n\r    Hello, world!"[...].utf8
    XCTAssertNoThrow(try Whitespace().parse(&input))
    XCTAssertEqual("Hello, world!", Substring(input))

    input = "    \r \t\t \r\n \n\r    Hello, world!"[...].utf8
    XCTAssertNoThrow(try Whitespace(.horizontal).parse(&input))
    XCTAssertEqual("\r \t\t \r\n \n\r    Hello, world!", Substring(input))

    input = "\r\n\r\n \n\r    Hello, world!"[...].utf8
    XCTAssertNoThrow(try Whitespace(.vertical).parse(&input))
    XCTAssertEqual(" \n\r    Hello, world!", Substring(input))
  }
}

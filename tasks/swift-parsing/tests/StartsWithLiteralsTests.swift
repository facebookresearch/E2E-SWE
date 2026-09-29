import Parsing
import XCTest

final class StartsWithLiteralsTests: XCTestCase {
  // A bare string literal is a void-output parser matching that exact text; `StartsWith` matches a
  // fixed prefix over any collection (here UTF-8).
  func testStartsWithAndLiterals() throws {
    var str = "Hello, world!"[...].utf8
    XCTAssertNoThrow(try StartsWith("Hello".utf8).parse(&str))
    XCTAssertEqual(", world!", Substring(str))

    let greeting = Parse(input: Substring.self) {
      "Hello, "
      Rest()
    }
    XCTAssertEqual("world!", try greeting.parse("Hello, world!"))
  }
}

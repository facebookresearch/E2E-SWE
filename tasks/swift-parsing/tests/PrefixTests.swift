import Parsing
import XCTest

final class PrefixTests: XCTestCase {
  // `Prefix` consumes a bounded, optionally predicate-limited run; a count minimum that can't be
  // met is a diagnosed failure.
  func testPrefixVariants() throws {
    var input = "42 Hi!"[...]
    XCTAssertEqual("42", try Prefix(2).parse(&input))
    XCTAssertEqual(" Hi!", input)

    input = "42 Hello, world!"[...]
    XCTAssertEqual("42", try Prefix(while: { $0.isNumber }).parse(&input))
    XCTAssertEqual(" Hello, world!", input)

    input = "42 Hello, world!"[...]
    XCTAssertEqual("42 Hello, ", try Prefix(...10).parse(&input))
    XCTAssertEqual("world!", input)

    input = "42 Hello, world!"[...]
    XCTAssertEqual("42", try Prefix(1..., while: { $0.isNumber }).parse(&input))

    // Requiring more elements than remain fails; the exact diagnostic wording is covered by the
    // error-rendering tests, so here we only assert that it fails.
    input = "42 Hi!"[...]
    XCTAssertThrowsError(try Prefix(10).parse(&input))
  }
}

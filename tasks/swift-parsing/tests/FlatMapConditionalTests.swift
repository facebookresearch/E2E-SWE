import Parsing
import XCTest

private struct OddNumberError: Error {}

final class FlatMapConditionalTests: XCTestCase {
  // `flatMap` chooses a follow-on parser from the previous output. Combined with `Always` and
  // `Fail` (in an `if`/`else`) it expresses a validated, conditional parse.
  func testFlatMapConditional() throws {
    let parser = Parse(input: Substring.UTF8View.self) { Int.parser() }
      .flatMap { (n: Int) in
        if n.isMultiple(of: 2) {
          Always<Substring.UTF8View, Int>(n)
        } else {
          Fail<Substring.UTF8View, Int>(throwing: OddNumberError())
        }
      }

    var input = "42 rest"[...].utf8
    XCTAssertEqual(try parser.parse(&input), 42)
    XCTAssertEqual(Substring(input), " rest")

    var odd = "43 rest"[...].utf8
    XCTAssertThrowsError(try parser.parse(&odd))
    XCTAssertEqual(Substring(odd), " rest")
  }
}

import Parsing
import XCTest

final class BuildConditionalTests: XCTestCase {
  // `if` with a void body conditionally includes a literal; `if` with an output body produces an
  // optional output.
  func testBuildConditional() throws {
    var parseComma = true
    var parser = Parse(input: Substring.self) {
      "Hello"
      if parseComma { "," }
      " "
      Prefix { $0 != "!" }
      "!"
    }
    var input = "Hello, world!"[...]
    XCTAssertEqual("world", try parser.parse(&input))

    parseComma = false
    parser = Parse(input: Substring.self) {
      "Hello"
      if parseComma { "," }
      " "
      Prefix { $0 != "!" }
      "!"
    }
    input = "Hello world!"[...]
    XCTAssertEqual("world", try parser.parse(&input))

    var parseInt = true
    var optional = Parse(input: Substring.self) {
      if parseInt {
        Int.parser()
        " "
      }
      Rest()
    }
    var input2 = "42 Blob"[...]
    let (n1, s1) = try optional.parse(&input2)
    XCTAssertEqual(n1, 42)
    XCTAssertEqual(s1, "Blob")

    parseInt = false
    optional = Parse(input: Substring.self) {
      if parseInt {
        Int.parser()
        " "
      }
      Rest()
    }
    input2 = "Blob"[...]
    let (n2, s2) = try optional.parse(&input2)
    XCTAssertEqual(n2, nil)
    XCTAssertEqual(s2, "Blob")
  }
}

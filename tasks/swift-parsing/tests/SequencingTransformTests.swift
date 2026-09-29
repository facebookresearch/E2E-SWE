import Parsing
import XCTest

private struct User: Equatable {
  var id: Int
  var name: String
  var isAdmin: Bool
}

final class SequencingTransformTests: XCTestCase {
  // Literals contribute nothing to the output; the remaining non-void parsers accumulate into a
  // flat tuple. A leading transform closure maps that tuple into a domain value.
  func testSequencingAndStructTransform() throws {
    let point = Parse(input: Substring.self) {
      "("
      Int.parser()
      ","
      Int.parser()
      ")"
    }
    let (x, y) = try point.parse("(2,-4)")
    XCTAssertEqual(x, 2)
    XCTAssertEqual(y, -4)

    let user = Parse(input: Substring.self, User.init(id:name:isAdmin:)) {
      Int.parser()
      ","
      Prefix { $0 != "," }.map(String.init)
      ","
      Bool.parser()
    }
    XCTAssertEqual(try user.parse("1,Blob,true"), User(id: 1, name: "Blob", isAdmin: true))
  }
}

import Parsing
import XCTest

private struct User: Equatable {
  var id: Int
  var name: String
  var isAdmin: Bool
}

final class MemberwiseRoundTripTests: XCTestCase {
  // A `ParsePrint` with a memberwise conversion round-trips a struct: parse text to value, print
  // value back to identical text.
  func testMemberwiseRoundTrip() throws {
    let user = ParsePrint(input: Substring.self, .memberwise(User.init(id:name:isAdmin:))) {
      Int.parser()
      ","
      Prefix { $0 != "," }.map(.string)
      ","
      Bool.parser()
    }

    XCTAssertEqual(try user.parse("1,Blob,true"), User(id: 1, name: "Blob", isAdmin: true))
    XCTAssertEqual(try user.print(User(id: 1, name: "Blob", isAdmin: true)), "1,Blob,true")
  }
}

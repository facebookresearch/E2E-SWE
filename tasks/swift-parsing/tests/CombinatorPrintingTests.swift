import Parsing
import XCTest

final class CombinatorPrintingTests: XCTestCase {
  // The print side of the collection/lookahead combinators round-trips: `PrefixUpTo` /
  // `PrefixThrough` re-emit their value, `Optionally` prints the wrapped value or nothing,
  // `Backtracking` is transparent, `Skip` prints its (void) parser, and `Not` prints nothing when
  // it has nothing to negate.
  func testCombinatorPrinting() throws {
    let upTo = ParsePrint(input: Substring.self) {
      PrefixUpTo(", ").map(.string)
      ", "
      Rest().map(.string)
    }
    let (a, b) = try upTo.parse("Hello, world")
    XCTAssertEqual(a, "Hello")
    XCTAssertEqual(b, "world")
    XCTAssertEqual(try upTo.print(("Hello", "world")), "Hello, world")

    let through = ParsePrint(input: Substring.self) {
      PrefixThrough(", ").map(.string)
      Rest().map(.string)
    }
    XCTAssertEqual(try through.print(("Hello, ", "world")), "Hello, world")

    let optionalName = ParsePrint(input: Substring.self) {
      Optionally { Prefix(1...) { !$0.isWhitespace } }
    }
    XCTAssertEqual(try optionalName.print(.some("foo"[...])), "foo")
    XCTAssertEqual(try optionalName.print(Substring?.none), "")

    let backtracking = ParsePrint(input: Substring.self) {
      Backtracking { Prefix(2) { $0 == "A" } }
    }
    XCTAssertEqual(try backtracking.print("AA"[...]), "AA")

    let padded = ParsePrint(input: Substring.self) {
      Skip { Whitespace() }
      Int.parser()
    }
    XCTAssertEqual(try padded.print(42), "42")

    var notInput = "abc"[...]
    XCTAssertNoThrow(try Not { "//" }.print((), into: &notInput))
    XCTAssertEqual(notInput, "abc")
  }
}

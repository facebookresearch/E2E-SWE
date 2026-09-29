import Parsing
import XCTest

private enum Currency: Equatable { case eur, gbp, usd, unknown }

final class OneOfTests: XCTestCase {
  // `OneOf` tries alternatives in order (most specific first); `replaceError(with:)` turns a
  // failure into a default, non-throwing result.
  func testOneOfOrderingAndReplaceError() throws {
    let field = Parse(input: Substring.self) {
      OneOf {
        Parse {
          "\""
          Prefix { $0 != "\"" }
          "\""
        }
        Prefix { $0 != "," && $0 != "\n" }
      }
    }
    XCTAssertEqual("McBlob, Esq.", try field.parse("\"McBlob, Esq.\""))
    XCTAssertEqual("Blob", try field.parse("Blob"))

    let currency = OneOf {
      "€".map { Currency.eur }
      "£".map { Currency.gbp }
      "$".map { Currency.usd }
    }
    .replaceError(with: Currency.unknown)

    var s1 = "$"[...]
    XCTAssertEqual(.usd, currency.parse(&s1))
    var s2 = "฿"[...]
    XCTAssertEqual(.unknown, currency.parse(&s2))
    XCTAssertEqual("฿", s2)
  }
}

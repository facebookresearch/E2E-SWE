import Parsing
import XCTest

final class PipeAcrossInputTests: XCTestCase {
  // `pipe` runs a downstream parser on the output of an upstream parser, even when the two operate
  // on different input types: the upstream's `Substring` output (produced from a
  // `Substring.UTF8View` input) is fed into and fully consumed by a downstream parser running in the
  // `Substring` domain, and the downstream's result is derived from that piped-through output.
  func testPipeAcrossInputTypes() throws {
    let upstream = Parse(input: Substring.UTF8View.self) {
      Always("Hello world"[...])
    }
    let piped = upstream.pipe {
      Parse(input: Substring.self) {
        Rest().map(.string)
      }
    }
    var input = ""[...].utf8
    XCTAssertEqual("Hello world", try piped.parse(&input))
  }
}

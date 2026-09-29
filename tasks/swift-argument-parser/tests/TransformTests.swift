import ArgumentParser
import XCTest

private struct WithTransform: ParsableArguments {
  @Option(transform: { arg in
    guard let n = Int(arg) else { throw ValidationError("Could not transform to an Int.") }
    return n * 2
  })
  var doubled: Int
}

final class TransformTests: XCTestCase {
  /// A `transform:` closure converts the raw string and may throw `ValidationError`.
  func testTransformClosure() throws {
    XCTAssertEqual(try WithTransform.parse(["--doubled", "21"]).doubled, 42)
    XCTAssertThrowsError(try WithTransform.parse(["--doubled", "abc"]))
  }
}

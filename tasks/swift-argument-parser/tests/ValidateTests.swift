import ArgumentParser
import XCTest

private struct WithValidation: ParsableArguments {
  @Argument var count: Int
  func validate() throws {
    if count < 0 { throw ValidationError("Count must be non-negative.") }
  }
}

final class ValidateTests: XCTestCase {
  /// `validate()` runs after parsing; throwing turns a valid parse into a failure that maps to
  /// the validation exit code.
  func testValidateMethod() throws {
    XCTAssertEqual(try WithValidation.parse(["3"]).count, 3)
    XCTAssertThrowsError(try WithValidation.parse(["-1"])) { error in
      XCTAssertEqual(WithValidation.exitCode(for: error), .validationFailure)
    }
  }
}

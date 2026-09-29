import ArgumentParser
import XCTest

private struct Dummy: ParsableArguments {}

final class ExitCodeTests: XCTestCase {
  /// `ExitCode` exposes standard codes and maps errors: `ValidationError` -> `.validationFailure`,
  /// an explicit `ExitCode` passes through, a `CleanExit` is success.
  func testExitCodes() throws {
    XCTAssertEqual(ExitCode.success.rawValue, 0)
    XCTAssertTrue(ExitCode.success.isSuccess)
    XCTAssertFalse(ExitCode.failure.isSuccess)
    XCTAssertEqual(ExitCode(rawValue: 42).rawValue, 42)
    XCTAssertEqual(Dummy.exitCode(for: ValidationError("bad")), .validationFailure)
    XCTAssertEqual(Dummy.exitCode(for: ExitCode(42)), ExitCode(42))
    XCTAssertEqual(Dummy.exitCode(for: CleanExit.message("done")), .success)
  }
}

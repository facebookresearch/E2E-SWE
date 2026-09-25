import ArgumentParser
import XCTest

private struct BoolFlags: ParsableArguments {
  @Flag var verbose = false
  @Flag(inversion: .prefixedNo) var extattr = false
  @Flag(inversion: .prefixedNo) var extattr2: Bool?
  @Flag(inversion: .prefixedEnableDisable) var logging = false
}

final class BoolFlagTests: XCTestCase {
  /// Plain and invertible boolean flags: absent flags take defaults (inverted optional stays
  /// nil); `--flag`/`--no-flag` set and clear; repeats are last-wins.
  func testBooleanFlagsAndPrefixedNo() throws {
    let def = try BoolFlags.parse([])
    XCTAssertEqual(def.verbose, false)
    XCTAssertEqual(def.extattr, false)
    XCTAssertNil(def.extattr2)
    XCTAssertEqual(def.logging, false)

    let set = try BoolFlags.parse(["--verbose", "--extattr", "--extattr2"])
    XCTAssertEqual(set.verbose, true)
    XCTAssertEqual(set.extattr, true)
    XCTAssertEqual(set.extattr2, true)

    XCTAssertEqual(try BoolFlags.parse(["--extattr", "--no-extattr"]).extattr, false)
    XCTAssertEqual(try BoolFlags.parse(["--no-extattr", "--no-extattr", "--extattr"]).extattr, true)
    XCTAssertEqual(try BoolFlags.parse(["--no-extattr2", "--no-extattr2"]).extattr2, false)
  }

  /// `.prefixedEnableDisable` produces `--enable-x`/`--disable-x` names, with last-wins.
  func testEnableDisableInversion() throws {
    XCTAssertEqual(try BoolFlags.parse(["--enable-logging"]).logging, true)
    XCTAssertEqual(try BoolFlags.parse(["--disable-logging", "--enable-logging"]).logging, true)
    XCTAssertEqual(try BoolFlags.parse(["--enable-logging", "--disable-logging"]).logging, false)
  }
}

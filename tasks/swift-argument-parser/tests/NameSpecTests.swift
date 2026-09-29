import ArgumentParser
import XCTest

private struct Names: ParsableArguments {
  @Option(name: .shortAndLong) var verbose: String
  @Option(name: [.customShort("n"), .long]) var name: String
  @Option(name: .customLong("file-path")) var filePath: String
  @Option(name: [.customLong("ttl", withSingleDash: true)]) var title: String
}

final class NameSpecTests: XCTestCase {
  /// Every `NameSpecification` form: `.shortAndLong` gives `-v`/`--verbose`, `.customShort` +
  /// `.long` gives `-n`/`--name`, `.customLong` overrides the long name, and a single-dash long
  /// name (`-ttl`) works. camelCase property names become kebab-cased long names.
  func testNameSpecificationForms() throws {
    let a = try Names.parse(["-v", "V", "-n", "N", "--file-path", "P", "-ttl", "T"])
    XCTAssertEqual(a.verbose, "V")
    XCTAssertEqual(a.name, "N")
    XCTAssertEqual(a.filePath, "P")
    XCTAssertEqual(a.title, "T")

    let b = try Names.parse(["--verbose", "V", "--name", "N", "--file-path", "P", "-ttl", "T"])
    XCTAssertEqual(b.verbose, "V")
    XCTAssertEqual(b.name, "N")

    XCTAssertThrowsError(try Names.parse(["-v", "V", "-n", "N", "--filePath", "P", "-ttl", "T"]))
    XCTAssertThrowsError(try Names.parse(["-v", "V", "-n", "N", "--file-path", "P", "--ttl", "T"]))
  }
}

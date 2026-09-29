import ArgumentParser
import XCTest

private struct App: ParsableCommand {
  static let configuration = CommandConfiguration(commandName: "app", subcommands: [Container.self])
}

private struct Container: ParsableCommand {
  static let configuration = CommandConfiguration(commandName: "container", subcommands: [Leaf.self])
}

private struct Leaf: ParsableCommand {
  static let configuration = CommandConfiguration(commandName: "leaf")
  @Option var value: Int
}

final class NestedCommandTests: XCTestCase {
  /// A multi-level command tree resolves the full path and returns the leaf instance.
  func testNestedSubcommands() throws {
    let leaf = try XCTUnwrap(try App.parseAsRoot(["container", "leaf", "--value", "7"]) as? Leaf)
    XCTAssertEqual(leaf.value, 7)
    XCTAssertThrowsError(try App.parseAsRoot(["container", "leaf"]))
    XCTAssertThrowsError(try App.parseAsRoot(["leaf", "--value", "7"]))
  }
}

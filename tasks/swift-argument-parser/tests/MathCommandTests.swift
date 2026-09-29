import ArgumentParser
import XCTest

private struct SharedOptions: ParsableArguments {
  @Flag(name: [.customShort("x"), .customLong("hex")]) var hex = false
  @Argument var values: [Int] = []
}

private struct MathRoot: ParsableCommand {
  static let configuration = CommandConfiguration(
    commandName: "math", subcommands: [Add.self, Multiply.self], defaultSubcommand: Add.self)
}

private struct Add: ParsableCommand {
  static let configuration = CommandConfiguration(commandName: "add", aliases: ["plus"])
  @OptionGroup var options: SharedOptions
}

private struct Multiply: ParsableCommand {
  static let configuration = CommandConfiguration(commandName: "mul")
  @OptionGroup var options: SharedOptions
}

final class MathCommandTests: XCTestCase {
  /// Parsing dispatches to the named subcommand and `@OptionGroup` flattens shared flags/args
  /// into each subcommand.
  func testSubcommandDispatch() throws {
    let add = try XCTUnwrap(try MathRoot.parseAsRoot(["add", "1", "2", "3"]) as? Add)
    XCTAssertEqual(add.options.values, [1, 2, 3])
    XCTAssertEqual(add.options.hex, false)

    let mul = try XCTUnwrap(try MathRoot.parseAsRoot(["mul", "--hex", "2", "3"]) as? Multiply)
    XCTAssertEqual(mul.options.values, [2, 3])
    XCTAssertEqual(mul.options.hex, true)

    let shortHex = try XCTUnwrap(try MathRoot.parseAsRoot(["mul", "-x", "5"]) as? Multiply)
    XCTAssertEqual(shortHex.options.hex, true)
    XCTAssertEqual(shortHex.options.values, [5])

    XCTAssertThrowsError(try MathRoot.parseAsRoot(["divide", "1"]))
  }

  /// With no subcommand token, the configured `defaultSubcommand` is selected.
  func testDefaultSubcommand() throws {
    let add = try XCTUnwrap(try MathRoot.parseAsRoot(["1", "2"]) as? Add)
    XCTAssertEqual(add.options.values, [1, 2])
  }

  /// A subcommand alias resolves to the same command as its canonical name.
  func testSubcommandAlias() throws {
    let add = try XCTUnwrap(try MathRoot.parseAsRoot(["plus", "4", "5"]) as? Add)
    XCTAssertEqual(add.options.values, [4, 5])
  }
}

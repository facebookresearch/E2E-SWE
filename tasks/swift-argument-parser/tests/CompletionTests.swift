import ArgumentParser
import XCTest

private struct Tool: ParsableCommand {
  static let configuration = CommandConfiguration(commandName: "tool", subcommands: [Sub.self])
  @Option(help: "The user's name.") var name: String?
  @Flag var verbose = false
}

private struct Sub: ParsableCommand {
  static let configuration = CommandConfiguration(commandName: "sub")
}

final class CompletionTests: XCTestCase {
  /// Completion scripts register the command and enumerate its options and subcommands: bash
  /// emits the `complete` registration, zsh the `#compdef` header; both reference option long
  /// names and subcommand names.
  func testCompletionScriptGeneration() {
    let bash = Tool.completionScript(for: .bash)
    XCTAssertTrue(bash.contains("complete -o filenames -F"), "bash should register a completion function")
    XCTAssertTrue(bash.contains("tool"), "bash should name the command")
    XCTAssertTrue(bash.contains("--name"), "bash should list --name")
    XCTAssertTrue(bash.contains("--verbose"), "bash should list --verbose")
    XCTAssertTrue(bash.contains("sub"), "bash should list the subcommand")

    let zsh = Tool.completionScript(for: .zsh)
    XCTAssertTrue(zsh.contains("#compdef tool"), "zsh should start with #compdef")
    XCTAssertTrue(zsh.contains("--name"), "zsh should list --name")
    XCTAssertTrue(zsh.contains("sub"), "zsh should list the subcommand")
  }
}

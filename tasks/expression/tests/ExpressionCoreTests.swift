// Hidden grading suite for the core `Expression` (Double) engine.
// Uses only the public API exposed by `import Expression`.

import XCTest
import Foundation
import Expression

final class ExpressionCoreTests: XCTestCase {
    // MARK: Parsing & arithmetic

    func testArithmeticPrecedenceAndAssociativity() throws {
        XCTAssertEqual(try Expression("2 + 3 * 4").evaluate(), 14)
        XCTAssertEqual(try Expression("(2 + 3) * 4").evaluate(), 20)
        XCTAssertEqual(try Expression("2 + 3 * 2").evaluate(), 8)
        XCTAssertEqual(try Expression("10 - 3 - 2").evaluate(), 5)   // left-associative
        XCTAssertEqual(try Expression("3 * 4 +5").evaluate(), 17)    // whitespace-insensitive
    }

    func testUnaryMinusAndParentheses() throws {
        XCTAssertEqual(try Expression("-3 + 5").evaluate(), 2)
        XCTAssertEqual(try Expression("-(2 + 3)").evaluate(), -5)
        XCTAssertEqual(try Expression("- -5").evaluate(), 5)
        XCTAssertEqual(try Expression("2 * -3").evaluate(), -6)
    }

    func testModuloAndDivideByZero() throws {
        XCTAssertEqual(try Expression("10 % 3").evaluate(), 1)
        XCTAssertEqual(try Expression("-7 % 3").evaluate(), -1)      // fmod semantics
        XCTAssertEqual(try Expression("mod(10, 3)").evaluate(), 1)
        XCTAssertEqual(try Expression("1 / 0").evaluate(), .infinity)
    }

    func testNumberLiteralParsing() throws {
        XCTAssertEqual(try Expression("0xFF").evaluate(), 255)
        XCTAssertEqual(try Expression("1.5e2").evaluate(), 150)
        XCTAssertEqual(try Expression(".5").evaluate(), 0.5)
        XCTAssertEqual(try Expression("19911919912912918507489841695948800").evaluate(),
                       19_911_919_912_912_918_507_489_841_695_948_800)
    }

    // MARK: Standard library

    func testBuiltinUnaryMathFunctionsAndPi() throws {
        XCTAssertEqual(try Expression("sqrt(16)").evaluate(), 4)
        XCTAssertEqual(try Expression("floor(3.7)").evaluate(), 3)
        XCTAssertEqual(try Expression("ceil(3.2)").evaluate(), 4)
        XCTAssertEqual(try Expression("round(2.5)").evaluate(), 3)
        XCTAssertEqual(try Expression("abs(-5)").evaluate(), 5)
        XCTAssertEqual(try Expression("log(1)").evaluate(), 0)
        XCTAssertEqual(try Expression("pi").evaluate(), Double.pi, accuracy: 1e-12)
    }

    func testBuiltinBinaryAndVariadicFunctions() throws {
        XCTAssertEqual(try Expression("pow(2, 10)").evaluate(), 1024)
        XCTAssertEqual(try Expression("atan2(0, 1)").evaluate(), 0)
        XCTAssertEqual(try Expression("max(1, 7, 3)").evaluate(), 7)
        XCTAssertEqual(try Expression("min(4, 2, 9)").evaluate(), 2)
    }

    // MARK: Custom constants, variables, functions, operators

    func testConstantsAndVariableSymbols() throws {
        XCTAssertEqual(try Expression("a + b", constants: ["a": 2, "b": 3]).evaluate(), 5)
        let expr = Expression("foo + bar(5)", constants: ["foo": 4],
                              symbols: [.function("bar", arity: 1): { $0[0] + 1 }])
        XCTAssertEqual(try expr.evaluate(), 10)
    }

    func testCustomFunctionOverloadingByArity() throws {
        // Built-in pow/2 still works when pow/1 is added.
        XCTAssertEqual(try Expression("pow(3, 3)",
                                      symbols: [.function("pow", arity: 1): { $0[0] * $0[0] }]).evaluate(), 27)
        XCTAssertEqual(try Expression("pow(3)",
                                      symbols: [.function("pow", arity: 1): { $0[0] * $0[0] }]).evaluate(), 9)
        // Two user overloads, picked by argument count.
        XCTAssertEqual(try Expression("foo(3, 3)", symbols: [
            .function("foo", arity: 1): { $0[0] },
            .function("foo", arity: 2): { $0[0] + $0[1] },
        ]).evaluate(), 6)
    }

    func testCustomOperators() throws {
        XCTAssertEqual(try Expression("50%", symbols: [.postfix("%"): { $0[0] / 100 }]).evaluate(), 0.5)
        XCTAssertEqual(try Expression("3 plus 4", symbols: [.infix("plus"): { $0[0] + $0[1] }]).evaluate(), 7)
        XCTAssertEqual(try Expression("~5", symbols: [.prefix("~"): { $0[0] * $0[0] }]).evaluate(), 25)
    }

    func testCustomExponentOperatorPrecedence() throws {
        // `^` binds tighter than `*`, so this is 3 * (2^3) = 24, not (3*2)^3.
        XCTAssertEqual(try Expression("3 * 2 ^ 3", symbols: [.infix("^"): { pow($0[0], $0[1]) }]).evaluate(), 24)
    }

    // MARK: Boolean library

    func testBooleanComparisonsAndLogic() throws {
        XCTAssertEqual(try Expression("5 > 3", options: .boolSymbols).evaluate(), 1)
        XCTAssertEqual(try Expression("2 == 2", options: .boolSymbols).evaluate(), 1)
        XCTAssertEqual(try Expression("2 != 2", options: .boolSymbols).evaluate(), 0)
        XCTAssertEqual(try Expression("3 <= 3", options: .boolSymbols).evaluate(), 1)
        XCTAssertEqual(try Expression("1 && 0", options: .boolSymbols).evaluate(), 0)
        XCTAssertEqual(try Expression("1 || 0", options: .boolSymbols).evaluate(), 1)
        XCTAssertEqual(try Expression("!0", options: .boolSymbols).evaluate(), 1)
        XCTAssertEqual(try Expression("!5", options: .boolSymbols).evaluate(), 0)
        // Boolean symbols are opt-in: without the option, `>` is undefined.
        XCTAssertThrowsError(try Expression("5 > 3").evaluate()) { error in
            XCTAssertEqual(error as? Expression.Error, .undefinedSymbol(.infix(">")))
        }
    }

    func testTernaryOperator() throws {
        XCTAssertEqual(try Expression("1 ? 10 : 20", options: .boolSymbols).evaluate(), 10)
        XCTAssertEqual(try Expression("0 ? 10 : 20", options: .boolSymbols).evaluate(), 20)
        XCTAssertEqual(try Expression("1 - 1 ? 3 * 5 : 2 * 3", options: .boolSymbols).evaluate(), 6)
        XCTAssertEqual(try Expression("5 ?: 4", options: .boolSymbols).evaluate(), 5)
        XCTAssertEqual(try Expression("0 ?: 4", options: .boolSymbols).evaluate(), 4)
    }

    func testEqualityIsRightAssociative() throws {
        // b == c -> 1, then a == 1 -> 1
        XCTAssertEqual(try Expression("a == b == c", options: .boolSymbols,
                                      constants: ["a": 1, "b": 2, "c": 2]).evaluate(), 1)
    }

    // MARK: Arrays

    func testArraySubscriptAndBounds() throws {
        XCTAssertEqual(try Expression("foo[2]", arrays: ["foo": [1, 2, 3]]).evaluate(), 3)
        XCTAssertEqual(try Expression("bar[2]",
                                      symbols: [.array("bar"): { [10, 20, 30][Int($0[0])] }]).evaluate(), 30)
        XCTAssertThrowsError(try Expression("foo[3]", arrays: ["foo": [1, 2, 3]]).evaluate()) { error in
            XCTAssertEqual(error as? Expression.Error, .arrayBounds(.array("foo"), 3))
        }
    }

    // MARK: Parsing reuse & advanced initializer

    func testParseReuseAndAdvancedInitializer() throws {
        let parsed = Expression.parse("a + b", usingCache: false)
        XCTAssertEqual(try Expression(parsed, constants: ["a": 1, "b": 2]).evaluate(), 3)
        XCTAssertEqual(try Expression(parsed, constants: ["a": 10, "b": 20]).evaluate(), 30)

        // Dynamic resolution via pureSymbols closure.
        let dynamic = Expression(Expression.parse("foo(21)"), pureSymbols: { symbol in
            if case .function("foo", arity: 1) = symbol { return { $0[0] * 2 } }
            return nil // fall back to the standard library
        })
        XCTAssertEqual(try dynamic.evaluate(), 42)
        // Returning nil from the lookup falls back to the standard library.
        XCTAssertEqual(try Expression(Expression.parse("3 + 4"), pureSymbols: { _ in nil }).evaluate(), 7)
    }

    // MARK: Errors

    func testErrorCases() throws {
        XCTAssertThrowsError(try Expression("foo()").evaluate()) { error in
            XCTAssertEqual(error as? Expression.Error, .undefinedSymbol(.function("foo", arity: 0)))
        }
        XCTAssertThrowsError(try Expression("pow(4, 5, 6)").evaluate()) { error in
            XCTAssertEqual(error as? Expression.Error, .arityMismatch(.function("pow", arity: 2)))
        }
        XCTAssertThrowsError(try Expression("min(3)").evaluate()) { error in
            XCTAssertEqual(error as? Expression.Error, .arityMismatch(.function("min", arity: .atLeast(2))))
        }
        XCTAssertThrowsError(try Expression("").evaluate()) { error in
            XCTAssertEqual(error as? Expression.Error, .emptyExpression)
        }
    }

    func testErrorDescriptions() {
        XCTAssertEqual(Expression.Error.message("boom").description, "boom")
        XCTAssertEqual(Expression.Error.emptyExpression.description, "Empty expression")
        XCTAssertEqual(Expression.Error.unexpectedToken(")").description, "Unexpected token `)`")
        XCTAssertEqual(Expression.Error.missingDelimiter("]").description, "Missing `]`")
        XCTAssertEqual(Expression.Error.undefinedSymbol(.postfix("foo")).description,
                       "Undefined postfix operator foo")
        XCTAssertEqual(Expression.Error.arityMismatch(.function("foo", arity: 1)).description,
                       "Function foo() expects 1 argument")
        XCTAssertEqual(Expression.Error.arityMismatch(.array("foo")).description,
                       "Array foo[] expects 1 argument")
        XCTAssertEqual(Expression.Error.arrayBounds(.array("foo"), 3).description,
                       "Index 3 out of bounds for array foo[]")
    }

    // MARK: Description normalization

    func testDescriptionNormalization() {
        XCTAssertEqual(Expression("a+b").description, "a + b")
        XCTAssertEqual(Expression("a+b*c").description, "a + b * c")
        XCTAssertEqual(Expression("a*(b+c)").description, "a * (b + c)")
        XCTAssertEqual(Expression("(a+b)*c").description, "(a + b) * c")
        XCTAssertEqual(Expression("(a+b)+c").description, "a + b + c")
        XCTAssertEqual(Expression("-foo").description, "-foo")
        XCTAssertEqual(Expression("- -foo").description, "-(-foo)")
        XCTAssertEqual(Expression("foo%").description, "foo%")
        XCTAssertEqual(Expression("32 + 200014").description, "200046")
        XCTAssertEqual(Expression("2.4 + 7.65").description, "10.05")
    }

    // MARK: Optimization

    func testOptimizerConstantFolding() {
        let folded = Expression("5 + foo", constants: ["foo": 5])
        XCTAssertEqual(folded.symbols, [])
        XCTAssertEqual(folded.description, "10")

        let pureBuiltin = Expression("min(5, 6) + a")
        XCTAssertEqual(pureBuiltin.symbols, [.variable("a"), .infix("+")])
        XCTAssertEqual(pureBuiltin.description, "5 + a")

        let raw = Expression("3 * 5", options: .noOptimize)
        XCTAssertEqual(raw.symbols, [.infix("*")])
        XCTAssertEqual(raw.description, "3 * 5")

        let partial = Expression("foo(bar, baz)", constants: ["bar": 5, "baz": 2.5])
        XCTAssertEqual(partial.symbols, [.function("foo", arity: 2)])
        XCTAssertEqual(partial.description, "foo(5, 2.5)")
    }

    func testPureVsImpureInlining() {
        // Variables are never inlined, even with pureSymbols.
        let v = Expression("5 + foo", options: .pureSymbols, symbols: [.variable("foo"): { _ in 5 }])
        XCTAssertEqual(v.symbols, [.variable("foo"), .infix("+")])
        XCTAssertEqual(v.description, "5 + foo")

        // A custom function is impure by default (not folded)...
        let impure = Expression("5 + foo()", symbols: [.function("foo", arity: 0): { _ in 5 }])
        XCTAssertEqual(impure.symbols, [.infix("+"), .function("foo", arity: 0)])

        // ...but folds when declared pure.
        let pure = Expression("5 + foo()", options: .pureSymbols, symbols: [.function("foo", arity: 0): { _ in 5 }])
        XCTAssertEqual(pure.symbols, [])
        XCTAssertEqual(pure.description, "10")
    }

    func testSymbolsProperty() throws {
        let expr = Expression("mod(foo, bar)", symbols: [
            .variable("foo"): { _ in 5 },
            .variable("bar"): { _ in 2.5 },
        ])
        XCTAssertEqual(expr.symbols, [.function("mod", arity: 2), .variable("foo"), .variable("bar")])
        XCTAssertEqual(try expr.evaluate(), 0)   // fmod(5, 2.5)
    }

    // MARK: Validation helpers

    func testIsValidIdentifierAndOperator() {
        XCTAssertTrue(Expression.isValidIdentifier("foo"))
        XCTAssertTrue(Expression.isValidIdentifier("foo.bar"))
        XCTAssertTrue(Expression.isValidIdentifier("x'"))
        XCTAssertFalse(Expression.isValidIdentifier("foo bar"))
        XCTAssertFalse(Expression.isValidIdentifier("+"))
        XCTAssertFalse(Expression.isValidIdentifier(""))

        XCTAssertTrue(Expression.isValidOperator("+"))
        XCTAssertTrue(Expression.isValidOperator(","))
        XCTAssertTrue(Expression.isValidOperator(":"))
        XCTAssertTrue(Expression.isValidOperator("==="))
        XCTAssertFalse(Expression.isValidOperator("("))
        XCTAssertFalse(Expression.isValidOperator("foo"))
        XCTAssertFalse(Expression.isValidOperator(""))
    }
}

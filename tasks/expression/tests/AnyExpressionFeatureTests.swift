// Hidden grading suite for `AnyExpression` (arbitrary-typed values).
// Uses only the public API exposed by `import Expression`.

import XCTest
import Foundation
import Expression

final class AnyExpressionFeatureTests: XCTestCase {
    // MARK: Numerics & result typing

    func testNumericEvaluationAndCasting() throws {
        XCTAssertEqual(try AnyExpression("4 + 5").evaluate() as Int, 9)
        XCTAssertEqual(try AnyExpression("57.5").evaluate() as Int, 57)
        XCTAssertEqual(try AnyExpression("57.5").evaluate() as Double, 57.5)
        XCTAssertEqual(try AnyExpression("5 > 4").evaluate() as Double, 1.0)   // Bool -> numeric
        XCTAssertEqual(try AnyExpression("0.6").evaluate() as Bool, true)      // numeric -> Bool
        XCTAssertEqual(try AnyExpression("0").evaluate() as Bool, false)
    }

    func testNumericPrecisionPreserved() throws {
        XCTAssertEqual(try AnyExpression("true ? a : b",
                                         constants: ["a": UInt64.max, "b": Int64.min]).evaluate() as UInt64,
                       UInt64.max)
        XCTAssertEqual(try AnyExpression("a + b", constants: ["a": UInt64(4), "b": 5]).evaluate() as Int, 9)
    }

    // MARK: Strings

    func testStringConcatenationAndCoercion() throws {
        XCTAssertEqual(try AnyExpression("'foo' + 'bar'").evaluate() as String, "foobar")
        XCTAssertEqual(try AnyExpression("5 + 'foo'").evaluate() as String, "5foo")
        XCTAssertEqual(try AnyExpression("'foo' + 5").evaluate() as String, "foo5")
        XCTAssertEqual(try AnyExpression("'foo' + 5.1").evaluate() as String, "foo5.1")
        XCTAssertEqual(try AnyExpression("'foo' + true").evaluate() as String, "footrue")
    }

    func testStringNumberCoercionInConditional() throws {
        XCTAssertEqual(try AnyExpression("a + b == 9 ? c : ''",
                                         constants: ["a": 4, "b": 5, "c": "foo"]).evaluate() as String, "foo")
    }

    // MARK: Arrays

    func testArrayLiteralsSubscriptConcat() throws {
        XCTAssertEqual(try AnyExpression("[1, 2, 3]").evaluate() as [Int], [1, 2, 3])
        XCTAssertEqual(try AnyExpression("[1, 2, 3][1]").evaluate() as Int, 2)
        XCTAssertEqual(try AnyExpression("['a', 'b', 'c'][1]").evaluate() as String, "b")
        XCTAssertEqual(try AnyExpression("[1, 2] + [3, 4]").evaluate() as [Int], [1, 2, 3, 4])
    }

    func testArrayConstantSubscriptAndBounds() throws {
        XCTAssertEqual(try AnyExpression("a[b]", constants: ["a": ["hello", "world"], "b": 1]).evaluate() as String, "world")
        XCTAssertThrowsError(try AnyExpression("array[2]", constants: ["array": ["hello", "world"]]).evaluate() as Any) { error in
            XCTAssertEqual(error as? Expression.Error, .arrayBounds(.array("array"), 2))
        }
    }

    func testDictionarySubscript() throws {
        XCTAssertEqual(try AnyExpression("a[b]", constants: ["a": ["hello": "world"], "b": "hello"]).evaluate() as String,
                       "world")
        // Numeric key coercion: Int index matches a Double key.
        XCTAssertEqual(try AnyExpression("a[b]", constants: ["a": [1.0: "world"], "b": 1]).evaluate() as String,
                       "world")
    }

    // MARK: Ranges

    func testRangeLiterals() throws {
        XCTAssertEqual(try AnyExpression("1 ... 3").evaluate() as ClosedRange<Int>, 1 ... 3)
        XCTAssertEqual(try AnyExpression("1 ..< 3").evaluate() as Range<Int>, 1 ..< 3)
    }

    func testRangeSlicing() throws {
        // Slicing strings and arrays with range subscripts.
        XCTAssertEqual(try AnyExpression("'foo'[1 ..< 3]").evaluate() as String, "oo")
        XCTAssertEqual(try AnyExpression("'foo'[1 ... 2]").evaluate() as String, "oo")
        XCTAssertEqual(try AnyExpression("a[r]", constants: ["a": [1, 2, 3, 4], "r": 1 ... 2]).evaluate() as [Int], [2, 3])
    }

    // MARK: Optionals / null

    func testOptionalsAndNullCoalescing() throws {
        let null: String? = nil
        XCTAssertEqual(try AnyExpression("foo ?? 'bar'", constants: ["foo": null as Any]).evaluate() as String, "bar")
        XCTAssertEqual(try AnyExpression("foo ?? 'bar'", constants: ["foo": "foo"]).evaluate() as String, "foo")
        XCTAssertEqual(try AnyExpression("foo ?? 'bar'", constants: ["foo": NSNull()]).evaluate() as String, "bar")
        XCTAssertEqual(try AnyExpression("foo == nil ? 'bar' : 'foo'", constants: ["foo": null as Any]).evaluate() as String, "bar")
        XCTAssertEqual(try AnyExpression("foo == nil ? 'bar' : 'foo'", constants: ["foo": "x"]).evaluate() as String, "foo")
    }

    // MARK: Comparisons & booleans

    func testEqualityOfHashablesAndBooleans() throws {
        XCTAssertEqual(try AnyExpression("a == b", constants: ["a": ["hello", "world"], "b": ["hello", "world"]]).evaluate() as Bool, true)
        XCTAssertEqual(try AnyExpression("a == b", constants: ["a": ["hello", "world"], "b": ["world", "hello"]]).evaluate() as Bool, false)
        XCTAssertEqual(try AnyExpression("NaN == NaN", constants: ["NaN": Double.nan]).evaluate() as Bool, false)
        XCTAssertEqual(try AnyExpression("NaN != NaN", constants: ["NaN": Double.nan]).evaluate() as Bool, true)
        // Boolean library is enabled by default for AnyExpression.
        XCTAssertEqual(try AnyExpression("5 == 6").evaluate() as Bool, false)
        XCTAssertEqual(try AnyExpression("a && b", constants: ["a": true, "b": true]).evaluate() as Bool, true)
    }

    // MARK: Anonymous functions

    func testAnonymousFunctions() throws {
        let add: Expression.SymbolEvaluator = { $0[0] + $0[1] }
        let expr = AnyExpression("foo()(1, 2)", options: .pureSymbols,
                                 symbols: [.function("foo", arity: 0): { _ in add }])
        XCTAssertEqual(try expr.evaluate() as Int, 3)
    }

    // MARK: Type errors

    func testTypeMismatchesThrow() {
        // A nil used where a concrete value is required throws (spec'd example).
        let null: String? = nil
        XCTAssertThrowsError(try AnyExpression("foo + 'bar'", constants: ["foo": null as Any]).evaluate() as Any)
        // Boolean operators are undefined when boolSymbols is disabled.
        XCTAssertThrowsError(try AnyExpression("5 == 6", options: []).evaluate() as Bool) { error in
            XCTAssertEqual(error as? Expression.Error, .undefinedSymbol(.infix("==")))
        }
    }
}

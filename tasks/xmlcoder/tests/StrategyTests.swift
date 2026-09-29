// Hidden grading suite — encoder/decoder strategies: keys, dates, data, node encoding, floats.
// Public API only (`import XMLCoder`). Expected values taken from XMLCoder's own tests.

import XCTest
import Foundation
import XMLCoder

private struct SnakeItem: Codable, Equatable {
    let text: String
    enum CodingKeys: String, CodingKey { case text = "tagName" }
}

private struct CapItem: Codable, Equatable {
    let text: String
    enum CodingKeys: String, CodingKey { case text = "t" }
}

private struct UpperItem: Codable, Equatable {
    let text: String
    enum CodingKeys: String, CodingKey { case text = "tag" }
}

private struct DateBox: Codable, Equatable { let date: Date }
private struct DataBox: Codable, Equatable { let blob: Data }
private struct FloatBox: Codable, Equatable { let value: Float }
private struct MixNode: Codable, Equatable { let id: Int; let name: String }

private func gmtFormatter() -> DateFormatter {
    let fmt = DateFormatter()
    fmt.dateFormat = "yyyy-MM-dd"
    fmt.timeZone = TimeZone(identifier: "GMT")
    fmt.locale = Locale(identifier: "en_US_POSIX")
    return fmt
}

final class StrategyTests: XCTestCase {
    func testKeyEncodingStrategies() throws {
        func encode(_ item: some Encodable, _ strategy: XMLEncoder.KeyEncodingStrategy) throws -> String {
            let encoder = XMLEncoder()
            encoder.keyEncodingStrategy = strategy
            return String(data: try encoder.encode(item, withRootKey: "si"), encoding: .utf8)!
        }
        XCTAssertEqual(try encode(SnakeItem(text: "blah"), .convertToSnakeCase), "<si><tag_name>blah</tag_name></si>")
        XCTAssertEqual(try encode(SnakeItem(text: "blah"), .convertToKebabCase), "<si><tag-name>blah</tag-name></si>")
        XCTAssertEqual(try encode(CapItem(text: "blah"), .capitalized), "<si><T>blah</T></si>")
        XCTAssertEqual(try encode(UpperItem(text: "blah"), .uppercased), "<si><TAG>blah</TAG></si>")
    }

    func testKeyDecodingStrategies() throws {
        func decode<T: Decodable>(_ type: T.Type, _ xml: String, _ strategy: XMLDecoder.KeyDecodingStrategy) throws -> T {
            let decoder = XMLDecoder()
            decoder.keyDecodingStrategy = strategy
            return try decoder.decode(type, from: xml.data(using: .utf8)!)
        }
        XCTAssertEqual(try decode(SnakeItem.self, "<si><tag_name>blah</tag_name></si>", .convertFromSnakeCase),
                       SnakeItem(text: "blah"))
        XCTAssertEqual(try decode(SnakeItem.self, "<si><tag-name>blah</tag-name></si>", .convertFromKebabCase),
                       SnakeItem(text: "blah"))
        XCTAssertEqual(try decode(CapItem.self, "<si><T>blah</T></si>", .convertFromCapitalized),
                       CapItem(text: "blah"))
        XCTAssertEqual(try decode(SnakeItem.self, "<si><TAG_NAME>blah</TAG_NAME></si>", .convertFromUppercase),
                       SnakeItem(text: "blah"))
    }

    func testDateStrategies() throws {
        let epoch = DateBox(date: Date(timeIntervalSince1970: 0.0))
        let secondsEncoder = XMLEncoder()
        secondsEncoder.dateEncodingStrategy = .secondsSince1970
        let secondsXML = try secondsEncoder.encode(epoch, withRootKey: "container")
        XCTAssertEqual(String(data: secondsXML, encoding: .utf8), "<container><date>0.0</date></container>")
        // Decoder default is .secondsSince1970.
        XCTAssertEqual(try XMLDecoder().decode(DateBox.self, from: secondsXML), epoch)

        let formattedValue = DateBox(date: Date(timeIntervalSince1970: 970_358_400))
        let fmtEncoder = XMLEncoder()
        fmtEncoder.dateEncodingStrategy = .formatted(gmtFormatter())
        let fmtXML = try fmtEncoder.encode(formattedValue, withRootKey: "container")
        XCTAssertEqual(String(data: fmtXML, encoding: .utf8), "<container><date>2000-10-01</date></container>")
        let fmtDecoder = XMLDecoder()
        fmtDecoder.dateDecodingStrategy = .formatted(gmtFormatter())
        XCTAssertEqual(try fmtDecoder.decode(DateBox.self, from: fmtXML), formattedValue)
    }

    func testDataStrategyCustom() throws {
        // Exercise a non-default DataEncodingStrategy/DataDecodingStrategy: the custom closure
        // codes the Data as its raw UTF-8 text instead of the default Base64 element.
        let value = DataBox(blob: Data("lorem ipsum".utf8))

        let encoder = XMLEncoder()
        encoder.dataEncodingStrategy = .custom { data, enc in
            var container = enc.singleValueContainer()
            try container.encode(String(decoding: data, as: UTF8.self))
        }
        let encoded = try encoder.encode(value, withRootKey: "container")
        XCTAssertEqual(String(data: encoded, encoding: .utf8), "<container><blob>lorem ipsum</blob></container>")

        let decoder = XMLDecoder()
        decoder.dataDecodingStrategy = .custom { dec in
            let container = try dec.singleValueContainer()
            return Data(try container.decode(String.self).utf8)
        }
        XCTAssertEqual(try decoder.decode(DataBox.self, from: encoded), value)
    }

    func testNodeEncodingStrategyCustom() throws {
        let encoder = XMLEncoder()
        encoder.nodeEncodingStrategy = .custom { _, _ in
            { key in key.stringValue == "id" ? .attribute : .element }
        }
        let encoded = try encoder.encode(MixNode(id: 1, name: "foo"), withRootKey: "Mix")
        XCTAssertEqual(String(data: encoded, encoding: .utf8), "<Mix id=\"1\"><name>foo</name></Mix>")
    }

    func testNonConformingFloat() throws {
        let throwing = XMLEncoder()
        XCTAssertThrowsError(try throwing.encode(FloatBox(value: .infinity), withRootKey: "container"))

        let converting = XMLEncoder()
        converting.nonConformingFloatEncodingStrategy =
            .convertToString(positiveInfinity: "INF", negativeInfinity: "-INF", nan: "NaN")
        let encoded = try converting.encode(FloatBox(value: .infinity), withRootKey: "container")
        XCTAssertEqual(String(data: encoded, encoding: .utf8), "<container><value>INF</value></container>")

        let decoder = XMLDecoder()
        decoder.nonConformingFloatDecodingStrategy =
            .convertFromString(positiveInfinity: "INF", negativeInfinity: "-INF", nan: "NaN")
        let decoded = try decoder.decode(FloatBox.self, from: encoded)
        XCTAssertEqual(decoded.value, .infinity)
    }
}

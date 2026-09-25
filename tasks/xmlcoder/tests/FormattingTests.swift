// Hidden grading suite — output formatting: pretty print, escaping, CDATA, headers, doctype,
// root attributes. Public API only (`import XMLCoder`). Expected values from XMLCoder's own tests.

import XCTest
import Foundation
import XMLCoder

private struct TopContainer: Encodable {
    let nested: NestedContainer
}
private struct NestedContainer: Encodable {
    let values: [String]
}

private struct Response: Codable {
    let aResponse: String
}

private struct NewlineAttr: Codable, DynamicNodeEncoding, Equatable {
    let id: String
    static func nodeEncoding(for key: CodingKey) -> XMLEncoder.NodeEncoding { .attribute }
}

private struct CDataContainer: Codable, Equatable {
    let value: Int
    let data: String
}
private struct CData: Codable {
    let string: String
    let int: Int
    let bool: Bool
}

private struct HeaderProbe: Encodable {
    let a: Int
}

private struct DocItem: Codable, Equatable {
    let text: String
    enum CodingKeys: String, CodingKey { case text = "t" }
}

private struct Policy: Encodable, DynamicNodeEncoding {
    var name: String
    var initial: String
    enum CodingKeys: String, CodingKey { case name, initial }
    static func nodeEncoding(for key: CodingKey) -> XMLEncoder.NodeEncoding {
        switch key {
        case Policy.CodingKeys.name: return .attribute
        default: return .element
        }
    }
}

final class FormattingTests: XCTestCase {
    private let container = TopContainer(nested: NestedContainer(values: ["foor", "bar"]))

    func testPrettyPrintIndentation() throws {
        func encode(_ indentation: XMLEncoder.PrettyPrintIndentation) throws -> String {
            let encoder = XMLEncoder()
            encoder.outputFormatting = [.prettyPrinted]
            encoder.prettyPrintIndentation = indentation
            return String(data: try encoder.encode(container), encoding: .utf8)!
        }
        XCTAssertEqual(try encode(.spaces(4)), """
        <TopContainer>
            <nested>
                <values>foor</values>
                <values>bar</values>
            </nested>
        </TopContainer>
        """)
        XCTAssertEqual(try encode(.spaces(3)), """
        <TopContainer>
           <nested>
              <values>foor</values>
              <values>bar</values>
           </nested>
        </TopContainer>
        """)
        XCTAssertEqual(try encode(.tabs(2)), """
        <TopContainer>
        \t\t<nested>
        \t\t\t\t<values>foor</values>
        \t\t\t\t<values>bar</values>
        \t\t</nested>
        </TopContainer>
        """)
    }

    func testEscaping() throws {
        let defaultEncoder = XMLEncoder()
        XCTAssertEqual(String(data: try defaultEncoder.encode(Response(aResponse: " \"\"\" ")), encoding: .utf8),
                       "<Response><aResponse> &quot;&quot;&quot; </aResponse></Response>")

        let noElementEscaping = XMLEncoder()
        noElementEscaping.charactersEscapedInElements = []
        XCTAssertEqual(String(data: try noElementEscaping.encode(Response(aResponse: " \"\"\" ")), encoding: .utf8),
                       "<Response><aResponse> \"\"\" </aResponse></Response>")

        let attributeNewlineEncoded = "<NewlineAttr id=\"Got an attributed String.&#10;Will create a image.&#10;&#10;\" />"
        let value = NewlineAttr(id: "Got an attributed String.\nWill create a image.\n\n")
        let attributeEncoder = XMLEncoder()
        attributeEncoder.charactersEscapedInAttributes += [("\n", "&#10;")]
        XCTAssertEqual(String(data: try attributeEncoder.encode(value, withRootKey: "NewlineAttr"), encoding: .utf8),
                       attributeNewlineEncoded)

        let decoder = XMLDecoder()
        decoder.trimValueWhitespaces = false
        XCTAssertEqual(try decoder.decode(NewlineAttr.self, from: attributeNewlineEncoded.data(using: .utf8)!), value)
    }

    func testCDATA() throws {
        let xml = "<container><value>42</value><data><![CDATA[lorem ipsum]]></data></container>".data(using: .utf8)!
        XCTAssertEqual(try XMLDecoder().decode(CDataContainer.self, from: xml),
                       CDataContainer(value: 42, data: "lorem ipsum"))

        let encoder = XMLEncoder()
        encoder.stringEncodingStrategy = .cdata
        encoder.outputFormatting = .prettyPrinted
        let encoded = try encoder.encode(CData(string: "string", int: 123, bool: true))
        XCTAssertEqual(String(data: encoded, encoding: .utf8), """
        <CData>
            <string><![CDATA[string]]></string>
            <int>123</int>
            <bool>true</bool>
        </CData>
        """)
    }

    func testHeaderVariants() throws {
        func encode(_ header: XMLHeader) throws -> String {
            String(data: try XMLEncoder().encode(HeaderProbe(a: 1), withRootKey: "probe", header: header), encoding: .utf8)!
        }
        XCTAssertEqual(try encode(XMLHeader(version: 1.0)),
                       "<?xml version=\"1.0\"?>\n<probe><a>1</a></probe>")
        XCTAssertEqual(try encode(XMLHeader(version: 1.0, encoding: "UTF-8")),
                       "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<probe><a>1</a></probe>")
        XCTAssertEqual(try encode(XMLHeader(version: 1.0, encoding: "UTF-8", standalone: "yes")),
                       "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<probe><a>1</a></probe>")
    }

    func testDoctype() throws {
        let systemXML = "<!DOCTYPE si SYSTEM \"http://example.com/myService_v1.dtd\">\n<si><t>blah</t></si>".data(using: .utf8)!
        let publicXML = "<!DOCTYPE si PUBLIC \"-//Domain//DTD MyService v1//EN\" \"http://example.com/myService_v1.dtd\">\n<si><t>blah</t></si>".data(using: .utf8)!

        let item = try XMLDecoder().decode(DocItem.self, from: systemXML)
        XCTAssertEqual(item.text, "blah")

        let encoder = XMLEncoder()
        XCTAssertEqual(try encoder.encode(item, withRootKey: "si",
                                          doctype: .system(rootElement: "si",
                                                           dtdLocation: "http://example.com/myService_v1.dtd")),
                       systemXML)
        XCTAssertEqual(try encoder.encode(item, withRootKey: "si",
                                          doctype: .public(rootElement: "si",
                                                           dtdName: "-//Domain//DTD MyService v1//EN",
                                                           dtdLocation: "http://example.com/myService_v1.dtd")),
                       publicXML)
    }

    func testRootAttributes() throws {
        let encoder = XMLEncoder()
        encoder.keyEncodingStrategy = .lowercased
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(Policy(name: "test", initial: "extra root attributes"),
                                      rootAttributes: [
                                          "xmlns": "http://www.nrf-arts.org/IXRetail/namespace",
                                          "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
                                          "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                                      ])
        XCTAssertEqual(String(data: data, encoding: .utf8), """
        <policy name="test" xmlns="http://www.nrf-arts.org/IXRetail/namespace" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <initial>extra root attributes</initial>
        </policy>
        """)
    }
}

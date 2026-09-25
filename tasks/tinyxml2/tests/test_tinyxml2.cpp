// tinyxml2 WRG task — hidden test suite (gtest version).
//
// One TEST per behaviour, ported 1:1 from a prior pytest+subprocess+g++
// driver (2026-06-25). Where the pytest version compiled a per-test driver
// and asserted on its stdout, this version drives the tinyxml2 API directly
// via gtest assertions — no subprocess, no string parsing.
//
// The grader compiles this single file against the agent's installed
// tinyxml2 header + library + gtest + pthread, runs the resulting binary
// with --gtest_output=xml, and converts the JUnit XML to CTRF JSON.
//
// Bind side-effecting Query*/Get* results to a local BEFORE consuming them
// in the same expression — C++ argument evaluation order is unspecified and
// the original pytest-era drivers relied on that discipline.

#include <gtest/gtest.h>
#include <tinyxml2.h>

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <string>

using namespace tinyxml2;


// --- 1. Parse + traverse + text retrieval --------------------------------
TEST(TinyXml2ParseTraverse, NavigatesElementsAndReadsText) {
    const char* xml =
        "<library>"
        "<book id='1'><title>The Hobbit</title><author>Tolkien</author></book>"
        "<book id='2'><title>Dune</title><author>Herbert</author></book>"
        "<book id='3'><title>Foundation</title><author>Asimov</author></book>"
        "</library>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);

    XMLElement* root = doc.RootElement();
    ASSERT_NE(root, nullptr);
    EXPECT_STREQ(root->Name(), "library");

    int count = 0;
    XMLElement* book = root->FirstChildElement("book");
    ASSERT_NE(book, nullptr);
    XMLElement* firstBook = book;

    // Iterate <book> children: titles/authors in document order.
    const char* expected_titles[] = {"The Hobbit", "Dune", "Foundation"};
    const char* expected_authors[] = {"Tolkien", "Herbert", "Asimov"};
    while (book) {
        const XMLElement* title  = book->FirstChildElement("title");
        const XMLElement* author = book->FirstChildElement("author");
        ASSERT_NE(title, nullptr);
        ASSERT_NE(author, nullptr);
        EXPECT_STREQ(title->GetText(),  expected_titles[count]);
        EXPECT_STREQ(author->GetText(), expected_authors[count]);
        ++count;
        book = book->NextSiblingElement("book");
    }
    EXPECT_EQ(count, 3);
}

TEST(TinyXml2ParseTraverse, GetTextReturnsNullWhenFirstChildIsNotText) {
    // <book>'s first child is <title> (an element), not text — GetText must
    // return null on that case.
    const char* xml =
        "<library>"
        "<book id='1'><title>The Hobbit</title><author>Tolkien</author></book>"
        "</library>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* firstBook = doc.RootElement()->FirstChildElement("book");
    ASSERT_NE(firstBook, nullptr);
    EXPECT_EQ(firstBook->GetText(), nullptr);
}


// --- 2. Attribute typed access + Query* error codes -----------------------
TEST(TinyXml2AttributeTyped, ConvenienceAccessorsAndDefaults) {
    const char* xml = "<doc count='42' ratio='3.14' enabled='true' label='hello'/>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* e = doc.RootElement();
    ASSERT_NE(e, nullptr);

    EXPECT_EQ(e->IntAttribute("count"),       42);
    EXPECT_DOUBLE_EQ(e->DoubleAttribute("ratio"), 3.14);
    EXPECT_TRUE (e->BoolAttribute("enabled"));
    EXPECT_STREQ(e->Attribute("label"),       "hello");

    // Defaults on missing attribute.
    EXPECT_EQ(e->IntAttribute("missing", 99), 99);
    EXPECT_EQ(e->Attribute("missing"),        nullptr);
}

TEST(TinyXml2AttributeTyped, QueryIntAttributeErrorCodes) {
    const char* xml = "<doc count='42' label='hello'/>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* e = doc.RootElement();
    ASSERT_NE(e, nullptr);

    // Non-numeric attribute → XML_WRONG_ATTRIBUTE_TYPE.
    int v = 0;
    XMLError wrongTypeErr = e->QueryIntAttribute("label", &v);
    EXPECT_EQ(wrongTypeErr, XML_WRONG_ATTRIBUTE_TYPE);

    // Missing attribute → XML_NO_ATTRIBUTE.
    XMLError missingErr = e->QueryIntAttribute("missing", &v);
    EXPECT_EQ(missingErr, XML_NO_ATTRIBUTE);

    // Successful query writes value and returns XML_SUCCESS.
    int n = -1;
    XMLError okErr = e->QueryIntAttribute("count", &n);
    EXPECT_EQ(okErr, XML_SUCCESS);
    EXPECT_EQ(n, 42);
}

TEST(TinyXml2AttributeTyped, AttributeNameValueMatchForm) {
    const char* xml = "<doc label='hello'/>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* e = doc.RootElement();
    ASSERT_NE(e, nullptr);

    // Attribute(name, value) returns a non-null pointer iff value matches.
    EXPECT_NE(e->Attribute("label", "hello"), nullptr);
    EXPECT_EQ(e->Attribute("label", "world"), nullptr);
}


// --- 3. Attribute iteration order and deletion ----------------------------
TEST(TinyXml2AttributeOrder, IterationFollowsDocumentOrder) {
    const char* xml = "<e a='1' b='2' c='3' d='4'/>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* e = doc.RootElement();
    ASSERT_NE(e, nullptr);

    const char* expected_names[]  = {"a", "b", "c", "d"};
    const char* expected_values[] = {"1", "2", "3", "4"};
    int i = 0;
    for (const XMLAttribute* a = e->FirstAttribute(); a; a = a->Next()) {
        ASSERT_LT(i, 4);
        EXPECT_STREQ(a->Name(),  expected_names[i]);
        EXPECT_STREQ(a->Value(), expected_values[i]);
        ++i;
    }
    EXPECT_EQ(i, 4);
}

TEST(TinyXml2AttributeOrder, DeleteAttributePreservesRemainingOrder) {
    const char* xml = "<e a='1' b='2' c='3' d='4'/>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* e = doc.RootElement();
    ASSERT_NE(e, nullptr);

    // Delete middle attribute; remaining order preserved.
    e->DeleteAttribute("b");
    const char* expected1[] = {"a", "c", "d"};
    int i = 0;
    for (const XMLAttribute* a = e->FirstAttribute(); a; a = a->Next()) {
        ASSERT_LT(i, 3);
        EXPECT_STREQ(a->Name(), expected1[i]);
        ++i;
    }
    EXPECT_EQ(i, 3);

    // Delete first and last; one attribute remains.
    e->DeleteAttribute("a");
    e->DeleteAttribute("d");
    int j = 0;
    for (const XMLAttribute* a = e->FirstAttribute(); a; a = a->Next()) {
        ASSERT_LT(j, 1);
        EXPECT_STREQ(a->Name(),  "c");
        EXPECT_STREQ(a->Value(), "3");
        ++j;
    }
    EXPECT_EQ(j, 1);

    // Delete all → FirstAttribute returns null.
    e->DeleteAttribute("c");
    EXPECT_EQ(e->FirstAttribute(), nullptr);
}


// --- 4. Programmatic DOM construction with Insert* ------------------------
TEST(TinyXml2DomConstruction, BuildWithNewAndInsertSerializesCompact) {
    XMLDocument doc;

    XMLElement* root = doc.NewElement("config");
    doc.InsertEndChild(root);

    XMLElement* host = doc.NewElement("host");
    host->SetAttribute("name", "primary");
    host->SetAttribute("port", 8080);
    root->InsertEndChild(host);

    XMLElement* logging = doc.NewElement("logging");
    logging->SetText("verbose");
    root->InsertEndChild(logging);

    // Insert a comment as the first child (before <host>).
    XMLComment* c = doc.NewComment("server configuration");
    root->InsertFirstChild(c);

    // Insert a new element between <host> and <logging>.
    XMLElement* timeout = doc.NewElement("timeout");
    timeout->SetText(30);
    root->InsertAfterChild(host, timeout);

    // Serialize compactly and string-compare.
    XMLPrinter printer(nullptr, /*compact=*/true);
    doc.Print(&printer);
    const std::string expected =
        "<config>"
        "<!--server configuration-->"
        "<host name=\"primary\" port=\"8080\"/>"
        "<timeout>30</timeout>"
        "<logging>verbose</logging>"
        "</config>";
    EXPECT_EQ(std::string(printer.CStr()), expected);
}


// --- 5. SaveFile/LoadFile round-trip with declaration and BOM -------------
TEST(TinyXml2FileRoundTrip, SaveLoadPreservesDeclarationBomAttributesText) {
    namespace fs = std::filesystem;
    fs::path tmp = fs::temp_directory_path() / "tinyxml2_roundtrip.xml";
    const std::string path = tmp.string();

    // Write.
    {
        XMLDocument doc;
        doc.InsertEndChild(doc.NewDeclaration());
        doc.SetBOM(true);
        XMLElement* root = doc.NewElement("data");
        root->SetAttribute("version", 2);
        XMLElement* item = doc.NewElement("item");
        item->SetText("payload");
        root->InsertEndChild(item);
        doc.InsertEndChild(root);
        ASSERT_EQ(doc.SaveFile(path.c_str()), XML_SUCCESS);
    }

    // Read back and inspect.
    {
        XMLDocument doc;
        ASSERT_EQ(doc.LoadFile(path.c_str()), XML_SUCCESS);

        EXPECT_TRUE(doc.HasBOM());

        // First child must be the XML declaration.
        XMLNode* first = doc.FirstChild();
        ASSERT_NE(first, nullptr);
        EXPECT_NE(first->ToDeclaration(), nullptr);

        XMLElement* root = doc.RootElement();
        ASSERT_NE(root, nullptr);
        EXPECT_STREQ(root->Name(), "data");
        EXPECT_EQ(root->IntAttribute("version"), 2);

        XMLElement* item = root->FirstChildElement("item");
        ASSERT_NE(item, nullptr);
        EXPECT_STREQ(item->GetText(), "payload");
    }

    // Clean up the file so re-runs in the same FS don't leak.
    std::error_code ec;
    fs::remove(tmp, ec);
}


// --- 6. XMLPrinter serializes a doc-built DOM to parseable output ---------
TEST(TinyXml2Printer, PrintProducesParseableOutput) {
    // Build the same structure through the DOM API, serialize it via
    // doc.Print(&printer), then parse the output back and verify.
    XMLDocument out;
    XMLElement* resp = out.NewElement("response");
    resp->SetAttribute("status", "ok");
    resp->SetAttribute("code",   200);
    resp->SetAttribute("cached", true);

    XMLElement* body = out.NewElement("body");
    body->SetText("payload-data");
    resp->InsertEndChild(body);

    XMLComment* endComment = out.NewComment("end of response");
    resp->InsertEndChild(endComment);

    out.InsertEndChild(resp);

    XMLPrinter printer;
    out.Print(&printer);

    // Parse the serialized output back and verify structure semantically.
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(printer.CStr()), XML_SUCCESS);

    XMLElement* respParsed = doc.RootElement();
    ASSERT_NE(respParsed, nullptr);
    EXPECT_STREQ(respParsed->Name(), "response");
    EXPECT_STREQ(respParsed->Attribute("status"), "ok");
    EXPECT_EQ(respParsed->IntAttribute("code"), 200);
    EXPECT_TRUE(respParsed->BoolAttribute("cached"));

    XMLElement* bodyParsed = respParsed->FirstChildElement("body");
    ASSERT_NE(bodyParsed, nullptr);
    EXPECT_STREQ(bodyParsed->GetText(), "payload-data");

    // The comment round-trips as a sibling of <body> inside <response>.
    // The default (non-compact) printer inserts indentation/newlines between
    // sibling nodes; whether the parser materialises that inter-node
    // whitespace as its own XMLText node is left open by the spec, so skip
    // any whitespace-only text node when locating the comment.
    auto isWhitespaceOnly = [](const XMLNode* n) {
        const XMLText* t = n->ToText();
        if (t == nullptr) return false;
        const char* v = t->Value();
        if (v == nullptr) return true;
        for (const char* p = v; *p; ++p) {
            if (*p != ' ' && *p != '\t' && *p != '\n' && *p != '\r') return false;
        }
        return true;
    };
    const XMLNode* c = bodyParsed->NextSibling();
    while (c != nullptr && isWhitespaceOnly(c)) {
        c = c->NextSibling();
    }
    ASSERT_NE(c, nullptr);
    ASSERT_NE(c->ToComment(), nullptr);
    EXPECT_STREQ(c->Value(), "end of response");
}


// --- 7. Parse-error reporting: id, name, line number ----------------------
TEST(TinyXml2ParseErrors, MismatchedClosingTagReportsLineAndName) {
    // Mismatched closing tag on line 2 (1-based; the offending </wrong> sits
    // on the source line after the <root>\n line break).
    const char* xml = "<root>\n  <child>text</wrong>\n</root>";
    XMLDocument doc;
    XMLError err = doc.Parse(xml);
    EXPECT_EQ(err, XML_ERROR_MISMATCHED_ELEMENT);
    EXPECT_EQ(doc.ErrorLineNum(), 2);
    EXPECT_TRUE(doc.Error());
    EXPECT_STREQ(doc.ErrorName(), "XML_ERROR_MISMATCHED_ELEMENT");
}

TEST(TinyXml2ParseErrors, EmptyInputYieldsEmptyDocumentError) {
    XMLDocument doc;
    XMLError err = doc.Parse("");
    EXPECT_EQ(err, XML_ERROR_EMPTY_DOCUMENT);
    EXPECT_STREQ(doc.ErrorName(), "XML_ERROR_EMPTY_DOCUMENT");
}

TEST(TinyXml2ParseErrors, MalformedAttributeReportsParsingAttributeError) {
    // An unquoted attribute value is malformed. The parser stops on the
    // offending attribute (line 2, 1-based) and reports the error via the
    // Parse() return value, ErrorID(), Error(), and ErrorLineNum().
    const char* xml = "<root>\n  <child attr=bad/>\n</root>";
    XMLDocument doc;
    XMLError err = doc.Parse(xml);
    EXPECT_EQ(err, XML_ERROR_PARSING_ATTRIBUTE);
    EXPECT_EQ(doc.ErrorID(), XML_ERROR_PARSING_ATTRIBUTE);
    EXPECT_TRUE(doc.Error());
    EXPECT_EQ(doc.ErrorLineNum(), 2);
}

TEST(TinyXml2ParseErrors, SuccessfulParseClearsErrorState) {
    XMLDocument doc;
    ASSERT_EQ(doc.Parse("<ok/>"), XML_SUCCESS);
    EXPECT_FALSE(doc.Error());
    EXPECT_EQ(static_cast<int>(doc.ErrorID()), 0);
}


// --- 8. CDATA and entity translation --------------------------------------
TEST(TinyXml2Entities, CdataPreservesRawMarkupCharacters) {
    const char* xml = "<root><![CDATA[a < b && c > d]]></root>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    const XMLText* t = doc.RootElement()->FirstChild()->ToText();
    ASSERT_NE(t, nullptr);
    EXPECT_STREQ(t->Value(), "a < b && c > d");
    EXPECT_TRUE(t->CData());
}

TEST(TinyXml2Entities, NamedEntitiesDecodeInAttributesAndText) {
    const char* xml = "<msg s='a &lt; b &amp; c &quot;q&quot;'>X &amp; Y</msg>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    EXPECT_STREQ(doc.RootElement()->Attribute("s"), "a < b & c \"q\"");
    EXPECT_STREQ(doc.RootElement()->GetText(),      "X & Y");
}

TEST(TinyXml2Entities, NumericAndHexCharacterReferencesDecode) {
    // CVE-2024-50615 regression — both decimal and hex char refs decode.
    const char* xml = "<n a='X&#65;Y' b='X&#x42;Y'/>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    EXPECT_STREQ(doc.RootElement()->Attribute("a"), "XAY");
    EXPECT_STREQ(doc.RootElement()->Attribute("b"), "XBY");
}

TEST(TinyXml2Entities, ParsedEntitiesReEncodeOnPrint) {
    const char* xml = "<msg s='a &lt; b &amp; c &quot;q&quot;'>X &amp; Y</msg>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLPrinter p(nullptr, /*compact=*/true);
    doc.Print(&p);
    EXPECT_EQ(std::string(p.CStr()),
              std::string("<msg s=\"a &lt; b &amp; c &quot;q&quot;\">X &amp; Y</msg>"));
}


// --- 9. Typed text queries + SetText overloads ----------------------------
TEST(TinyXml2TypedText, QueryIntDoubleBoolTextSucceeds) {
    const char* xml =
        "<root>"
        "<i>42</i>"
        "<d>3.14</d>"
        "<b>true</b>"
        "</root>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* root = doc.RootElement();

    int iv = 0;
    XMLError ei = root->FirstChildElement("i")->QueryIntText(&iv);
    EXPECT_EQ(ei, XML_SUCCESS);
    EXPECT_EQ(iv, 42);

    double dv = 0;
    XMLError ed = root->FirstChildElement("d")->QueryDoubleText(&dv);
    EXPECT_EQ(ed, XML_SUCCESS);
    EXPECT_DOUBLE_EQ(dv, 3.14);

    bool bv = false;
    XMLError eb = root->FirstChildElement("b")->QueryBoolText(&bv);
    EXPECT_EQ(eb, XML_SUCCESS);
    EXPECT_TRUE(bv);
}

TEST(TinyXml2TypedText, QueryIntTextErrorCodesForBadAndEmpty) {
    const char* xml =
        "<root>"
        "<bad>not-a-number</bad>"
        "<empty/>"
        "</root>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* root = doc.RootElement();

    int badv = -1;
    XMLError badErr = root->FirstChildElement("bad")->QueryIntText(&badv);
    EXPECT_EQ(badErr, XML_CAN_NOT_CONVERT_TEXT);

    int emptyv = -1;
    XMLError emptyErr = root->FirstChildElement("empty")->QueryIntText(&emptyv);
    EXPECT_EQ(emptyErr, XML_NO_TEXT_NODE);
}

TEST(TinyXml2TypedText, SetTextOverloadsRoundTripThroughGetText) {
    XMLDocument out;
    XMLElement* e1 = out.NewElement("x"); e1->SetText(7);    out.InsertEndChild(e1);
    XMLElement* e2 = out.NewElement("y"); e2->SetText(1.5);  out.InsertEndChild(e2);
    XMLElement* e3 = out.NewElement("z"); e3->SetText(true); out.InsertEndChild(e3);

    EXPECT_STREQ(e1->GetText(), "7");
    EXPECT_STREQ(e2->GetText(), "1.5");
    EXPECT_STREQ(e3->GetText(), "true");
}


// --- 10. XMLHandle null-safe navigation -----------------------------------
TEST(TinyXml2Handle, NullSafeNavigationFindsDeepLeafAndAbsorbsMissing) {
    const char* xml = "<a><b><c name='deep'/></b></a>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);

    // Successful navigation: a -> b -> c.
    XMLElement* found =
        XMLHandle(doc)
            .FirstChildElement("a")
            .FirstChildElement("b")
            .FirstChildElement("c")
            .ToElement();
    ASSERT_NE(found, nullptr);
    EXPECT_STREQ(found->Attribute("name"), "deep");

    // Missing intermediate step: handle absorbs the null silently.
    XMLElement* missing =
        XMLHandle(doc)
            .FirstChildElement("a")
            .FirstChildElement("zzz")
            .FirstChildElement("c")
            .ToElement();
    EXPECT_EQ(missing, nullptr);

    // Missing leaf only.
    XMLElement* leaf =
        XMLHandle(doc)
            .FirstChildElement("a")
            .FirstChildElement("b")
            .FirstChildElement("xxx")
            .ToElement();
    EXPECT_EQ(leaf, nullptr);
}


// --- 11. XMLVisitor + Accept walks the whole tree in document order -------
TEST(TinyXml2Visitor, AcceptDispatchesEnterExitForDocumentElementsAndText) {
    struct Trace : public XMLVisitor {
        std::string log;
        bool VisitEnter(const XMLDocument&) override { log += "D{"; return true; }
        bool VisitExit (const XMLDocument&) override { log += "}D"; return true; }
        bool VisitEnter(const XMLElement& e, const XMLAttribute*) override {
            log += "E("; log += e.Name(); log += "){";
            return true;
        }
        bool VisitExit (const XMLElement& e) override {
            log += "}E("; log += e.Name(); log += ")";
            return true;
        }
        bool Visit(const XMLText& t) override {
            log += "T("; log += t.Value(); log += ")";
            return true;
        }
        bool Visit(const XMLComment& c) override {
            log += "C("; log += c.Value(); log += ")";
            return true;
        }
    };

    const char* xml = "<root><a>hi</a><!--mid--><b/></root>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    Trace t;
    EXPECT_TRUE(doc.Accept(&t));
    EXPECT_EQ(t.log,
              std::string("D{E(root){E(a){T(hi)}E(a)C(mid)E(b){}E(b)}E(root)}D"));
}


// --- 12. DeepClone copies a subtree into another document -----------------
TEST(TinyXml2DeepClone, ClonedSubtreeOutlivesSourceDocument) {
    XMLDocument dst;
    // Clone the subtree from a source doc that goes out of scope before we
    // serialize dst — verifies independent ownership.
    {
        const char* xml = "<src><kept attr='v'><deep/>txt</kept></src>";
        XMLDocument src;
        ASSERT_EQ(src.Parse(xml), XML_SUCCESS);
        XMLElement* kept = src.RootElement()->FirstChildElement("kept");
        ASSERT_NE(kept, nullptr);
        XMLNode* cloned = kept->DeepClone(&dst);
        dst.InsertFirstChild(cloned);
    }
    // Source is destroyed. Inspect dst.
    XMLPrinter p(nullptr, /*compact=*/true);
    dst.Print(&p);
    EXPECT_EQ(std::string(p.CStr()),
              std::string("<kept attr=\"v\"><deep/>txt</kept>"));

    XMLElement* root = dst.RootElement();
    ASSERT_NE(root, nullptr);
    EXPECT_STREQ(root->Name(),           "kept");
    EXPECT_STREQ(root->Attribute("attr"), "v");
    EXPECT_NE(root->FirstChildElement("deep"), nullptr);
}


// --- 13. UTF-8 round-trips through Parse + Print --------------------------
TEST(TinyXml2Utf8, MultiByteAttributeAndTextRoundTripByteForByte) {
    // lang = "ру" (Russian "ru" cyrillic), text = "Привет α" (Privet + alpha)
    const char* xml =
        "<doc lang=\"\xD1\x80\xD1\x83\">"
        "\xD0\x9F\xD1\x80\xD0\xB8\xD0\xB2\xD0\xB5\xD1\x82 \xCE\xB1"
        "</doc>";
    XMLDocument d;
    ASSERT_EQ(d.Parse(xml), XML_SUCCESS);

    // Attribute and text content preserved byte-for-byte.
    EXPECT_STREQ(d.RootElement()->Attribute("lang"), "\xD1\x80\xD1\x83");
    EXPECT_STREQ(d.RootElement()->GetText(),
                 "\xD0\x9F\xD1\x80\xD0\xB8\xD0\xB2\xD0\xB5\xD1\x82 \xCE\xB1");

    // Round-trip via Print produces the same bytes (compact mode for stable comparison).
    XMLPrinter p(nullptr, /*compact=*/true);
    d.Print(&p);
    // The printer wraps the value in double quotes regardless of the input
    // quote style — match that here.
    const std::string expected =
        "<doc lang=\"\xD1\x80\xD1\x83\">"
        "\xD0\x9F\xD1\x80\xD0\xB8\xD0\xB2\xD0\xB5\xD1\x82 \xCE\xB1"
        "</doc>";
    EXPECT_EQ(std::string(p.CStr()), expected);
}


// --- 14. Element depth limit rejects pathological nesting -----------------
TEST(TinyXml2DepthLimit, WithinLimitParsesSuccessfully) {
    // 100-deep nesting is well within the 500-level cap.
    std::string okXml;
    for (int i = 0; i < 100; ++i) okXml += "<a>";
    for (int i = 0; i < 100; ++i) okXml += "</a>";
    XMLDocument okDoc;
    EXPECT_EQ(okDoc.Parse(okXml.c_str()), XML_SUCCESS);
}

TEST(TinyXml2DepthLimit, OverLimitYieldsElementDepthExceeded) {
    // 600 nested elements > the 500-level cap.
    std::string deepXml;
    for (int i = 0; i < 600; ++i) deepXml += "<a>";
    for (int i = 0; i < 600; ++i) deepXml += "</a>";
    XMLDocument badDoc;
    XMLError badErr = badDoc.Parse(deepXml.c_str());
    EXPECT_EQ(badErr, XML_ELEMENT_DEPTH_EXCEEDED);
    EXPECT_TRUE(badDoc.Error());
}


// --- 15. Node mutation: delete + move subtree across parents --------------
TEST(TinyXml2Mutation, DeleteChildAndMoveSubtreePreserveSiblingOrder) {
    const char* xml =
        "<root>"
        "<a><x/><y/><z/></a>"
        "<b><keep/></b>"
        "</root>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);

    XMLElement* root = doc.RootElement();
    XMLElement* a = root->FirstChildElement("a");
    XMLElement* b = root->FirstChildElement("b");
    ASSERT_NE(a, nullptr);
    ASSERT_NE(b, nullptr);

    // Delete one named child of <a>.
    XMLElement* y = a->FirstChildElement("y");
    ASSERT_NE(y, nullptr);
    a->DeleteChild(y);

    // Move <keep> from <b> to be a child of <a>.
    XMLElement* keep = b->FirstChildElement("keep");
    ASSERT_NE(keep, nullptr);
    a->InsertEndChild(keep);

    // Delete all remaining children of <b>.
    b->DeleteChildren();

    EXPECT_TRUE(b->NoChildren());

    XMLPrinter p(nullptr, /*compact=*/true);
    doc.Print(&p);
    EXPECT_EQ(std::string(p.CStr()),
              std::string("<root><a><x/><z/><keep/></a><b/></root>"));
}


// --- 16. XMLPrinter compact mode boundary checks --------------------------
TEST(TinyXml2PrinterCompact, CStrHasNoTrailingWhitespaceAfterRoot) {
    // Compact-mode output must end at the root's close tag with no
    // trailing '\n' / indent. Spec: "compact writes without indentation
    // or newlines between tags".
    XMLDocument doc;
    XMLElement* root = doc.NewElement("root");
    root->SetAttribute("k", "v");
    doc.InsertEndChild(root);

    XMLPrinter p(nullptr, /*compact=*/true);
    doc.Print(&p);
    const std::string out = p.CStr();
    ASSERT_FALSE(out.empty());
    EXPECT_EQ(out.back(), '>')
        << "compact output must end at root close tag; got: " << out;
    EXPECT_EQ(out.find('\n'), std::string::npos)
        << "compact output must contain no newlines; got: " << out;
}


// --- 17. Sibling walk by name (backward) ----------------------------------
TEST(TinyXml2SiblingWalk, LastAndPreviousSiblingByName) {
    // LastChildElement(name) and PreviousSiblingElement(name) walk
    // the sibling chain backward filtering by tag. Agents commonly
    // implement forward walk (FirstChild/NextSibling) but stub the
    // backward variants.
    const char* xml =
        "<root>"
        "<a id='1'/><b/><a id='2'/><c/><a id='3'/>"
        "</root>";
    XMLDocument doc;
    ASSERT_EQ(doc.Parse(xml), XML_SUCCESS);
    XMLElement* root = doc.RootElement();
    ASSERT_NE(root, nullptr);

    const XMLElement* lastA = root->LastChildElement("a");
    ASSERT_NE(lastA, nullptr);
    EXPECT_STREQ(lastA->Attribute("id"), "3");

    const XMLElement* prev1 = lastA->PreviousSiblingElement("a");
    ASSERT_NE(prev1, nullptr);
    EXPECT_STREQ(prev1->Attribute("id"), "2");

    const XMLElement* prev2 = prev1->PreviousSiblingElement("a");
    ASSERT_NE(prev2, nullptr);
    EXPECT_STREQ(prev2->Attribute("id"), "1");

    const XMLElement* prev3 = prev2->PreviousSiblingElement("a");
    EXPECT_EQ(prev3, nullptr)
        << "no earlier <a> exists; PreviousSiblingElement(name) must return null";
}


// --- 18. XMLPrinter FILE* mode --------------------------------------------
TEST(TinyXml2PrinterFile, WritesDocToFilePointer) {
    // XMLPrinter(FILE*, compact) writes output directly to the FILE* as
    // doc.Print(&printer) drives the visitor. Verify by reading the file
    // back through XMLDocument and checking the parsed structure.
    namespace fs = std::filesystem;
    fs::path tmp = fs::temp_directory_path() / "tinyxml2_printer_file.xml";
    const std::string path = tmp.string();

    {
        XMLDocument out;
        XMLElement* root = out.NewElement("data");
        root->SetAttribute("id", 7);
        root->SetText("body");
        out.InsertEndChild(root);

        FILE* fp = std::fopen(path.c_str(), "wb");
        ASSERT_NE(fp, nullptr);
        {
            XMLPrinter p(fp, /*compact=*/true);
            out.Print(&p);
        }
        std::fclose(fp);
    }

    // Read the on-disk output back through the parser and verify structure.
    XMLDocument doc;
    ASSERT_EQ(doc.LoadFile(path.c_str()), XML_SUCCESS)
        << "XMLPrinter(FILE*) must write parseable XML to disk";
    XMLElement* root = doc.RootElement();
    ASSERT_NE(root, nullptr);
    EXPECT_STREQ(root->Name(), "data");
    EXPECT_EQ(root->IntAttribute("id"), 7);
    EXPECT_STREQ(root->GetText(), "body");

    std::error_code ec;
    fs::remove(tmp, ec);
}

//
// Hidden grading suite for the `plot` WRG task -- HTML Component (SwiftUI-like) layer.
//
// Exercises the `Component` protocol, the `@ComponentBuilder` result builder, component
// modifiers (class/id/style/data/directionality/accessibility), the built-in component library
// (Div, List, Table, Form, Text, ...), Node<->Component interoperability, and the environment
// propagation API. Driven entirely through the public component DSL + `render()`.
//

import XCTest
import Plot

final class ComponentFormsAndMediaTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Higher-level form and media components, whose initialisers wrap several elements and
    /// attributes behind a single call (Form/Label/TextField/TextArea/Input/SubmitButton,
    /// IFrame, Image, AudioPlayer).
    func testComponentFormsAndMedia() {
        let form = Form(
            url: "url.com",
            method: .post,
            content: {
                FieldSet {
                    Label("Username") {
                        TextField(name: "username", isRequired: true).autoFocused().autoComplete(false)
                    }
                    Label("Password") {
                        Input(type: .password, name: "password").class("password-input")
                    }
                    .class("password-label")
                }
                TextArea(text: "Enter a description", name: "description",
                         numberOfRows: 3, numberOfColumns: 2)
                SubmitButton("Submit")
            }
        )
        .render()

        XCTAssertEqual(form, """
        <form action="url.com" method="post">\
        <fieldset>\
        <label>Username<input type="text" name="username" required autofocus autocomplete="off"/></label>\
        <label class="password-label">Password<input type="password" name="password" class="password-input"/></label>\
        </fieldset>\
        <textarea name="description" rows="3" cols="2">Enter a description</textarea>\
        <input type="submit" value="Submit"/>\
        </form>
        """)

        XCTAssertEqual(
            IFrame(url: "url.com", addBorder: false, allowFullScreen: true,
                   enabledFeatureNames: ["gyroscope"]).render(),
            #"<iframe src="url.com" frameborder="0" allowfullscreen allow="gyroscope"></iframe>"#
        )

        XCTAssertEqual(Image(url: "image.png", description: "My image").render(),
                       #"<img src="image.png" alt="My image"/>"#)
        XCTAssertEqual(Image("image.png").render(), #"<img src="image.png"/>"#)

        let audio = HTML {
            AudioPlayer(source: .mp3(at: "a.mp3"), showControls: false)
            AudioPlayer(source: .wav(at: "b.wav"), showControls: true)
        }
        // AudioPlayer auto-generates its <source>, whose two independent attributes (type, src)
        // have no spec-pinned relative order; accept either ordering while still requiring the
        // <audio> wrapper, the controls flag, and a self-closed <source> with the right type/src.
        let audioRendered = audio.render()
        let audioTypeFirst = "<!DOCTYPE html><html><body>"
            + #"<audio><source type="audio/mpeg" src="a.mp3"/></audio>"#
            + #"<audio controls><source type="audio/wav" src="b.wav"/></audio>"#
            + "</body></html>"
        let audioSrcFirst = "<!DOCTYPE html><html><body>"
            + #"<audio><source src="a.mp3" type="audio/mpeg"/></audio>"#
            + #"<audio controls><source src="b.wav" type="audio/wav"/></audio>"#
            + "</body></html>"
        XCTAssertTrue(audioRendered == audioTypeFirst || audioRendered == audioSrcFirst,
                      "Unexpected AudioPlayer rendering: \(audioRendered)")
    }
}

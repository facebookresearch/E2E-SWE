"""
Test suite for remi — a pure-Python GUI library that renders widgets as HTML.

Tests exercise the public API through realistic user workflows: building
widgets, nesting them in containers, registering events, styling with CSS,
and verifying the generated HTML (via widget.repr()). The element id is the
Python object id (non-deterministic), so tests assert on tag type, class,
style, attributes, content, structure, and — for event/JS handlers — the
exact JS built using the widget's own .identifier.

Tests are consolidated by behavioral area: each test builds realistic widgets
and asserts the full contract for that area, failing as a unit if any part of
the contract is wrong.
"""

from html.parser import HTMLParser
from unittest import TestCase

import remi
import remi.gui as gui


class _RootParser(HTMLParser):
    """Captures the first (outermost) start tag and its attributes."""
    def __init__(self):
        super().__init__()
        self.tag = None
        self.attrs = None

    def handle_starttag(self, tag, attrs):
        if self.tag is None:
            self.tag = tag
            self.attrs = dict(attrs)


def root(widget):
    p = _RootParser()
    p.feed(widget.repr())
    return p.tag, p.attrs


def style_dict(style_str):
    out = {}
    for part in (style_str or "").split(";"):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition(":")
        out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------------------
# 1. Widget fundamentals
# ---------------------------------------------------------------------------

class TestWidgetFundamentals(TestCase):
    """Base Widget renders as <div> with class=Python class name, id from
    .identifier, inline style from the style dict; CSS setters, set_size,
    and add/remove_class work."""

    def test_structure_style_and_classes(self):
        w = gui.Widget()
        tag, attrs = root(w)
        self.assertEqual("div", tag)
        self.assertEqual("Widget", attrs["class"])
        self.assertEqual(w.identifier, attrs["id"])

        w.set_size(100, 50)
        w.style["color"] = "blue"
        w.css_background_color = "red"
        sd = style_dict(root(w)[1]["style"])
        self.assertEqual("100px", sd["width"])
        self.assertEqual("50px", sd["height"])
        self.assertEqual("blue", sd["color"])
        self.assertEqual("red", sd["background-color"])

        w.add_class("alpha")
        self.assertIn("alpha", w.attributes["class"].split(" "))
        w.remove_class("alpha")
        self.assertNotIn("alpha", w.attributes["class"].split(" "))


# ---------------------------------------------------------------------------
# 2. Text widgets — Button, Label
# ---------------------------------------------------------------------------

class TestTextWidgets(TestCase):
    """Button and Label render correct tags/content, set_text updates a Label,
    and both reject non-string text."""

    def test_button_and_label(self):
        tag, attrs = root(gui.Button("Click me"))
        self.assertEqual("button", tag)
        self.assertEqual("Button", attrs["class"])
        self.assertIn("Click me", gui.Button("Click me").repr())

        tag, attrs = root(gui.Label("hi"))
        self.assertEqual("p", tag)
        self.assertEqual("Label", attrs["class"])
        lbl = gui.Label("orig")
        lbl.set_text("updated")
        self.assertIn("updated", lbl.repr())
        self.assertNotIn("orig", lbl.repr())

        for bad in [{}, [], 123, (4, 5)]:
            with self.assertRaises(Exception):
                gui.Button(bad)
            with self.assertRaises(Exception):
                gui.Label(bad)


# ---------------------------------------------------------------------------
# 3. TextInput — special attributes + automatic onchange
# ---------------------------------------------------------------------------

class TestTextInput(TestCase):
    """Single-line TextInput renders <textarea> with single_line/rows/
    autocomplete attributes, resize:none style, hint as placeholder, an
    automatic onchange handler reporting new_value, and round-trips value."""

    def test_textinput_full_contract(self):
        ti = gui.TextInput(single_line=True, hint="enter text")
        tag, attrs = root(ti)
        self.assertEqual("textarea", tag)
        self.assertEqual("TextInput", attrs["class"])
        self.assertEqual("true", attrs["single_line"])
        self.assertEqual("1", attrs["rows"])
        self.assertEqual("off", attrs["autocomplete"])
        self.assertEqual("enter text", attrs["placeholder"])
        self.assertEqual("none", style_dict(attrs["style"]).get("resize"))
        onchange = attrs["onchange"]
        self.assertIn("params['new_value']", onchange)
        self.assertIn("remi.sendCallbackParam('%s','onchange',params);" % ti.identifier, onchange)

        ti.set_value("hello")
        self.assertEqual("hello", ti.get_value())
        self.assertIn("hello", ti.repr())


# ---------------------------------------------------------------------------
# 4. Containers — layout + child management
# ---------------------------------------------------------------------------

class TestContainers(TestCase):
    """VBox/HBox/GridBox apply the right display style; append/get_child/
    remove_child/empty manage children, which render nested with
    data-parent-widget and order:-1 style."""

    def test_layout_and_child_management(self):
        self.assertEqual("column", style_dict(root(gui.VBox())[1]["style"])["flex-direction"])
        self.assertEqual("flex", style_dict(root(gui.VBox())[1]["style"])["display"])
        self.assertEqual("row", style_dict(root(gui.HBox())[1]["style"])["flex-direction"])
        self.assertEqual("grid", style_dict(root(gui.GridBox())[1]["style"])["display"])

        box = gui.VBox()
        lbl = gui.Label("keep_me")
        btn = gui.Button("remove_me")
        key = box.append(lbl, "l")
        box.append(btn, "b")
        self.assertIs(box.get_child(key), lbl)
        html = box.repr()
        self.assertIn("keep_me", html)
        self.assertIn("remove_me", html)
        self.assertIn('data-parent-widget="%s"' % box.identifier, html)
        self.assertIn("order:-1", html)
        box.remove_child(btn)
        self.assertNotIn("remove_me", box.repr())
        box.empty()
        self.assertNotIn("keep_me", box.repr())


# ---------------------------------------------------------------------------
# 5. Events — exact JS for simple, parametrized, and key events
# ---------------------------------------------------------------------------

class TestEvents(TestCase):
    """Connecting handlers injects exact JS: simple events use
    remi.sendCallback; mouse/key events build params and use
    remi.sendCallbackParam. Unconnected events emit no attribute."""

    def test_simple_event_js(self):
        b = gui.Button("x")
        b.onclick.do(lambda *a: None)
        self.assertEqual("remi.sendCallback('%s','onclick');" % b.identifier,
                         root(b)[1]["onclick"])
        b2 = gui.Button("x")
        b2.ondblclick.do(lambda *a: None)
        self.assertEqual("remi.sendCallback('%s','ondblclick');" % b2.identifier,
                         root(b2)[1]["ondblclick"])
        self.assertNotIn("onclick", root(gui.Button("z"))[1])

    def test_mouse_param_event_js(self):
        b = gui.Button("y")
        b.onmousedown.do(lambda *a: None)
        js = root(b)[1]["onmousedown"]
        self.assertIn("params['x']", js)
        self.assertIn("params['y']", js)
        self.assertIn("remi.sendCallbackParam('%s','onmousedown',params);" % b.identifier, js)

    def test_key_event_js(self):
        w = gui.Widget()
        w.onkeydown.do(lambda *a: None)
        js = root(w)[1]["onkeydown"]
        self.assertIn("keycode", js)
        self.assertIn("event.keyCode", js)
        self.assertIn("remi.sendCallbackParam('%s','onkeydown',params);" % w.identifier, js)


# ---------------------------------------------------------------------------
# 6. Incremental update / change tracking
# ---------------------------------------------------------------------------

class TestChangeTracking(TestCase):
    """repr(changed_widgets) records changed widgets for incremental updates
    and records nothing when nothing changed since the last render."""

    def test_changed_widgets_recorded_then_empty(self):
        box = gui.VBox()
        lbl = gui.Label("a")
        box.append(lbl, "l")
        box.repr()
        lbl.set_text("b")
        changed = {}
        box.repr(changed)
        self.assertIn(lbl, changed)
        changed2 = {}
        box.repr(changed2)
        self.assertEqual(0, len(changed2))


# ---------------------------------------------------------------------------
# 7. Application entry point
# ---------------------------------------------------------------------------

class TestAppEntryPoint(TestCase):
    """The documented quickstart works: subclass App, return a widget tree from
    main(), and that root renders the expected HTML. start and App's documented
    methods are exposed."""

    def test_app_quickstart_renders_root(self):
        from remi import start, App
        self.assertTrue(callable(start))
        for method in ("set_root_widget", "notification_message", "execute_javascript", "main"):
            self.assertTrue(hasattr(App, method), "App missing %s" % method)

        class MyApp(App):
            def main(self):
                root = gui.VBox()
                root.append(gui.Label("Hello"), "lbl")
                root.append(gui.Button("Go"), "btn")
                return root

        # App.__init__ wires up a live HTTP server/socket, so construct the
        # instance without running it and drive the documented entry point.
        app = object.__new__(MyApp)
        root_widget = app.main()

        tag, attrs = root(root_widget)
        self.assertEqual("div", tag)
        self.assertEqual("VBox", attrs["class"])
        self.assertEqual("column", style_dict(attrs["style"])["flex-direction"])
        html = root_widget.repr()
        self.assertIn("Hello", html)
        self.assertIn("<p", html)
        self.assertIn("Go", html)
        self.assertIn("<button", html)


# ---------------------------------------------------------------------------
# 8. Numeric inputs — SpinBox, Slider, Progress (consolidated)
# ---------------------------------------------------------------------------

class TestNumericInputs(TestCase):
    """SpinBox/Slider render <input> with type-based class, value/min/max/
    step, autocomplete='off' and automatic onchange. Progress renders
    <progress> with value/max."""

    def test_numeric_inputs(self):
        s = gui.SpinBox(default_value=5, min_value=0, max_value=10, step=2)
        tag, attrs = root(s)
        self.assertEqual("input", tag)
        self.assertEqual("number", attrs["class"])
        self.assertEqual("number", attrs["type"])
        self.assertEqual("5", attrs["value"])
        self.assertEqual("0", attrs["min"])
        self.assertEqual("10", attrs["max"])
        self.assertEqual("2", attrs["step"])
        self.assertEqual("off", attrs["autocomplete"])
        self.assertIn("sendCallbackParam('%s','onchange'" % s.identifier, attrs["onchange"])
        self.assertIn("onkeypress", attrs)
        self.assertIn("onkeyup", attrs)
        s.set_value(8)
        self.assertEqual(8, int(s.get_value()))

        sl = gui.Slider(default_value=5, min=0, max=100, step=5)
        tag, attrs = root(sl)
        self.assertEqual("range", attrs["class"])
        self.assertEqual("range", attrs["type"])
        self.assertEqual("5", attrs["value"])
        self.assertEqual("off", attrs["autocomplete"])
        self.assertIn("sendCallbackParam('%s','onchange'" % sl.identifier, attrs["onchange"])

        p = gui.Progress(value=3, _max=10)
        tag, attrs = root(p)
        self.assertEqual("progress", tag)
        self.assertEqual("3", attrs["value"])
        self.assertEqual("10", attrs["max"])


# ---------------------------------------------------------------------------
# 9. CheckBox + CheckBoxLabel
# ---------------------------------------------------------------------------

class TestCheckBox(TestCase):
    """CheckBox renders <input type=checkbox class=checkbox> with automatic
    onchange reporting .checked; CheckBoxLabel wraps a checkbox + label in a
    flex row."""

    def test_checkbox_and_label(self):
        c = gui.CheckBox(checked=True)
        tag, attrs = root(c)
        self.assertEqual("input", tag)
        self.assertEqual("checkbox", attrs["class"])
        self.assertEqual("checkbox", attrs["type"])
        self.assertIn("checked", attrs)
        self.assertEqual("off", attrs["autocomplete"])
        self.assertIn(".checked", attrs["onchange"])
        self.assertIn("sendCallbackParam('%s','onchange'" % c.identifier, attrs["onchange"])

        cbl = gui.CheckBoxLabel("Accept", checked=True)
        tag, attrs = root(cbl)
        self.assertEqual("div", tag)
        self.assertEqual("CheckBoxLabel", attrs["class"])
        self.assertEqual("row", style_dict(attrs["style"])["flex-direction"])
        self.assertIn("Accept", cbl.repr())
        self.assertIn('type="checkbox"', cbl.repr())


# ---------------------------------------------------------------------------
# 10. Date + ColorPicker
# ---------------------------------------------------------------------------

class TestDateColorPicker(TestCase):
    """Date and ColorPicker render <input> with date/color type and a
    type-based class, plus automatic onchange + autocomplete."""

    def test_date_and_color(self):
        d = gui.Date()
        tag, attrs = root(d)
        self.assertEqual("input", tag)
        self.assertEqual("date", attrs["type"])
        self.assertEqual("date", attrs["class"])
        self.assertEqual("off", attrs["autocomplete"])
        self.assertIn("sendCallbackParam('%s','onchange'" % d.identifier, attrs["onchange"])

        cp = gui.ColorPicker()
        tag, attrs = root(cp)
        self.assertEqual("color", attrs["type"])
        self.assertEqual("color", attrs["class"])
        self.assertIn("sendCallbackParam('%s','onchange'" % cp.identifier, attrs["onchange"])


# ---------------------------------------------------------------------------
# 11. DropDown — options, selection, automatic onchange
# ---------------------------------------------------------------------------

class TestDropDown(TestCase):
    """DropDown renders <select> with an automatic onchange and <option>
    children; supports new_from_list, select_by_value, get_value."""

    def test_dropdown(self):
        dd = gui.DropDown.new_from_list(["alpha", "beta", "gamma"])
        tag, attrs = root(dd)
        self.assertEqual("select", tag)
        self.assertEqual("DropDown", attrs["class"])
        self.assertIn("sendCallbackParam('%s','onchange'" % dd.identifier, attrs["onchange"])
        for opt in ["alpha", "beta", "gamma"]:
            self.assertIn(opt, dd.repr())
        dd.select_by_value("beta")
        self.assertEqual("beta", dd.get_value())
        self.assertIn('selected="selected"', dd.repr())

        item = gui.DropDownItem("choice")
        tag, attrs = root(item)
        self.assertEqual("option", tag)
        self.assertEqual("choice", attrs["value"])


# ---------------------------------------------------------------------------
# 12. Media — Link, Image, VideoPlayer, FileDownloader
# ---------------------------------------------------------------------------

class TestMediaWidgets(TestCase):
    """Link/Image/VideoPlayer/FileDownloader render their tags with correct
    source/href/download attributes."""

    def test_media_widgets(self):
        tag, attrs = root(gui.Link("http://example.com", "mylink"))
        self.assertEqual("a", tag)
        self.assertEqual("http://example.com", attrs["href"])
        self.assertIn("mylink", gui.Link("http://example.com", "mylink").repr())

        tag, attrs = root(gui.Image("http://example.com/cat.png"))
        self.assertEqual("img", tag)
        self.assertIn("http://example.com/cat.png", gui.Image("http://example.com/cat.png").repr())

        tag, attrs = root(gui.VideoPlayer("http://example.com/v.mp4"))
        self.assertEqual("video", tag)
        self.assertEqual("http://example.com/v.mp4", attrs["src"])
        self.assertIn("controls", attrs)

        fd = gui.FileDownloader("click here", "food.txt")
        tag, attrs = root(fd)
        self.assertEqual("a", tag)
        self.assertEqual("food.txt", attrs["download"])
        self.assertIn("click here", fd.repr())


# ---------------------------------------------------------------------------
# 13. Lists — ListView, ListItem
# ---------------------------------------------------------------------------

class TestLists(TestCase):
    """ListView renders <ul>, ListItem renders <li>, and new_from_list builds
    one <li> per entry."""

    def test_lists(self):
        tag, attrs = root(gui.ListView())
        self.assertEqual("ul", tag)
        self.assertEqual("ListView", attrs["class"])

        tag, attrs = root(gui.ListItem("an item"))
        self.assertEqual("li", tag)
        self.assertIn("an item", gui.ListItem("an item").repr())

        lv = gui.ListView.new_from_list(["a", "b", "c"])
        self.assertEqual(3, lv.repr().count("<li"))


# ---------------------------------------------------------------------------
# 14. Tables — new_from_list, TableWidget, item access
# ---------------------------------------------------------------------------

class TestTables(TestCase):
    """Table.new_from_list builds <tr> rows with <th> header and <td> body
    cells; TableWidget pre-populates dimensions and exposes item_at cell
    access."""

    def test_tables(self):
        t = gui.Table.new_from_list([("H1", "H2"), ("a", "b"), ("c", "d")])
        self.assertEqual("table", root(t)[0])
        html = t.repr()
        self.assertIn("<th", html)
        self.assertIn("<td", html)
        for content in ["H1", "H2", "a", "b", "c", "d"]:
            self.assertIn(content, html)
        self.assertEqual(3, html.count("<tr"))

        tw = gui.TableWidget(2, 3, use_title=True, editable=False)
        self.assertEqual("table", root(tw)[0])
        twhtml = tw.repr()
        self.assertEqual(3, twhtml.count("<th"))
        self.assertEqual(3, twhtml.count("<td"))
        self.assertEqual(2, twhtml.count("<tr"))

        tw2 = gui.TableWidget(2, 2, use_title=False)
        tw2.item_at(0, 0).set_text("CELL")
        self.assertIn("CELL", tw2.repr())


# ---------------------------------------------------------------------------
# 15. SVG shapes — geometry attribute mapping (Rect/Circle/Line/Ellipse/
#     Path/Text/Image/Group)
# ---------------------------------------------------------------------------

class TestSvgShapes(TestCase):
    """SVG widgets map constructor geometry args to the correct SVG attribute
    names and nest inside an <svg> container."""

    def test_svg_shapes(self):
        svg = gui.Svg(width=100, height=100)
        r = gui.SvgRectangle(10, 20, 30, 40)
        svg.append(r, "r")
        self.assertEqual("svg", root(svg)[0])
        rtag, rattrs = root(r)
        self.assertEqual("rect", rtag)
        self.assertEqual("10", rattrs["x"])
        self.assertEqual("20", rattrs["y"])
        self.assertEqual("30", rattrs["width"])
        self.assertEqual("40", rattrs["height"])

        tag, attrs = root(gui.SvgCircle(50, 60, 25))
        self.assertEqual("circle", tag)
        self.assertEqual("50", attrs["cx"])
        self.assertEqual("60", attrs["cy"])
        self.assertEqual("25", attrs["r"])

        tag, attrs = root(gui.SvgLine(10, 10, 20, 30))
        self.assertEqual("line", tag)
        self.assertEqual("10", attrs["x1"])
        self.assertEqual("30", attrs["y2"])

        tag, attrs = root(gui.SvgEllipse(10, 20, 30, 40))
        self.assertEqual("ellipse", tag)
        self.assertEqual("10", attrs["cx"])
        self.assertEqual("30", attrs["rx"])
        self.assertEqual("40", attrs["ry"])

        tag, attrs = root(gui.SvgPath("M 10 10 L 20 20 Z"))
        self.assertEqual("path", tag)
        self.assertEqual("M 10 10 L 20 20 Z", attrs["d"])

        svgtext = gui.SvgText(15, 25, "hello world")
        tag, attrs = root(svgtext)
        self.assertEqual("text", tag)
        self.assertEqual("15", attrs["x"])
        self.assertIn("hello world", svgtext.repr())

        tag, attrs = root(gui.SvgImage("pic.png", 10, 20, 30, 40))
        self.assertEqual("image", tag)
        self.assertEqual("pic.png", attrs["xlink:href"])
        self.assertEqual("30", attrs["width"])

        tag, attrs = root(gui.SvgGroup())
        self.assertEqual("g", tag)
        self.assertEqual("SvgGroup", attrs["class"])


# ---------------------------------------------------------------------------
# 16. SVG Polyline / Polygon — points + vector-effect attribute
# ---------------------------------------------------------------------------

class TestSvgPolyline(TestCase):
    """Polyline/Polygon render with a points attribute and the
    vector-effect attribute (not a style property)."""

    def test_polyline_and_polygon(self):
        tag, attrs = root(gui.SvgPolyline())
        self.assertEqual("polyline", tag)
        self.assertIn("points", attrs)
        self.assertEqual("non-scaling-stroke", attrs["vector-effect"])

        tag, attrs = root(gui.SvgPolygon())
        self.assertEqual("polygon", tag)
        self.assertIn("points", attrs)


# ---------------------------------------------------------------------------
# 17. SelectionInput + Datalist
# ---------------------------------------------------------------------------

class TestSelectionInput(TestCase):
    """SelectionInput renders a text <input> with autocomplete + automatic
    onchange; Datalist renders a hidden <datalist>."""

    def test_selection_input_and_datalist(self):
        si = gui.SelectionInput()
        tag, attrs = root(si)
        self.assertEqual("input", tag)
        self.assertEqual("text", attrs["type"])
        self.assertEqual("text", attrs["class"])
        self.assertEqual("off", attrs["autocomplete"])
        self.assertIn("sendCallbackParam('%s','onchange'" % si.identifier, attrs["onchange"])

        tag, attrs = root(gui.Datalist())
        self.assertEqual("datalist", tag)
        self.assertEqual("Datalist", attrs["class"])
        self.assertEqual("none", style_dict(attrs.get("style"))["display"])


# ---------------------------------------------------------------------------
# 18. Tree + Menu / MenuBar
# ---------------------------------------------------------------------------

class TestTreeAndMenu(TestCase):
    """TreeItem/MenuItem nest children; Menu renders <ul> and MenuBar
    renders <nav>."""

    def test_tree_menu_nesting_and_tags(self):
        ti = gui.TreeItem("parent_node")
        ti.append(gui.TreeItem("child_node"), "c")
        self.assertIn("parent_node", ti.repr())
        self.assertIn("child_node", ti.repr())

        mi = gui.MenuItem("File")
        mi.append(gui.MenuItem("Open"), "s")
        self.assertIn("File", mi.repr())
        self.assertIn("Open", mi.repr())

        mtag, mattrs = root(gui.Menu())
        self.assertEqual("ul", mtag)
        self.assertEqual("Menu", mattrs["class"])

        btag, battrs = root(gui.MenuBar())
        self.assertEqual("nav", btag)
        self.assertEqual("MenuBar", battrs["class"])


# ---------------------------------------------------------------------------
# 19. TabBox.add_tab
# ---------------------------------------------------------------------------

class TestTabBox(TestCase):
    """TabBox.add_tab adds a named tab whose label and content appear in HTML."""

    def test_tabbox_add_tab(self):
        tb = gui.TabBox()
        tb.add_tab(gui.Label("tab content"), "MyTab", None)
        html = tb.repr()
        self.assertIn("MyTab", html)
        self.assertIn("tab content", html)


# ---------------------------------------------------------------------------
# 20. Dialogs
# ---------------------------------------------------------------------------

class TestDialogs(TestCase):
    """GenericDialog shows title/message and manages labelled fields."""

    def test_generic_dialog_fields(self):
        gd = gui.GenericDialog(title="My Title", message="My Message")
        ti = gui.TextInput()
        gd.add_field("username", ti)
        self.assertIn("My Title", gd.repr())
        self.assertIn("My Message", gd.repr())
        self.assertIs(gd.get_field("username"), ti)

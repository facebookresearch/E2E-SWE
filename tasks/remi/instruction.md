# remi — Python GUI Library Rendered as HTML

Implement `remi`, a pure-Python GUI library whose widgets render themselves as HTML. A developer builds an interface by constructing widget objects in Python, nesting them in container widgets, registering event handlers, and styling them with CSS. Each widget knows how to serialize itself to an HTML string.

## Dependencies and environment

`remi` is a pure-Python library that uses the **standard library only** — it has no third-party runtime dependencies. The environment is **offline**: everything needed (the Python interpreter and the build backend) is already installed, and there is **no network access**, so you must not install anything (no `pip install`, no `git clone`). Your project is installed offline by a `setup.sh` that runs `pip install -e . --no-build-isolation`, so structure your package as an installable project (e.g. with a `setup.py`/`pyproject.toml`) that exposes the `remi` package importably.

## Package Structure

```python
import remi.gui as gui
```

All widgets live in the `remi.gui` module and are accessed as `gui.<WidgetName>`.

## Core Rendering Contract

Every widget exposes a `.repr()` method returning its HTML representation as a string:

```python
gui.Button("Click").repr()
# -> '<button id="..." class="Button">Click</button>'
```

Rules that apply to all widgets:

- **Tag id**: every element has an `id` attribute whose value is a unique per-object identifier — non-deterministic across runs, but always present and stable for a given object. The same value is exposed as the `widget.identifier` property, and event-handler JS embeds this same id.
- **`class` attribute**: by default equals the widget's Python class name (e.g. `Button` → `class="Button"`, `Label` → `class="Label"`). The form-`<input>` widgets are an exception (see §Input widgets) — they use type-based class names.
- **`style` attribute**: inline CSS, built from the widget's style dictionary. Serializes as `key:value` pairs joined by `;` in insertion order, e.g. `style="width:100px;height:50px;color:blue"`. The attribute is omitted when the style dict is empty.
- **children**: container widgets render their children's HTML nested between their open/close tags, in append order. Each child element carries a `data-parent-widget="<parent-id>"` attribute, and (for flex/box containers) a `style` including `position:static` and `order:-1`.

## Widget — base class

`gui.Widget(**kwargs)` renders as a `<div class="Widget">`. It is the base for graphical widgets and provides:

- `set_size(width, height)` — sets `width`/`height` style in px (integers become `"100px"`).
- `style` — a dict-like attribute; assigning `widget.style["color"] = "blue"` adds to the inline style.
- `css_background_color`, `css_width`, `css_height`, `css_left`, `css_top`, and many other `css_*` properties — setters that write the corresponding CSS property into `style` (e.g. `css_background_color = "red"` → `background-color:red`).
- `add_class(name)` — appends a CSS class to the `class` attribute (space-separated).
- `remove_class(name)` — removes a CSS class from the `class` attribute.
- `attributes` — a dict-like of HTML attributes (e.g. `attributes["class"]`).

Many widgets accept `width=` and `height=` keyword arguments that set the size.

## Containers — nesting and layout

A `Container` is a widget that holds children. Children are added with:

- `append(child, key=None)` — adds a child, returns the key under which it is stored. If no key is given, one is generated. The child becomes retrievable via `get_child(key)`.
- `get_child(key)` — returns the child stored under `key`.
- `remove_child(child)` — removes the given child widget.
- `empty()` — removes all children.

Layout containers:

- `gui.VBox(**kwargs)` — vertical box. Style includes `display:flex` and `flex-direction:column`.
- `gui.HBox(**kwargs)` — horizontal box. Style includes `display:flex` and `flex-direction:row`.
- `gui.GridBox(**kwargs)` — grid container. Style includes `display:grid`.
- `gui.TabBox(**kwargs)` — tabbed container rendered as a `<div class="TabBox">`.

Page-structure tags also exist: `gui.HTML`, `gui.HEAD(title=...)`, `gui.BODY`.

## Text widgets

- `gui.Button(text, **kwargs)` — renders `<button class="Button">text</button>`. Raises an exception if `text` is not a string.
- `gui.Label(text, **kwargs)` — renders `<p class="Label">text</p>`. Raises an exception if `text` is not a string. `set_text(new_text)` replaces the content.

(`TextInput` is described in its own section below.)

## Event handling

Every widget exposes event connectors named after DOM events: `onclick`, `ondblclick`, `onmousedown`, `onmouseup`, `onmousemove`, `onchange`, `onkeydown`, `onkeyup`, etc. Connect a handler with `.do(callback)`:

```python
button.onclick.do(my_handler)
```

Connecting a handler injects JS into the corresponding HTML attribute. Each event is either **simple** (no parameters) or **parametrized** (carries data); the bucket each event name falls into is fixed:

- **Simple events** carry no parameters and emit `remi.sendCallback('<id>','<event>');` (where `<id>` is the widget's element id). `onclick` and `ondblclick` are simple events — e.g. a connected `ondblclick` emits exactly `ondblclick="remi.sendCallback('<id>','ondblclick');"`, the same form as `onclick` with the event name substituted.
- **Parametrized events** emit a JS snippet that builds a `params` object and calls `remi.sendCallbackParam('<id>','<event>',params);`. The coordinate-carrying mouse events `onmousedown`, `onmouseup`, and `onmousemove` each compute cursor coordinates relative to the element and set `params['x']` and `params['y']` before calling `sendCallbackParam`.
- **Key events** `onkeydown` and `onkeyup` are parametrized: they build a params object that includes the pressed key and key code (e.g. `params['keycode']=(event.which||event.keyCode)`) before calling `sendCallbackParam`.

A widget with no connected handler does not emit that event's attribute.

## Incremental update / change tracking

`repr()` accepts an optional `changed_widgets` dict used for incremental updates: `widget.repr(changed_widgets)`. When a widget (or one of its descendants) has changed since the last render, calling `repr(changed)` records the changed widget(s) in the dict (keyed by the widget object). Re-rendering again with no intervening changes records nothing (the dict stays empty). This lets the framework send only the changed sub-trees to the browser. A widget is considered "changed" when its attributes, style, or children change (e.g. via `set_text`, `append`, a style assignment, etc.).

## Application entry point

The top-level package exposes the application machinery:

```python
from remi import start, App
```

- `App` — base class for a remi application. A user subclasses it and implements `main(self)` returning the root widget; `App` itself declares a `main(self)` hook (a stub that raises `NotImplementedError`) which subclasses override. It provides methods including `set_root_widget(widget)`, `notification_message(title, content, icon="")`, and `execute_javascript(code)`.
- `start(app_class, **kwargs)` — launches the web server hosting the given `App` subclass.

## Input widgets (form `<input>` elements)

These render as `<input>` (or `<progress>`) with a **type-based class name**, not the Python class name.

**Automatic onchange handler.** Every value-bearing input widget *automatically* registers an `onchange` handler at construction (the user does not connect it). This handler reports the input's current value back to the server via `remi.sendCallbackParam('<id>','onchange',params)`, where `params['value']` is set from the element's `.value` (for most inputs) or `.checked` (for the checkbox). All these inputs also carry `autocomplete="off"`.

- `gui.SpinBox(default_value=0, min_value=0, max_value=65535, step=1, **kwargs)` — `<input class="number" type="number">` with `value`, `min`, `max`, `step` attributes from the args. In addition to the automatic `onchange`, a SpinBox emits `onkeypress`/`onkeyup` JS that restricts typed characters to digits and submits on Enter.
- `gui.Slider(default_value=0, min=0, max=65535, step=1, **kwargs)` — `<input class="range" type="range">` with `value`, `min`, `max`, `step`.
- `gui.CheckBox(checked=False, **kwargs)` — `<input class="checkbox" type="checkbox">`. When `checked=True`, adds a `checked` attribute. Its automatic `onchange` reports `params['value']` from the element's `.checked`.
- `gui.Date(default_value='2015-04-13', **kwargs)` — `<input class="date" type="date">`.
- `gui.ColorPicker(default_value='#995500', **kwargs)` — `<input class="color" type="color">`.
- `gui.Progress(value=0, _max=100, **kwargs)` — renders `<progress>` with `value` and `max` attributes. (Progress is not an editable input and has no onchange/autocomplete.)

Editable inputs expose `set_value(v)` and `get_value()`.

## TextInput details

`gui.TextInput(single_line=True, hint='', **kwargs)`:
- With `single_line=True`, renders `<textarea class="TextInput">` carrying the attributes `single_line="true"`, `rows="1"`, `autocomplete="off"`, an automatic `onchange` handler (whose `params['new_value']` comes from the element's `.value`), and `style="resize:none"`.
- The `hint` becomes the `placeholder` attribute.
- `set_value(text)` / `get_value()` set and read the text content.

## DropDown

- `gui.DropDown(**kwargs)` — renders `<select class="DropDown">`. Like the value-bearing `<input>` widgets, a DropDown *automatically* registers an `onchange` handler at construction (the user does not connect it) that reports the selected value back to the server via `remi.sendCallbackParam('<id>','onchange',params)`, where `params['value']` is set from the `<select>`'s `.value`. Build one from a list with the classmethod `gui.DropDown.new_from_list(["a", "b", "c"])`, which appends a `DropDownItem` per entry.
- `gui.DropDownItem(text, **kwargs)` — renders `<option value="text">text</option>`.
- `select_by_value(value)` — marks the matching option as selected (adds `selected="selected"`).
- `get_value()` — returns the currently selected option's value.

## CheckBoxLabel

`gui.CheckBoxLabel(label='', checked=False, **kwargs)` — an `HBox` (flex row) containing a `CheckBox` and a `Label`. Renders `<div class="CheckBoxLabel" style="display:flex;flex-direction:row;...">` with the checkbox and label nested inside.

## Lists

- `gui.ListView(**kwargs)` — renders `<ul class="ListView">`. Build from a list with `gui.ListView.new_from_list([...])`.
- `gui.ListItem(text, **kwargs)` — renders `<li class="ListItem">text</li>`.

## Link, Image, Video

- `gui.Link(url='', text='', open_new_window=True, **kwargs)` — renders `<a href="url">text</a>` (with `target="_blank"` when opening a new window).
- `gui.Image(image='', **kwargs)` — renders an `<img>` element whose source attribute is the given url.
- `gui.VideoPlayer(video='', poster=None, autoplay=False, loop=False, **kwargs)` — renders `<video class="VideoPlayer" src="..." preload="auto" controls poster>`.
- `gui.FileDownloader(text='', filename='', path_separator='/', **kwargs)` — renders `<a class="FileDownloader" download="<filename>" href="...">text</a>` with a `download` attribute equal to the filename.

## Tables

- `gui.Table(**kwargs)` — renders `<table>`. The classmethod `gui.Table.new_from_list(rows)` builds a table from a list of row tuples: the **first row** becomes header cells (`<th>`, class `TableTitle`), and the remaining rows become body cells (`<td>`, class `TableItem`). Each row is a `<tr>`.
- `gui.TableWidget(n_rows=2, n_columns=2, use_title=True, editable=False, **kwargs)` — renders a `<table>` pre-populated with `n_rows` rows of `n_columns` cells. With `use_title=True`, the first row uses `<th>` cells and the remaining rows use `<td>` cells.

## SVG

- `gui.Svg(width=..., height=..., **kwargs)` — renders an `<svg>` container; append SVG shapes as children.
- `gui.SvgRectangle(x=0, y=0, w=100, h=100, **kwargs)` — `<rect>` with attributes `x`, `y`, `width` (from `w`), `height` (from `h`).
- `gui.SvgCircle(x=0, y=0, radius=50, **kwargs)` — `<circle>` with attributes `cx` (from `x`), `cy` (from `y`), `r` (from `radius`).
- `gui.SvgLine(x1=0, y1=0, x2=50, y2=50, **kwargs)` — `<line>` with attributes `x1`, `y1`, `x2`, `y2`.
- `gui.SvgText(x=10, y=10, text='svg text', **kwargs)` — `<text>` positioned at `x`, `y` containing the text.
- `gui.SvgEllipse(x=0, y=0, rx=50, ry=30, **kwargs)` — `<ellipse>` with attributes `cx` (from `x`), `cy` (from `y`), `rx`, `ry`.
- `gui.SvgPolyline(**kwargs)` — `<polyline>` with a `points` attribute and `vector-effect="non-scaling-stroke"`. Points are added with `add_coord(x, y)`.
- `gui.SvgPolygon(**kwargs)` — `<polygon>`, like polyline but a closed shape.
- `gui.SvgPath(path_value='', **kwargs)` — `<path>` with the `d` attribute set to `path_value`.

## Dialogs

- `gui.GenericDialog(title='', message='', **kwargs)` — a dialog showing the title and message text. Add labelled input fields with `add_field(key, field_widget)` (optionally `add_field_with_label(key, label_text, field_widget)`), and retrieve a registered field widget with `get_field(key)`.
- `gui.InputDialog(title='', message='', **kwargs)` — a `GenericDialog` subclass with a single text input.

## Tree and Menu

- `gui.TreeView(**kwargs)`, `gui.TreeItem(text, **kwargs)` — a tree. A `TreeItem` may `append` child `TreeItem`s to form a hierarchy; nested items render nested in the HTML.
- `gui.MenuBar(**kwargs)` — renders `<nav class="MenuBar">`; holds a `Menu`.
- `gui.Menu(**kwargs)` — renders `<ul class="Menu">`. `gui.MenuItem(text, **kwargs)` — a menu entry; a `MenuItem` may `append` sub-`MenuItem`s to build submenus.

## More widgets

- `gui.TableWidget(...)` exposes `item_at(row, column)` returning the cell widget at that position (whose `set_text` updates the cell content), and `item_coords(item)`.
- `gui.TabBox(**kwargs)` exposes `add_tab(widget, key, callback=None)` to add a named tab whose content is `widget` and whose visible tab label is the `key` string.
- `gui.SelectionInput(**kwargs)` — a text input (`<input type="text" class="text">`) backed by a datalist for autocomplete; like other inputs it has `autocomplete="off"` and an automatic `onchange`.
- `gui.Datalist(**kwargs)` — renders `<datalist class="Datalist" style="display:none">`; holds `gui.DatalistItem(text)` entries.
- `gui.SvgImage(image_data='', x=0, y=0, w=100, h=100, **kwargs)` — `<image>` with `xlink:href` (from `image_data`), `x`, `y`, `width` (from `w`), `height` (from `h`).
- `gui.SvgGroup(**kwargs)` — `<g class="SvgGroup">`, a grouping container for SVG shapes.

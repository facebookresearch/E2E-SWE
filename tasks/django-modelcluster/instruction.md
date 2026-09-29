# django-modelcluster

Implement **modelcluster**, a Django extension for working with "clusters" of
related model objects as a single unit, held **in memory** and independent of the
database until the cluster's root object is explicitly saved.

Django's normal foreign keys require objects to exist in the database before a
relation can be populated. modelcluster lifts that restriction: it introduces a
`ParentalKey` (a foreign key whose child rows live on the parent in memory) and a
`ParentalManyToManyField`, and a `ClusterableModel` base class whose `save()`
commits the whole cluster at once. Until then the in-memory children can be
queried through a Django-QuerySet-like API, serialized to JSON, deep-copied, and
edited through cluster-aware forms and formsets.

```python
from modelcluster.models import ClusterableModel
from modelcluster.fields import ParentalKey

class Band(ClusterableModel):
    name = models.CharField(max_length=255)

class BandMember(models.Model):
    band = ParentalKey("Band", related_name="members", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

beatles = Band(name="The Beatles")
beatles.members = [BandMember(name="John Lennon"), BandMember(name="Paul McCartney")]
beatles.members.count()                  # 2  — queryable before save
Band.objects.filter(name="The Beatles")  # empty — nothing in the DB yet
beatles.save()                           # now the whole cluster is written
```

## Environment & dependencies

- **The environment is offline and every dependency is already installed — do not install (or
  attempt to download) anything.** The project itself is installed by a `setup.sh` that runs fully
  offline (an editable install of your package against the pre-installed dependencies); you only
  need to lay out the package so that editable install succeeds.
- Target **Python 3.10** and **Django 5.2.x** (the environment provides `Django 5.2`). Use Django
  5.x APIs — e.g. `datetime.timezone.utc`, not the removed `django.utils.timezone.utc` alias.
- **django-taggit** (`django-taggit 6.1`) is pre-installed, so `import taggit` already works — the
  `modelcluster.contrib.taggit` subsystem can rely on it directly. Declare `django-taggit` as an
  optional dependency of your package (an extra), but you do **not** need to install it yourself.

## Public import surface

Implement these modules and importable names **exactly** — the test suite
imports from these precise paths:

- `modelcluster.models` — `ClusterableModel`, `get_all_child_relations`,
  `get_all_child_m2m_relations`.
- `modelcluster.fields` — `ParentalKey`, `ParentalManyToManyField`.
- `modelcluster.queryset` — `FakeQuerySet`.
- `modelcluster.utils` — `ManyToManyTraversalError`.
- `modelcluster.forms` — `ClusterForm`, `childformset_factory`,
  `transientmodelformset_factory`.
- `modelcluster.contrib.taggit` — `ClusterTaggableManager`.

Internal helpers, module organization, and attribute names beyond the above are
yours to design. Do **not** rely on internal attribute names being a specific
value — tests subclass your managers/fields and may collide with private names.

---

## 1. ParentalKey and the deferring child manager (`modelcluster.fields`)

`ParentalKey` is a subclass of Django's `ForeignKey` declared on the **child**
model, pointing back at a `ClusterableModel` parent. `on_delete` defaults to
`CASCADE` when omitted.

Accessing the reverse accessor on a parent instance (e.g. `band.members`) returns
a **deferring related manager**: a manager that keeps an in-memory list of child
objects and only writes to the database when committed. It must support:

- **Assignment** — `parent.members = [child, ...]` replaces the in-memory set.
  Each child's foreign key is pointed back at the parent instance.
- **`all()`** — returns a `FakeQuerySet` (§3) over the in-memory children when the
  set has been touched in memory; for a saved, untouched parent it may fall back
  to the live database queryset. On an unsaved, untouched parent it is empty.
- **`add(*objs)`** — append objects; if an equal object is already present it is
  replaced (so re-adding a mutated instance updates it). De-duplicates.
- **`remove(*objs)`**, **`clear()`**, **`create(**kwargs)`** (builds, appends and
  returns a new child without saving), **`set(objs)`**.
- **`count()`**, plus the rest of the `FakeQuerySet` read API by delegating
  through `all()`.
- **`commit()`** — write the in-memory set to the database: insert/keep current
  members and **delete** any database rows no longer in the set. Raises
  `django.db.IntegrityError` if the parent has no primary key (is unsaved).

When the child model defines `Meta.ordering`, the in-memory set is kept sorted by
that ordering (so `all()` returns children in `Meta.ordering` order).

### System checks

`ParentalKey.check()` must add these Django system-check errors:

- **`modelcluster.E001`** when the target is a resolved model class that is **not**
  a subclass of `ClusterableModel`. Message exactly:
  `"ParentalKey must point to a subclass of ClusterableModel."`
- **`modelcluster.E002`** when `related_name='+'` (i.e. the relation has no usable
  accessor name). Message exactly:
  `"related_name='+' is not allowed on ParentalKey fields"`

(If the target model name can't be resolved to a class, skip E001 and let
Django's own `fields.E300` check fire.)

---

## 2. ParentalManyToManyField (`modelcluster.fields`)

A subclass of `ManyToManyField`, declared on the parent model, whose related set
is held in memory until the parent is saved. Its manager supports the same
in-memory `all()/add/remove/clear/set/count` semantics as above, plus:

- **Assignment** — `parent.<field> = [obj, ...]` (any iterable or queryset of
  saved target objects) replaces the in-memory related set, equivalent to
  `.set(...)`. Like `set()`, it works on an unsaved parent (the change is held in
  memory until save).
- The manager exposes a **`model`** attribute pointing at the target model.
- Reading the relation on a freshly built (unsaved, untouched) instance returns an
  **empty** result, not an error.
- `add()` requires each object to already have a primary key (the related objects
  must exist in the DB); adding an unsaved object raises **`ValueError`**.
- The in-memory set respects the **target model's** `Meta.ordering`.
- The reverse accessor (e.g. `author.articles_by_author`) reflects only parents
  already saved to the database, and supports the normal related-manager query
  API.
- **`value_from_object(obj)`** returns the current in-memory related set (so it
  works before the parent is saved — unlike Django's default, which returns empty
  for unsaved instances).
- `save(update_fields=[...])` that names a parental-m2m field commits that field.

---

## 3. FakeQuerySet (`modelcluster.queryset`)

`FakeQuerySet(model, results)` wraps an in-memory list of model instances and
emulates the read side of Django's `QuerySet` API. It is what the deferring
managers return, and it is also used directly (e.g. `FakeQuerySet(Log, [...])`).

Construction: `FakeQuerySet(model, results)` where `results` is a list of `model`
instances.

### Filtering

- **`filter(*args, **kwargs)`** / **`exclude(*args, **kwargs)`** return a new
  `FakeQuerySet`. `exclude` returns the complement of `filter`.
- Keyword lookups use Django's `field__lookup=value` spelling and must support
  these lookup types with Django-equivalent semantics:
  `exact` (default), `iexact`, `contains`, `icontains`, `startswith`,
  `istartswith`, `endswith`, `iendswith`, `in`, `lt`, `lte`, `gt`, `gte`,
  `range`, `isnull`, `regex`, `iregex`.
  - Values are coerced to the field's Python type before comparison (so
    `id="2"` matches an integer pk `2`).
  - `None` / empty-string values compare correctly (e.g. `name=None`,
    `name=""`, and `name__isnull=True/False`).
  - `in` uses plain Python membership against the value list: a `None` present
    in the list matches a field whose value is `None` (e.g.
    `get(name__in=[None, "Mink Car"])` returns the row whose `name` is `None`).
    This intentionally differs from Django's SQL `IN`, where `NULL IN (...)` is
    never true and NULL-valued rows are excluded.
  - A field whose **name** collides with a lookup token (e.g. a field literally
    named `range`) is treated as a field, not a lookup.
- Lookups may traverse **forward** foreign keys / one-to-one relations and the
  **reverse** FK to the parent with `__` (e.g.
  `favourite_restaurant__proprietor__name`, `band__name`). A row whose
  intermediate relation is `None` is treated as non-matching (excluded), not an
  error.
- Comparing a relation against a **model instance** matches by primary key for
  saved instances (and treats two distinct *unsaved* instances as different).
  Across multi-table inheritance, an instance matches when either side is a
  subclass of the other (same pk).
- Positional arguments accept `django.db.models.Q` objects, combined with
  `AND` / `OR` / `XOR` and negation (`~Q(...)`).
- Traversing a **many-to-many** relationship in a lookup is unsupported and must
  raise **`ManyToManyTraversalError`** (from `modelcluster.utils`).

### Date/time derivatives

For `DateField` / `DateTimeField` / `TimeField` values, support the lookup
*transforms* Django offers, both in `filter()`/`get()` and as projected fields in
`values()`/`values_list()` (e.g. `release_date__year`, `time__date`):

- Date components: `year`, `iso_year`, `month`, `day`, `week`, `week_day`,
  `iso_week_day`, `quarter`.
- Datetime extras: `date`, `time`.
- Time components: `hour`, `minute`, `second`.

`week_day` follows Django's convention (Sunday = 1 … Saturday = 7); `iso_week_day`
is ISO (Monday = 1 … Sunday = 7); `week` and `iso_year` come from the ISO
calendar. A `None` datetime yields `None` for every derived component.

### Retrieval & shaping

- **`get(*args, **kwargs)`** — return the single match; raise
  `model.DoesNotExist` if none and `model.MultipleObjectsReturned` if more than
  one. After `values()`/`values_list()`, `get()` returns the shaped dict/tuple.
- **`count()`**, **`exists()`**, **`first()`**, **`last()`**.
- **`order_by(*fields)`** — sort by one or more fields, each optionally prefixed
  `-` for descending; `?` shuffles randomly. Sorting may span relations with `__`,
  and rows with a `None` sort value sort **first**.
- **`values(*fields)`** — yield dicts; with no args, every concrete field. Field
  names may span relations with `__`. Foreign-key fields yield the related pk.
- **`values_list(*fields, flat=None)`** — yield tuples; `flat=True` yields scalars
  (and raises **`TypeError`** if combined with more than one field).
- **`distinct(*fields)`** — drop duplicate rows (by the given fields, or all
  non-pk fields if none given).
- **`none()`** — an empty queryset that stays empty under further chaining.
- **`all()`** returns the queryset itself; `filter`/`order_by`/`values`/… are
  chainable after one another and after `none()`.
- Support iteration, `len()`, indexing (`qs[0]`), and truthiness.
- `select_related`, `prefetch_related`, `only`, `defer` exist; only
  `prefetch_related` has real effect (it must drive Django's
  `prefetch_related_objects` over the in-memory results so that
  `Model.objects.prefetch_related("members"/"authors"/"tags")` works and reduces
  query counts).

---

## 4. ClusterableModel (`modelcluster.models`)

Abstract base model. In addition to the manager behavior above:

- **Constructor** — accepts child-relation accessor names and parental-m2m field
  names as keyword arguments (e.g.
  `Band(name="…", members=[...], albums=[...])`), assigning them to the
  in-memory relations after normal field initialization.
- **`save(**kwargs)`** — save the model and then `commit()` every child relation
  and parental-m2m field. If `update_fields` is given, partition it: names that
  are child relations or parental-m2m fields are committed (only those), and the
  remaining real field names are passed through to Django's `save`.

### Introspection helpers (module-level)

- **`get_all_child_relations(model)`** — list the reverse relation objects for
  every `ParentalKey` pointing at `model`, **including** those declared on
  ancestor models. Each entry behaves like a Django relation (`.name`,
  `.get_accessor_name()`, `.related_model`, `.field`).
- **`get_all_child_m2m_relations(model)`** — list the `ParentalManyToManyField`
  instances on `model` (including inherited ones).

### Serialization

- **`serializable_data()`** — return a JSON-ready dict containing `"pk"`, every
  serializable concrete field, each child relation under its accessor name as a
  list of the children's serialized data (recursing into clusterable children),
  and each parental-m2m field as a list of related primary keys. The concrete
  fields cover the model's **full** concrete field set, **including** fields
  inherited from a multi-table-inheritance parent (e.g. a `Restaurant` whose
  `name` is declared on its `Place` superclass serializes `name` too) — not only
  the fields declared directly on the model. Fields/relations declared
  `serialize=False` are omitted. Each field appears keyed by its **field name**
  (not its database `attname`); a foreign key therefore appears under the field
  name (e.g. `"band"`, not `"band_id"`) with its stored primary-key value (or
  `None`) as the value. For a multi-table-inheritance child, `"pk"` is the
  inherited primary key value (the same id shared up the inheritance chain).
- **`to_json()`** — `json.dumps(serializable_data(), cls=DjangoJSONEncoder)`.
- **`from_serializable_data(cls, data, check_fks=True, strict_fks=False)`** /
  **`from_json(cls, json_data, ...)`** (classmethods) — rebuild an instance
  (setting its pk, and for multi-table inheritance writing that same id to
  every primary-key attribute up the chain — each `*_ptr_id` parent link **and
  the root model's own primary-key attribute**) and its child relations. When
  `check_fks` is true and a referenced foreign key no longer exists in the
  database, resolve by `on_delete`:
  `SET_NULL` → set the FK to `None`; `CASCADE` on a **child** object → drop that
  child; a dangling FK on the **base** object → nullify it, unless `strict_fks`
  is true and the FK is `CASCADE`, in which case the whole object deserializes to
  `None`. Children are re-sorted by their `Meta.ordering`.
- Datetimes: naive datetimes are interpreted in the project's current time zone
  and stored as **UTC** (ISO string ending in `Z`); aware datetimes are converted
  to UTC; on deserialization a stored datetime is converted back to the local
  zone. `None` datetimes round-trip as `null`.
- `FileField` contents survive a `to_json()` / `from_json()` round-trip.

### Copying

- **`copy_cluster(exclude_fields=None)`** — return `(copy, child_object_map)`
  where `copy` is an **unsaved** deep copy carrying all field data, child
  relations (recursively, with fresh — i.e. `None` — primary keys) and parental
  m2m relations (non-parental m2m is not copied). The map is as for
  `copy_all_child_relations` below.
- **`copy_child_relation(child_relation, target, commit=False, append=False)`** —
  copy the children of one relation (named by accessor string or relation object,
  must be a `ParentalKey` relation) onto `target`. By default it **overwrites**
  the target relation (clears it first); `append=True` keeps the target's existing
  children. `commit=True` saves the copied children immediately, raising
  `IntegrityError` if `target` is unsaved. Returns a dict mapping
  `(child_relation, old_pk) -> new_object` for each source child that had a pk,
  and `(child_relation, None) -> [new_object, ...]` (a list) for source children
  without a pk.
- **`copy_all_child_relations(target, exclude=None, commit=False, append=False)`**
  — apply `copy_child_relation` to every child relation except accessor names in
  `exclude`; returns the merged map.

---

## 5. Forms and formsets (`modelcluster.forms`)

- **`transientmodelformset_factory(model, formset=..., **kwargs)`** — like
  Django's `modelformset_factory`, but the formset does not assume its initial
  instances exist in the database (it tolerates blank/absent PKs). Its
  `save(commit=False)` returns the changed/added instances without writing.
- **`childformset_factory(parent_model, model, form=ModelForm, formset=..., fk_name=None, fields=None, exclude=None, extra=3, can_order=False, can_delete=True, max_num=None, validate_max=False, min_num=None, validate_min=False, widgets=None, inherit_kwargs=None, formsets=None, exclude_formsets=None, formfield_callback=None)`**
  — build a formset bound to a parent instance via its `ParentalKey`. The
  parent's FK is auto-excluded. `instance=parent` exposes existing children plus
  `extra` blank forms. `save(commit=False)` stages adds/edits/deletes onto the
  parent's in-memory relation (so `parent.<rel>.commit()` or `parent.save()`
  applies them); `save(commit=True)` commits immediately. `max_num`/`min_num` are
  only enforced for validation when `validate_max`/`validate_min` are set (failing
  with non-form errors coded `"too_many_forms"` / `"too_few_forms"`). When the
  child model defines a `sort_order_field`, ordering is enabled and the
  submitted `ORDER` values are written to that field on save. Passing
  `form=ClusterForm` with `formsets=[...]` produces **nested** child formsets.
  Like `transientmodelformset_factory` / Django's `modelformset_factory` (and
  unlike Django's inline formsets, which key on the relation accessor name), a
  formset built by `childformset_factory` uses the default `"form"` prefix for
  its bound data when no explicit `prefix=` is given — so submitted data is keyed
  `form-TOTAL_FORMS`, `form-0-<field>`, … (`ClusterForm` still keys its own
  managed child formsets by each relation's accessor name).
- **`ClusterForm`** — a `ModelForm` subclass that automatically manages child
  formsets for its model's child relations, configured via its inner `Meta`:
  - `Meta.formsets` — which child relations get formsets. May be a list/tuple of
    accessor names, or a dict mapping accessor name → options (e.g.
    `{"fields": [...]}`, `{"widgets": {...}}`, `{"form": SomeClusterForm}`,
    `{"formset_name": "records"}`, `{"inherit_kwargs": [...]}`, and
    `{"formsets": [...]}` / `{"exclude_formsets": [...]}` for nesting). With no
    `formsets`/`exclude_formsets` specified, **no** child formsets are built.
  - `Meta.exclude_formsets` — build formsets for all child relations except these.
  - `Meta.widgets` — may include a child-relation key mapping to that formset's
    widget overrides.
  - Child relations inherited from a model **superclass** are included.
  - The form **class** exposes a `formsets` attribute — a dict mapping each
    managed child-relation name to its generated formset *class* (an empty dict
    when none are configured, so `bool(MyForm.formsets)` reflects whether any were
    built). Each **instance** exposes `formsets` as the corresponding
    *instantiated* child formsets, keyed the same way (e.g.
    `form.formsets["members"]`).
  - Each child formset uses **3** extra forms by default.
  - `is_valid()` is true only when the parent form and every child formset are
    valid; child unique constraints (`unique_together`, `UniqueConstraint`) are
    enforced across the submitted child forms; child forms marked for deletion
    skip validation.
  - `as_p()` renders the parent form followed by its formsets and returns a
    `SafeString`. `media` aggregates parent + child widget media. `is_multipart()`
    is true if the parent or any child form needs multipart encoding.
  - Constructor kwargs do **not** propagate to child forms unless their names are
    listed in a formset's `inherit_kwargs`.
  - `save(commit=True)` saves the instance and its formsets and m2m data; with
    `commit=False` it applies all changes to the in-memory instance only and
    exposes a deferred `save_m2m()` for the standard (non-parental) m2m fields —
    parental m2m and tag fields are applied immediately in memory and committed
    with the instance's own `save()`.
- A `clusterform_factory(model, form=ClusterForm, **kwargs)` helper analogous to
  Django's `modelform_factory` is expected for completeness.

---

## 6. Cluster-aware taggit support (`modelcluster.contrib.taggit`)

**`ClusterTaggableManager`** — a `django-taggit` `TaggableManager` subclass whose
tags are managed **in memory** (via an underlying `ParentalKey` tagged-item
relation) until the owning instance is saved. It is declared like taggit's
manager: `tags = ClusterTaggableManager(through=TaggedThing, blank=True)`, where
the through model's `content_object` is a `ParentalKey` to a `ClusterableModel`.

It must support, including on an **unsaved** instance:

- `instance.tags.add("a", "b")`, `.remove("a")`, `.clear()`,
  `.set(["a", "b"])`, `.count()`, `.all()` (yielding taggit `Tag` instances) —
  all without touching the database until `instance.save()`.
- Adding a non-string / non-Tag value (e.g. an integer) raises `ValueError`.
- `prefetch_related("tags")` over a queryset of owners works.
- The field integrates with `ClusterForm` (a comma-separated tag string in form
  data creates/sets the tags). A plain taggit `TaggableManager` on a model must
  also continue to work through `ClusterForm` (without the in-memory behavior).

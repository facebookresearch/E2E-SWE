"""
Integration tests for pyrsistent — persistent/immutable data structures.
Tests exercise PVector, PMap, PSet, PList, PBag, PDeque, PRecord, PClass,
immutable, transformations, freeze/thaw/mutant, checked types, and get_in.
"""

import pickle

import pytest

# Module-level classes needed for pickle roundtrip tests
from pyrsistent import PRecord, PClass, field as _field
from pyrsistent import CheckedPVector, CheckedPMap, CheckedPSet


class _PicklePR(PRecord):
    x = _field(type=int)
    y = _field(type=str)


class _PicklePC(PClass):
    a = _field(type=int)
    b = _field(type=str)


class _PickleIV(CheckedPVector):
    __type__ = int


class _PickleSM(CheckedPMap):
    __key_type__ = str
    __value_type__ = int


class _PickleIS(CheckedPSet):
    __type__ = int


# =============================================================================
# PVector — Persistent Vector
# =============================================================================


class TestPVector:
    """Tests for PVector covering creation, persistence, evolver, and protocols."""

    def test_pvector_construction_persistence_and_protocols(self):
        """Build PVectors via pvector/v, verify persistence on set, and confirm hashing."""
        from pyrsistent import pvector, v
        from collections.abc import Sequence, Hashable

        vec = pvector(range(10000))
        assert len(vec) == 10000
        assert vec[0] == 0
        assert vec[9999] == 9999
        assert vec[-1] == 9999
        assert vec[5000] == 5000

        # Shorthand factory
        small = v(1, 2, 3)
        assert list(small) == [1, 2, 3]

        # Persistence: set returns new vector, original unchanged
        original = pvector(range(100))
        modified = original.set(50, "changed")
        assert original[50] == 50
        assert modified[50] == "changed"
        assert len(original) == len(modified) == 100

        # Hashable
        assert hash(pvector([1, 2, 3])) == hash(pvector([1, 2, 3]))

        # Pickle roundtrip
        assert pickle.loads(pickle.dumps(vec)) == vec

        # Out-of-bounds access raises IndexError
        with pytest.raises(IndexError):
            vec[10000]
        with pytest.raises(IndexError):
            vec[-10001]
        with pytest.raises(IndexError):
            small.set(10, 99)

    def test_pvector_slicing_concat_repeat_count_index(self):
        """PVector supports slicing, concatenation, repetition, count, and index."""
        from pyrsistent import pvector

        vec = pvector([10, 20, 30, 20, 40])
        assert list(vec[1:3]) == [20, 30]
        assert list(vec[:2]) == [10, 20]
        assert list(vec[::2]) == [10, 30, 40]

        assert 20 in vec
        assert vec.count(20) == 2
        assert vec.index(30) == 2

        # Concatenation
        concat = vec + pvector([50, 60])
        assert list(concat) == [10, 20, 30, 20, 40, 50, 60]

        # Repetition
        rep = pvector([1, 2]) * 3
        assert list(rep) == [1, 2, 1, 2, 1, 2]

    def test_pvector_extend_delete_mset(self):
        """extend appends iterable, delete removes by index, mset sets multiple indices."""
        from pyrsistent import pvector

        vec = pvector([1, 2, 3])
        extended = vec.extend([4, 5, 6])
        assert list(extended) == [1, 2, 3, 4, 5, 6]

        deleted = extended.delete(2)
        assert list(deleted) == [1, 2, 4, 5, 6]

        # delete negative index
        deleted_neg = pvector([10, 20, 30]).delete(-1)
        assert list(deleted_neg) == [10, 20]

        multi = pvector([10, 20, 30]).mset(0, 100, 2, 300)
        assert list(multi) == [100, 20, 300]

    def test_pvector_evolver_batch_mutations(self):
        """Evolver enables mutable batch updates: __setitem__, append, extend, __delitem__."""
        from pyrsistent import pvector

        vec = pvector(range(1000))
        evolver = vec.evolver()
        for i in range(0, 1000, 2):
            evolver[i] = i * 10
        evolver.append(9999)
        evolver.extend([8888, 7777])
        del evolver[1]
        result = evolver.persistent()

        assert result[0] == 0  # 0 * 10
        assert result[1] == 20  # was index 2 (shifted after del)
        assert len(result) == 1002  # 1000 - 1 + 1 + 2

        # Original unchanged, including at indices the evolver overwrote
        assert vec[0] == 0
        assert vec[1] == 1
        assert vec[2] == 2
        assert vec[500] == 500
        assert len(vec) == 1000


# =============================================================================
# PMap — Persistent Map (HAMT)
# =============================================================================


class TestPMap:
    """Tests for PMap covering CRUD, persistence, evolver, keys-as-pset, and hashing."""

    def test_pmap_crud_and_mapping_protocol(self):
        """PMap supports set, remove, discard, update, and mapping/hashable behavior."""
        from pyrsistent import pmap, m, pset

        pm = pmap({"a": 1, "b": 2, "c": 3})
        assert pm["a"] == 1
        assert len(pm) == 3
        assert "b" in pm

        # Shorthand
        pm2 = m(x=10, y=20)
        assert pm2["x"] == 10

        # Persistence
        original = pmap({"a": 1, "b": 2})
        with_c = original.set("c", 3)
        without_b = original.remove("b")
        assert "c" not in original
        assert with_c["c"] == 3
        assert "b" not in without_b
        assert "b" in original

        # discard
        assert pm.discard("nonexistent") == pm
        assert pm.discard("a") == pmap({"b": 2, "c": 3})

        # update
        merged = original.update({"b": 20, "d": 4})
        assert merged["b"] == 20
        assert merged["d"] == 4

        # keys returns PSet
        keys = pm.keys()
        assert isinstance(keys, type(pset()))
        assert keys == pset({"a", "b", "c"})

        # remove missing raises KeyError
        with pytest.raises(KeyError):
            pm.remove("nonexistent")

        # Pickle roundtrip
        assert pickle.loads(pickle.dumps(pm)) == pm

        # Equality independent of insertion order
        m1 = pmap({"a": 1, "b": 2, "c": 3})
        m2 = pmap({"c": 3, "a": 1, "b": 2})
        assert m1 == m2
        assert hash(m1) == hash(m2)
        assert m1 == {"a": 1, "b": 2, "c": 3}

    def test_pmap_evolver(self):
        """PMap evolver for batch mutations: __setitem__, __delitem__, remove, persistent."""
        from pyrsistent import pmap

        pm = pmap({"a": 1, "b": 2})
        evolver = pm.evolver()
        evolver["c"] = 3
        evolver["a"] = 10
        del evolver["b"]
        result = evolver.persistent()

        assert result == pmap({"a": 10, "c": 3})
        assert pm == pmap({"a": 1, "b": 2})

    def test_pmap_evolver_at_scale_and_update_with_pmap(self):
        """PMap evolver at scale (5K entries); update merging two PMaps."""
        from pyrsistent import pmap

        # Build large map via evolver
        evolver = pmap().evolver()
        for i in range(5000):
            evolver[f"k{i}"] = i
        pm = evolver.persistent()
        assert len(pm) == 5000
        assert pm["k2500"] == 2500

        # Batch delete via evolver
        ev2 = pm.evolver()
        for i in range(0, 5000, 2):
            del ev2[f"k{i}"]
        pm2 = ev2.persistent()
        assert len(pm2) == 2500
        assert "k0" not in pm2
        assert pm2["k1"] == 1

        # Original unchanged
        assert len(pm) == 5000

        # update with another PMap
        extra = pmap({"k0": 999, "new_key": 42})
        merged = pm2.update(extra)
        assert merged["k0"] == 999
        assert merged["new_key"] == 42
        assert merged["k1"] == 1

    def test_pmap_evolver_remove_nonexistent_key(self):
        """Deleting a non-existent key from a PMap evolver raises KeyError,
        exercising the evolver's distinct error-handling path separate from
        PMap.remove() on a persistent map."""
        from pyrsistent import pmap

        pm = pmap({"a": 1, "b": 2, "c": 3})
        evolver = pm.evolver()

        # Successful mutation first
        evolver["d"] = 4
        del evolver["a"]

        # Now try to remove a key that never existed
        with pytest.raises(KeyError):
            del evolver["nonexistent"]

        # Also test removing a key that was already removed from the evolver
        with pytest.raises(KeyError):
            del evolver["a"]

        # The evolver should still be usable after the errors
        result = evolver.persistent()
        assert result == pmap({"b": 2, "c": 3, "d": 4})
        assert "a" not in result


# =============================================================================
# PSet — Persistent Set
# =============================================================================


class TestPSet:
    """Tests for PSet with set algebra and persistence."""

    def test_pset_operations_and_algebra(self):
        """PSet supports add, remove, discard, set algebra, operators, and hashing."""
        from pyrsistent import pset, s

        ps = pset([1, 2, 3, 4, 5])
        assert len(ps) == 5
        assert 3 in ps

        # add/remove persistence
        added = ps.add(6)
        assert 6 in added
        assert 6 not in ps

        removed = ps.remove(3)
        assert 3 not in removed
        assert 3 in ps

        # discard does not raise
        assert ps.discard(99) == ps

        # remove raises KeyError
        with pytest.raises(KeyError):
            ps.remove(99)

        # Set algebra
        other = pset([4, 5, 6, 7])
        assert ps.union(other) == pset([1, 2, 3, 4, 5, 6, 7])
        assert (ps | other) == pset([1, 2, 3, 4, 5, 6, 7])
        assert ps.intersection(other) == pset([4, 5])
        assert (ps & other) == pset([4, 5])
        assert ps.difference(other) == pset([1, 2, 3])
        assert (ps - other) == pset([1, 2, 3])
        assert ps.symmetric_difference(other) == pset([1, 2, 3, 6, 7])
        assert (ps ^ other) == pset([1, 2, 3, 6, 7])

        # Shorthand
        assert s(1, 2, 3) == pset([1, 2, 3])

        # issubset / issuperset
        assert pset([1, 2]).issubset(ps)
        assert ps.issuperset(pset([1, 2]))

        # Pickle roundtrip
        assert pickle.loads(pickle.dumps(ps)) == ps

        # Evolver for batch mutations
        e = ps.evolver()
        e.add(6)
        e.add(7)
        e.remove(2)
        evolver_result = e.persistent()
        assert evolver_result == pset([1, 3, 4, 5, 6, 7])
        assert ps == pset([1, 2, 3, 4, 5])  # original unchanged

    def test_pset_hash_collision_stress(self):
        """Create a PSet with many elements sharing hash prefixes using a custom
        __hash__ class. This forces real HAMT collision node handling since PSet
        is built on PMap — a naive set wrapper would fail on collision groups."""
        from pyrsistent import pset

        class CollidingKey:
            def __init__(self, val, group):
                self.val = val
                self.group = group

            def __hash__(self):
                return self.group  # All items in same group share hash

            def __eq__(self, other):
                return (isinstance(other, CollidingKey)
                        and self.val == other.val
                        and self.group == other.group)

            def __repr__(self):
                return f"CK({self.val},{self.group})"

        # 100 elements across 5 hash groups (20 per group)
        elements = [CollidingKey(i, i % 5) for i in range(100)]
        ps = pset(elements)
        assert len(ps) == 100

        # Membership checks across different collision groups
        assert CollidingKey(0, 0) in ps
        assert CollidingKey(99, 4) in ps
        assert CollidingKey(200, 0) not in ps

        # Remove from a collision group and verify persistence
        ps2 = ps.remove(CollidingKey(50, 0))
        assert len(ps2) == 99
        assert CollidingKey(50, 0) not in ps2
        assert CollidingKey(50, 0) in ps  # original unchanged

        # Add a new element to a collision group
        ps3 = ps.add(CollidingKey(200, 0))
        assert len(ps3) == 101
        assert CollidingKey(200, 0) in ps3
        assert CollidingKey(200, 0) not in ps  # original unchanged


# =============================================================================
# PList — Persistent Singly-Linked List
# =============================================================================


class TestPList:
    """Tests for PList including cons, traversal, remove, and edge cases."""

    def test_plist_cons_traversal_remove_mcons_reverse_split(self):
        """PList supports cons, first/rest, remove, mcons, reverse, split, and hashing."""
        from pyrsistent import plist, l
        from collections.abc import Sequence, Hashable

        pl = plist([1, 2, 3])
        assert isinstance(pl, Sequence)
        assert isinstance(pl, Hashable)
        assert pl.first == 1
        assert pl.rest.first == 2
        assert pl.rest.rest.first == 3
        assert list(pl) == [1, 2, 3]
        assert len(pl) == 3

        # cons prepends
        prepended = pl.cons(0)
        assert prepended.first == 0
        assert list(prepended) == [0, 1, 2, 3]

        # Shorthand
        assert list(l(10, 20)) == [10, 20]

        # Empty
        empty = plist()
        assert not empty
        assert bool(pl)

        # remove
        removed = pl.remove(2)
        assert list(removed) == [1, 3]

        # remove nonexistent raises ValueError
        with pytest.raises(ValueError):
            pl.remove(99)

        # indexing
        assert pl[0] == 1
        assert pl[2] == 3
        assert pl[-1] == 3

        # hash
        assert hash(plist([1, 2])) == hash(plist([1, 2]))

        # Pickle roundtrip
        assert pickle.loads(pickle.dumps(pl)) == pl

        # mcons: prepend multiple elements (iterable items prepended in reverse order)
        mc = pl.mcons([10, 20])
        assert list(mc) == [20, 10, 1, 2, 3]
        assert list(pl) == [1, 2, 3]  # original unchanged

        # reverse: returns reversed plist
        rev = pl.reverse()
        assert list(rev) == [3, 2, 1]
        assert list(pl) == [1, 2, 3]  # original unchanged

        # split: divide at index into (left, right)
        left, right = pl.split(1)
        assert list(left) == [1]
        assert list(right) == [2, 3]

        # split at 0: empty left, full right
        left0, right0 = pl.split(0)
        assert list(left0) == []
        assert list(right0) == [1, 2, 3]

        # split at end: full left, empty right
        left3, right3 = pl.split(3)
        assert list(left3) == [1, 2, 3]
        assert list(right3) == []


# =============================================================================
# PBag — Persistent Multiset
# =============================================================================


class TestPBag:
    """Tests for PBag multiset operations."""

    def test_pbag_count_add_remove_update_and_operators(self):
        """PBag tracks counts, supports add/remove, update, and bag arithmetic operators."""
        from pyrsistent import pbag, b

        bag = pbag([1, 1, 2, 3, 3, 3])
        assert bag.count(1) == 2
        assert bag.count(3) == 3
        assert bag.count(99) == 0
        assert len(bag) == 6

        added = bag.add(1)
        assert added.count(1) == 3

        removed = bag.remove(3)
        assert removed.count(3) == 2
        assert len(removed) == 5

        # remove nonexistent raises KeyError
        with pytest.raises(KeyError):
            bag.remove(99)

        # Shorthand
        assert b(1, 1, 2).count(1) == 2

        # PBag supports eq
        assert pbag([1, 2, 2]) == pbag([2, 1, 2])

        # PBag supports hash
        assert hash(pbag([1, 2])) == hash(pbag([2, 1]))

        # Pickle roundtrip
        assert pickle.loads(pickle.dumps(bag)) == bag

        # PBag supports iteration (yields all elements including duplicates)
        assert sorted(bag) == [1, 1, 2, 3, 3, 3]

        # update: adds all elements from iterable
        updated = bag.update([4, 4, 1])
        assert updated.count(1) == 3
        assert updated.count(4) == 2
        assert len(updated) == 9  # 6 original + 3 new
        assert len(bag) == 6  # original unchanged

        b1 = pbag([1, 1, 2])
        b2 = pbag([1, 2, 3])

        # __add__: sum of counts
        sum_bag = b1 + b2
        assert sum_bag.count(1) == 3
        assert sum_bag.count(2) == 2
        assert sum_bag.count(3) == 1
        assert len(sum_bag) == 6

        # __sub__: subtract counts (clamp at 0, drop zero-count elements)
        subtracted = b1 - b2
        assert subtracted.count(1) == 1
        assert subtracted.count(2) == 0
        assert sorted(subtracted) == [1]

        # __or__: union = max of counts
        union = b1 | b2
        assert union.count(1) == 2
        assert union.count(2) == 1
        assert union.count(3) == 1
        assert len(union) == 4

        # __and__: intersection = min of counts
        inter = b1 & b2
        assert inter.count(1) == 1
        assert inter.count(2) == 1
        assert inter.count(3) == 0
        assert len(inter) == 2


# =============================================================================
# PDeque — Persistent Double-Ended Queue
# =============================================================================


class TestPDeque:
    """Tests for PDeque operations and bounded deque behavior."""

    def test_pdeque_full_api(self):
        """PDeque supports append/pop, extend/extendleft, count, reverse, rotate, and bounded overflow."""
        from pyrsistent import pdeque, dq
        from collections.abc import Sequence, Hashable

        dq1 = pdeque([1, 2, 3])
        assert isinstance(dq1, Sequence)
        assert isinstance(dq1, Hashable)
        assert dq1.left == 1
        assert dq1.right == 3
        assert len(dq1) == 3
        assert list(dq1) == [1, 2, 3]

        # append/appendleft
        appended = dq1.append(4)
        assert appended.right == 4
        assert list(appended) == [1, 2, 3, 4]

        left_added = dq1.appendleft(0)
        assert left_added.left == 0
        assert list(left_added) == [0, 1, 2, 3]

        # pop (from right)
        popped = dq1.pop()
        assert list(popped) == [1, 2]
        assert popped.right == 2

        # popleft
        popped_left = dq1.popleft()
        assert list(popped_left) == [2, 3]
        assert popped_left.left == 2

        # pop with count
        popped_2 = pdeque([1, 2, 3, 4, 5]).pop(2)
        assert list(popped_2) == [1, 2, 3]

        # popleft with count
        popped_left_2 = pdeque([1, 2, 3, 4, 5]).popleft(2)
        assert list(popped_left_2) == [3, 4, 5]

        # remove
        removed = dq1.remove(2)
        assert list(removed) == [1, 3]

        # extend: append multiple from right
        extended = dq1.extend([4, 5])
        assert list(extended) == [1, 2, 3, 4, 5]
        assert list(dq1) == [1, 2, 3]  # original unchanged

        # extendleft: prepend multiple from left (reversed order, like collections.deque)
        ext_left = dq1.extendleft([0, -1])
        assert list(ext_left) == [-1, 0, 1, 2, 3]

        # count: count occurrences
        d2 = pdeque([1, 2, 1, 3, 1])
        assert d2.count(1) == 3
        assert d2.count(5) == 0

        # reverse: reverse the deque
        rev = dq1.reverse()
        assert list(rev) == [3, 2, 1]
        assert list(dq1) == [1, 2, 3]  # original unchanged

        # rotate positive: move elements from right to left
        d3 = pdeque([1, 2, 3, 4, 5])
        rot1 = d3.rotate(1)
        assert list(rot1) == [5, 1, 2, 3, 4]

        rot2 = d3.rotate(2)
        assert list(rot2) == [4, 5, 1, 2, 3]

        # rotate negative: move elements from left to right
        rot_neg1 = d3.rotate(-1)
        assert list(rot_neg1) == [2, 3, 4, 5, 1]

        rot_neg2 = d3.rotate(-2)
        assert list(rot_neg2) == [3, 4, 5, 1, 2]

        # Bounded deque: append drops from opposite end
        bounded = pdeque([1, 2, 3], maxlen=3)
        assert bounded.maxlen == 3
        overflow = bounded.append(4)
        assert len(overflow) == 3
        assert overflow.left == 2
        assert list(overflow) == [2, 3, 4]

        # Bounded appendleft drops from right
        overflow_left = bounded.appendleft(0)
        assert len(overflow_left) == 3
        assert overflow_left.right == 2
        assert list(overflow_left) == [0, 1, 2]

        # extend on bounded deque respects maxlen
        bd = pdeque([1, 2, 3], maxlen=4)
        bd_ext = bd.extend([4, 5])
        assert list(bd_ext) == [2, 3, 4, 5]
        assert bd_ext.maxlen == 4

        # Shorthand
        assert list(dq(1, 2, 3)) == [1, 2, 3]

        # Hash and pickle roundtrip
        assert hash(pdeque([1, 2])) == hash(pdeque([1, 2]))
        assert pickle.loads(pickle.dumps(dq1)) == dq1


# =============================================================================
# PRecord — Typed Record (PMap subclass)
# =============================================================================


class TestPRecord:
    """Tests for PRecord: field types, invariants, factories, serializers, inheritance."""

    def test_precord_creation_typing_and_persistence(self):
        """PRecord enforces field types, supports set() for persistence, and is a PMap."""
        from pyrsistent import PRecord, field, PTypeError

        class Person(PRecord):
            name = field(type=str, mandatory=True)
            age = field(type=int, initial=0)

        p = Person(name="Alice", age=30)
        assert p.name == "Alice"
        assert p.age == 30
        assert p["name"] == "Alice"

        # set returns new record, original unchanged
        p2 = p.set(age=31)
        assert p2.age == 31
        assert p.age == 30

        # set with positional args (k, v)
        p3 = p.set("name", "Bob")
        assert p3.name == "Bob"

        # Default initial value
        p4 = Person(name="Charlie")
        assert p4.age == 0

        # Type violation
        with pytest.raises(PTypeError):
            Person(name="Alice", age="not_an_int")

        # Missing mandatory
        from pyrsistent import InvariantException
        with pytest.raises(InvariantException):
            Person(age=5)

        # Undeclared field
        with pytest.raises(AttributeError):
            Person(name="Alice", z=5)

        # Direct assignment blocked
        with pytest.raises(AttributeError):
            p.name = "Hacked"

        # Evolver batch mutations
        class R(PRecord):
            a = field()
            b = field()

        r = R(a=1, b=2)
        e = r.evolver()
        e["a"] = 10
        e["b"] = 20
        evolver_result = e.persistent()
        assert evolver_result == {"a": 10, "b": 20}
        assert r == {"a": 1, "b": 2}

    def test_precord_invariants_and_factory(self):
        """PRecord supports field invariants, factories, global invariants, and serializers."""
        from pyrsistent import PRecord, field, InvariantException

        class Validated(PRecord):
            __invariant__ = lambda r: (r.x <= r.y, 'x must be <= y')
            x = field(type=int, invariant=lambda x: (x >= 0, 'x negative'))
            y = field(type=int, mandatory=True)

        v = Validated(x=1, y=2)
        assert v.x == 1
        assert v.y == 2

        # Field invariant violation
        try:
            Validated(x=-1, y=2)
            assert False
        except InvariantException as e:
            assert 'x negative' in e.invariant_errors

        # Global invariant violation
        try:
            Validated(x=5, y=1)
            assert False
        except InvariantException as e:
            assert 'x must be <= y' in e.invariant_errors

        # Factory
        class WithFactory(PRecord):
            x = field(type=int, factory=int)

        assert WithFactory(x=2.5) == {"x": 2}

        # Serializer
        class WithSerializer(PRecord):
            x = field(serializer=lambda fmt, v: v * 2 if fmt == 'double' else v)

        ws = WithSerializer(x=5)
        assert ws.serialize('double') == {'x': 10}
        assert ws.serialize('other') == {'x': 5}

        # InvariantException carries invariant_errors and missing_fields tuples
        ie = InvariantException(
            error_codes=('err1', 'err2'),
            missing_fields=('Field.a', 'Field.b')
        )
        assert ie.invariant_errors == ('err1', 'err2')
        assert ie.missing_fields == ('Field.a', 'Field.b')
        assert 'err1' in str(ie)
        assert 'Field.a' in str(ie)

    def test_precord_inheritance_and_create(self):
        """PRecord supports inheritance and the create() class method with ignore_extra."""
        from pyrsistent import PRecord, field

        class Base(PRecord):
            x = field(type=int)

        class Child(Base):
            y = field(type=str)

        c = Child(x=1, y="hello")
        assert isinstance(c, Child)
        assert isinstance(c, Base)
        assert c == {"x": 1, "y": "hello"}

        # create with ignore_extra
        c2 = Child.create({"x": 1, "y": "hello", "z": "extra"}, ignore_extra=True)
        assert c2.x == 1
        assert c2.y == "hello"

        # create without ignore_extra raises on extra fields
        with pytest.raises(AttributeError):
            Child.create({"x": 1, "y": "hello", "z": "extra"})

        # create is idempotent
        assert Child.create(c) is c

# =============================================================================
# PClass — Typed Immutable Object
# =============================================================================


class TestPClass:
    """Tests for PClass: fields, invariants, evolver, remove, serialize, transform."""

    def test_pclass_creation_immutability_and_set(self):
        """PClass enforces field types, is immutable, supports set() with persistence."""
        from collections.abc import Hashable

        from pyrsistent import PClass, field, InvariantException

        class Point(PClass):
            x = field(type=(int, float), mandatory=True)
            y = field(type=(int, float), mandatory=True)

        pt = Point(x=1, y=2)
        assert pt.x == 1
        assert pt.y == 2
        assert isinstance(pt, Hashable)

        # set returns new instance
        pt2 = pt.set(x=10)
        assert pt2.x == 10
        assert pt.x == 1

        # set with positional args
        pt3 = pt.set('x', 20)
        assert pt3.x == 20

        # Immutable: __setattr__ raises
        with pytest.raises(AttributeError):
            pt.x = 100

        # Immutable: __delattr__ raises
        with pytest.raises(AttributeError):
            del pt.x

        # Type violation
        with pytest.raises(TypeError):
            Point(x='a', y=2)

        # Missing mandatory
        with pytest.raises(InvariantException):
            Point(y=2)

        # Undeclared fields
        with pytest.raises(AttributeError):
            Point(x=1, y=2, z=3)

        # Equality
        assert Point(x=1, y=2) == Point(x=1, y=2)
        assert Point(x=1, y=2) != Point(x=3, y=2)

        # Hash
        d = {pt: "point"}
        assert d[Point(x=1, y=2)] == "point"

        # optional() allows None as valid value
        from pyrsistent import optional

        class MaybePoint(PClass):
            x = field(type=int, mandatory=True)
            label = field(type=optional(str))

        mp1 = MaybePoint(x=1, label="hello")
        assert mp1.label == "hello"
        mp2 = MaybePoint(x=1, label=None)
        assert mp2.label is None
        with pytest.raises(TypeError):
            MaybePoint(x=1, label=42)

    def test_pclass_invariants_factory_serializer(self):
        """PClass supports field invariants, global invariants, factories, and serializers."""
        from pyrsistent import PClass, field, InvariantException
        import math

        class UnitCirclePoint(PClass):
            __invariant__ = lambda cp: (0.99 < math.sqrt(cp.x**2 + cp.y**2) < 1.01,
                                        "Point not on unit circle")
            x = field(type=float)
            y = field(type=float)

        UnitCirclePoint(x=1.0, y=0.0)
        with pytest.raises(InvariantException):
            UnitCirclePoint(x=1.0, y=1.0)

        # Field factory
        class Squared(PClass):
            x = field(factory=lambda x: x ** 2)
            y = field()

        sp = Squared(x=3, y=10)
        assert sp.x == 9
        assert sp.y == 10

        # Factory re-applied on set
        sp2 = sp.set(x=4)
        assert sp2.x == 16

        # Serializer
        class WithSer(PClass):
            x = field(type=int)
            y = field(type=int, serializer=lambda fmt, y: fmt(y))

        ws = WithSer(x=1, y=2)
        assert ws.serialize(format=lambda v: v * 3) == {'x': 1, 'y': 6}

    def test_pclass_evolver_and_remove(self):
        """PClass evolver supports chained set/remove, dot notation access."""
        from pyrsistent import PClass, field, InvariantException

        class P(PClass):
            x = field(type=int, mandatory=True)
            y = field(type=int)
            z = field(type=int, initial=0)

        p = P(x=1, y=2)

        # Evolver without changes returns same instance
        assert p.evolver().persistent() is p

        # Evolver with changes
        e = p.evolver()
        e.x = 10
        assert e.x == 10
        result = e.persistent()
        assert result.x == 10
        assert result.y == 2

        # Chained set and remove
        p2 = p.evolver().set('x', 3).remove('y').persistent()
        assert p2 == P(x=3)

        # remove nonexistent raises
        with pytest.raises(AttributeError):
            p.remove('nonexistent')

        # remove mandatory raises InvariantException
        with pytest.raises(InvariantException):
            p.remove('x')

    def test_pclass_nested_create_and_transform(self):
        """PClass.create builds nested structures from dicts; transform does deep updates."""
        from pyrsistent import PClass, field

        class Inner(PClass):
            a = field(type=int)
            b = field(type=int)

        class Outer(PClass):
            inner = field(type=Inner)
            label = field(type=str)

        source = {"inner": {"a": 1, "b": 2}, "label": "test"}
        o = Outer.create(source)
        assert isinstance(o.inner, Inner)
        assert o.inner.a == 1
        assert o.label == "test"

        # Transform nested path
        o2 = o.transform(['inner', 'a'], 99)
        assert o2.inner.a == 99
        assert o.inner.a == 1  # original unchanged

    def test_pclass_nested_serialize_with_per_field_serializers(self):
        """serialize() recurses correctly through nested PClass fields, applying
        per-field serializers at each level. This exercises the recursive serialize
        dispatch — a flat dict dump would miss inner serializer transformations."""
        from pyrsistent import PClass, field

        class Inner(PClass):
            a = field(
                type=int,
                serializer=lambda fmt, v: v * 10 if fmt == "scaled" else v,
            )
            b = field(type=str)

        class Middle(PClass):
            inner = field(type=Inner)
            label = field(
                type=str,
                serializer=lambda fmt, v: v.upper() if fmt == "scaled" else v,
            )

        class Outer(PClass):
            middle = field(type=Middle)
            count = field(type=int)

        o = Outer.create(
            {
                "middle": {"inner": {"a": 5, "b": "hello"}, "label": "test"},
                "count": 42,
            }
        )

        # With format="scaled", inner serializers should fire at each level
        result = o.serialize(format="scaled")
        assert result == {
            "middle": {
                "inner": {"a": 50, "b": "hello"},
                "label": "TEST",
            },
            "count": 42,
        }

        # Without a recognized format, serializers return values unchanged
        result_default = o.serialize()
        assert result_default["middle"]["inner"]["a"] == 5
        assert result_default["middle"]["label"] == "test"
        assert result_default["count"] == 42


# =============================================================================
# Transformations
# =============================================================================


class TestTransformations:
    """Tests for deep path-based transformations with predicates and helpers."""

    def test_transform_nested_pmap_with_inc_and_ny(self):
        """transform applies inc at nested paths; ny matches all keys;
        callable commands vs literal values; intermediate PMap creation."""
        from pyrsistent import pmap, inc, ny, freeze

        data = pmap({"a": pmap({"b": pmap({"c": 1})})})
        result = data.transform(["a", "b", "c"], inc)
        assert result["a"]["b"]["c"] == 2
        assert data["a"]["b"]["c"] == 1

        # ny matches all keys
        flat = pmap({"a": 1, "b": 2, "c": 3})
        all_inc = flat.transform([ny], inc)
        assert all_inc["a"] == 2
        assert all_inc["b"] == 3
        assert all_inc["c"] == 4

        # Callable command vs literal value
        m = pmap({"a": 5, "b": 10})
        # Literal replacement
        r_literal = m.transform(["a"], 99)
        assert r_literal["a"] == 99
        assert r_literal["b"] == 10
        # Lambda command applied to current value
        r_lambda = m.transform(["a"], lambda x: x * 2)
        assert r_lambda["a"] == 10
        assert r_lambda["b"] == 10
        # Nested lambda
        m2 = freeze({"outer": {"x": 3, "y": 7}})
        r_nested = m2.transform(["outer", "x"], lambda v: v ** 2)
        assert r_nested["outer"]["x"] == 9
        assert r_nested["outer"]["y"] == 7
        # Lambda returning a dict replaces (does not recurse into) the value
        r_dict = m.transform(["a"], lambda x: {"nested": x})
        assert r_dict["a"] == {"nested": 5}

        # Missing intermediate keys create new PMaps
        empty = pmap({})
        r_intermediate = empty.transform(["foo", "bar", "baz"], 7)
        assert r_intermediate == freeze({"foo": {"bar": {"baz": 7}}})

    def test_transform_pvector_with_index_path(self):
        """transform on PVector uses integer index as path element."""
        from pyrsistent import pvector, inc

        vec = pvector([10, 20, 30])
        result = vec.transform([1], inc)
        assert result[1] == 21
        assert vec[1] == 20

    def test_transform_with_predicate_and_discard(self):
        """transform supports lambda predicates and the discard command."""
        from pyrsistent import freeze, inc, discard

        # Lambda predicate
        m = freeze({"foo": {"bar": {"baz": 1}, "qux": {"baz": 1}}})
        result = m.transform(["foo", lambda x: x.startswith("b"), "baz"], inc)
        assert result["foo"]["bar"]["baz"] == 2
        assert result["foo"]["qux"]["baz"] == 1

        # discard removes elements
        m2 = freeze({"foo": {"bar": {"baz": 1}}})
        assert m2.transform(["foo", "bar", "baz"], discard) == freeze({"foo": {"bar": {}}})

        # discard on pvector
        m3 = freeze({"foo": [1, 2, 3]})
        assert m3.transform(["foo", 1], discard) == freeze({"foo": [1, 3]})

        # discard multiple elements from pvector
        v = freeze([0, 1, 2, 3, 4])
        assert v.transform([lambda i: i % 2 == 1], discard) == freeze([0, 2, 4])

    def test_transform_with_rex_matcher(self):
        """rex() provides regex-based key matching in transform paths."""
        from pyrsistent import freeze, inc, rex

        m = freeze({"foo": {"bar": {"baz": 1}, "bof": {"baz": 1}}})
        result = m.transform(["foo", rex("^bo.*"), "baz"], inc)
        assert result["foo"]["bar"]["baz"] == 1
        assert result["foo"]["bof"]["baz"] == 2

        # rex skips non-string keys
        m2 = freeze({"foo": 1, 5: 2})
        assert m2.transform([rex(".*")], 5) == freeze({"foo": 5, 5: 2})

    def test_transform_multiple_transformations(self):
        """Multiple transformation pairs applied in sequence."""
        from pyrsistent import freeze, inc

        v = freeze([1, 2])
        result = v.transform([2, "foo"], 3, [2, "foo"], inc)
        assert result == freeze([1, 2, {"foo": 4}])

    def test_transform_no_change_returns_same_object(self):
        """transform that makes no change returns the exact same object (identity)."""
        from pyrsistent import freeze, ny

        v = freeze([{"foo": 1}, {"bar": 2}])
        result = v.transform([ny, ny], lambda x: x)
        assert result is v

    def test_transform_key_value_predicate(self):
        """Binary predicates in transform receive both key and value."""
        from pyrsistent import freeze

        m = freeze({"foo": 1, "bar": 2})
        result = m.transform([lambda k, v: (k, v) == ("foo", 1)], lambda v: v * 3)
        assert result == freeze({"foo": 3, "bar": 2})


# =============================================================================
# Freeze / Thaw / mutant
# =============================================================================


class TestFreezeThaw:
    """Tests for freeze/thaw recursive conversion and the mutant decorator."""

    def test_freeze_and_thaw_roundtrip(self):
        """freeze converts dict/list/set to persistent; thaw converts back."""
        from pyrsistent import freeze, thaw, PMap, PVector, PSet
        import collections

        data = {"a": [1, 2, 3], "b": {"nested": True}, "c": {4, 5}}
        frozen = freeze(data)

        assert isinstance(frozen, PMap)
        assert isinstance(frozen["a"], PVector)
        assert isinstance(frozen["b"], PMap)
        assert isinstance(frozen["c"], PSet)
        assert frozen["b"]["nested"] is True
        assert list(frozen["a"]) == [1, 2, 3]

        thawed = thaw(frozen)
        assert isinstance(thawed, dict)
        assert isinstance(thawed["a"], list)
        assert thawed["a"] == [1, 2, 3]
        assert thawed["b"] == {"nested": True}

        # freeze preserves tuples
        assert freeze((1, [2])) == (1, freeze([2]))
        assert isinstance(freeze((1, [2]))[1], PVector)

        # freeze handles defaultdict
        dd = collections.defaultdict(dict)
        dd["a"] = "b"
        assert freeze(dd) == freeze({"a": "b"})

        # thaw converts PSet to set
        assert isinstance(thaw(freeze({1, 2})), set)

        # freeze/thaw with strict=False
        from pyrsistent import m, v
        result = freeze({"a": m(b={"c": 1})}, strict=False)
        assert type(result["a"]["b"]) is dict

    def test_get_in_nested_access(self):
        """get_in accesses deeply nested structures with default and no_default."""
        from pyrsistent import freeze, get_in

        data = freeze({"a": {"b": {"c": 42}}})
        assert get_in(["a", "b", "c"], data) == 42
        assert get_in(["a", "x"], data) is None
        assert get_in(["a", "x"], data, default="missing") == "missing"

        # no_default raises KeyError
        with pytest.raises(KeyError):
            get_in(["a", "x"], data, no_default=True)

        # Works with list indexing too
        data2 = freeze({"items": [10, 20, 30]})
        assert get_in(["items", 1], data2) == 20

    def test_mutant_decorator(self):
        """mutant decorator freezes inputs and outputs."""
        from pyrsistent import mutant, v, m, PMap, PVector

        @mutant
        def fn(a_list, a_dict):
            assert isinstance(a_list, PVector)
            assert isinstance(a_dict, PMap)
            return [1, 2, 3], {"a": 3}

        pv, pm = fn([1, 2, 3], a_dict={"a": 5})
        assert isinstance(pv, PVector)
        assert isinstance(pm, PMap)
        assert list(pv) == [1, 2, 3]
        assert pm == m(a=3)

    def test_freeze_strict_true_vs_false(self):
        """freeze with strict=True recurses INTO already-persistent types
        (converting mutable values inside them), while strict=False does NOT
        recurse into persistent types. This is a specific documented behavior
        that current tests only lightly cover."""
        from pyrsistent import freeze, pmap, PVector

        # strict=True (default): recurses into the PMap's values
        result_strict = freeze({"a": pmap({"b": [1, 2]})}, strict=True)
        inner_strict = result_strict["a"]["b"]
        assert isinstance(inner_strict, PVector)
        assert list(inner_strict) == [1, 2]

        # strict=False: does NOT recurse into the PMap's values
        result_lax = freeze({"a": pmap({"b": [1, 2]})}, strict=False)
        inner_lax = result_lax["a"]["b"]
        assert isinstance(inner_lax, list)
        assert inner_lax == [1, 2]

    def test_thaw_precord_to_dict(self):
        """thaw() on a PRecord correctly converts it and all its nested persistent
        fields to plain Python types. This exercises the PRecord-specific thaw path
        (PRecord is a PMap subclass but has typed fields that need special handling)."""
        from pyrsistent import PRecord, field, thaw, pvector

        class Inner(PRecord):
            x = field(type=int)
            y = field(type=str)

        class Outer(PRecord):
            name = field(type=str)
            inner = field(type=Inner)
            items = field()

        o = Outer(
            name="test",
            inner=Inner(x=1, y="hello"),
            items=pvector([10, 20]),
        )
        thawed = thaw(o)

        # Top-level is a plain dict
        assert isinstance(thawed, dict)
        assert thawed["name"] == "test"

        # Nested PRecord is also thawed to dict
        assert isinstance(thawed["inner"], dict)
        assert thawed["inner"]["x"] == 1
        assert thawed["inner"]["y"] == "hello"

        # PVector field is thawed to list
        assert isinstance(thawed["items"], list)
        assert thawed["items"] == [10, 20]


# =============================================================================
# Checked Types
# =============================================================================


class TestCheckedTypes:
    """Tests for CheckedPVector, CheckedPMap, CheckedPSet with type enforcement."""

    def test_checked_pvector_type_enforcement(self):
        """CheckedPVector enforces element types on creation, append, and set."""
        from pyrsistent import CheckedPVector

        class IntVector(CheckedPVector):
            __type__ = int

        iv = IntVector([1, 2, 3])
        assert list(iv) == [1, 2, 3]

        iv2 = iv.append(4)
        assert list(iv2) == [1, 2, 3, 4]

        iv3 = iv.set(0, 99)
        assert iv3[0] == 99

        iv4 = iv.extend([7, 8])
        assert list(iv4) == [1, 2, 3, 7, 8]

        with pytest.raises(TypeError):
            IntVector(["not", "ints"])

        with pytest.raises(TypeError):
            iv.append("string")

    def test_checked_pvector_with_invariant(self):
        """CheckedPVector supports __invariant__ for custom validation."""
        from pyrsistent import CheckedPVector, InvariantException

        class Positives(CheckedPVector):
            __type__ = int
            __invariant__ = lambda n: (n > 0, 'must be positive')

        pv = Positives([1, 2, 3])
        assert list(pv) == [1, 2, 3]

        with pytest.raises(InvariantException):
            Positives([1, -1, 3])

    def test_checked_pmap_type_enforcement(self):
        """CheckedPMap enforces key and value types on creation and set."""
        from pyrsistent import CheckedPMap

        class StrIntMap(CheckedPMap):
            __key_type__ = str
            __value_type__ = int

        m = StrIntMap({"a": 1, "b": 2})
        assert m["a"] == 1

        m2 = m.set("c", 3)
        assert m2["c"] == 3

        with pytest.raises(TypeError):
            StrIntMap({1: "wrong"})

        with pytest.raises(TypeError):
            m.set(1, 2)  # wrong key type

        with pytest.raises(TypeError):
            m.set("d", "wrong")  # wrong value type

    def test_checked_pset_type_enforcement(self):
        """CheckedPSet enforces element types on creation and add."""
        from pyrsistent import CheckedPSet

        class IntSet(CheckedPSet):
            __type__ = int

        s = IntSet([1, 2, 3])
        assert len(s) == 3
        assert 1 in s

        s2 = s.add(4)
        assert 4 in s2

        with pytest.raises(TypeError):
            IntSet(["not", "ints"])

        with pytest.raises(TypeError):
            s.add("string")

    def test_checked_types_create_and_serialize(self):
        """CheckedType.create() is a factory; serialize() returns plain Python."""
        from pyrsistent import CheckedPVector, CheckedPMap

        class IntVec(CheckedPVector):
            __type__ = int

        iv = IntVec.create([1, 2, 3])
        assert list(iv) == [1, 2, 3]
        assert iv.serialize() == [1, 2, 3]

        # create is idempotent
        assert IntVec.create(iv) is iv

        class SIMap(CheckedPMap):
            __key_type__ = str
            __value_type__ = int

        m = SIMap.create({"a": 1})
        assert m.serialize() == {"a": 1}

    def test_checked_type_error_attributes(self):
        """CheckedKeyTypeError/CheckedValueTypeError carry source_class, expected_types, actual_type, actual_value."""
        from pyrsistent import CheckedPMap, CheckedKeyTypeError, CheckedValueTypeError

        class StrIntMap(CheckedPMap):
            __key_type__ = str
            __value_type__ = int

        # CheckedKeyTypeError on wrong key type
        with pytest.raises(CheckedKeyTypeError) as exc_info:
            StrIntMap({1: 2})
        e = exc_info.value
        assert e.source_class is StrIntMap
        assert e.expected_types == (str,)
        assert e.actual_type is int
        assert e.actual_value == 1

        # CheckedValueTypeError on wrong value type
        with pytest.raises(CheckedValueTypeError) as exc_info:
            StrIntMap({"a": "bad"})
        e = exc_info.value
        assert e.source_class is StrIntMap
        assert e.expected_types == (int,)
        assert e.actual_type is str
        assert e.actual_value == "bad"

        # Both are subclasses of TypeError
        assert issubclass(CheckedKeyTypeError, TypeError)
        assert issubclass(CheckedValueTypeError, TypeError)


# =============================================================================
# immutable() — Named Tuple Wrapper
# =============================================================================


class TestImmutable:
    """Tests for the immutable() factory function."""

    def test_immutable_creation_set_and_frozen_members(self):
        """immutable creates namedtuple-like classes with set() and frozen members."""
        from pyrsistent import immutable

        Point = immutable('x, y', name='Point')
        p = Point(1, 2)
        assert p.x == 1
        assert p.y == 2
        assert 'Point' in repr(p)

        # set returns new instance
        p2 = p.set(x=3)
        assert p2.x == 3
        assert p.x == 1

        # Cannot modify directly
        with pytest.raises(AttributeError):
            p.x = 10

        # Non-member raises AttributeError
        with pytest.raises(AttributeError):
            p.set(z=5)

        # Frozen members (trailing underscore)
        FrozenPoint = immutable('x, y, id_', name='FrozenPoint')
        fp = FrozenPoint(1, 2, id_=17)
        assert fp.id_ == 17

        # Can set non-frozen
        fp2 = fp.set(x=3)
        assert fp2.x == 3
        assert fp2.id_ == 17

        # Cannot set frozen
        with pytest.raises(AttributeError):
            fp.set(id_=18)

        # Empty immutable: set() with no args returns same instance
        Empty = immutable(name='Empty')
        e = Empty()
        assert e.set() is e

    def test_immutable_inheritance(self):
        """immutable classes can be subclassed with custom __new__ for validation."""
        from pyrsistent import immutable

        class PositivePoint(immutable('x, y')):
            __slots__ = tuple()
            def __new__(cls, x, y):
                if x > 0 and y > 0:
                    return super(PositivePoint, cls).__new__(cls, x, y)
                raise ValueError('Coordinates must be positive!')

        p = PositivePoint(1, 2)
        p2 = p.set(x=3)
        assert p2.x == 3
        assert p2.y == 2

        with pytest.raises(ValueError):
            p.set(y=-3)


# =============================================================================
# Field Helpers: pvector_field, pmap_field, pset_field
# =============================================================================


class TestFieldHelpers:
    """Tests for pvector_field, pmap_field, pset_field in PRecord."""

    def test_pvector_field_type_enforcement(self):
        """pvector_field creates typed vector fields with initial values and type checking."""
        from pyrsistent import PRecord, pvector_field, pvector, InvariantException

        class R(PRecord):
            nums = pvector_field(int)

        # Default initial is empty
        r = R()
        assert list(r.nums) == []

        # Factory converts list to checked PVector
        r2 = R(nums=[1, 2, 3])
        assert list(r2.nums) == [1, 2, 3]

        # Type checking on append
        with pytest.raises(TypeError):
            r2.nums.append("string")

        # Mandatory: remove raises
        with pytest.raises(InvariantException):
            r2.remove("nums")

    def test_pmap_field_type_enforcement(self):
        """pmap_field creates typed map fields with initial values and type checking."""
        from pyrsistent import PRecord, pmap_field, pmap

        class R(PRecord):
            data = pmap_field(str, int)

        r = R()
        assert r.data == pmap()

        r2 = R(data={"a": 1, "b": 2})
        assert r2.data["a"] == 1

        # Type checking
        with pytest.raises(TypeError):
            r2.data.set(1, 2)  # wrong key type

        with pytest.raises(TypeError):
            r2.data.set("c", "wrong")  # wrong value type

    def test_pset_field_type_enforcement(self):
        """pset_field creates typed set fields with initial values and type checking."""
        from pyrsistent import PRecord, pset_field, pset, InvariantException

        class R(PRecord):
            tags = pset_field(str)

        r = R()
        assert r.tags == pset()

        r2 = R(tags=["hello", "world"])
        assert "hello" in r2.tags

        # Type checking
        with pytest.raises(TypeError):
            r2.tags.add(42)

        # Optional
        class OptR(PRecord):
            tags = pset_field(str, optional=True)

        assert OptR(tags=None).tags is None
        assert OptR(tags=["a"]).tags == pset(["a"])


# =============================================================================
# Pickling
# =============================================================================


class TestPickling:
    """Tests for pickle serialization of all persistent structures and typed variants."""

    def test_pickle_precord_and_pclass(self):
        """PRecord and PClass support pickle roundtrip."""
        pr = _PicklePR(x=1, y="hello")
        pr2 = pickle.loads(pickle.dumps(pr))
        assert pr2 == pr
        assert pr2.x == 1
        assert pr2.y == "hello"

        pc = _PicklePC(a=1, b="hello")
        pc2 = pickle.loads(pickle.dumps(pc))
        assert pc2 == pc
        assert pc2.a == 1
        assert pc2.b == "hello"

    def test_pickle_checked_types(self):
        """Checked types support pickle roundtrip."""
        iv = _PickleIV([1, 2, 3])
        iv2 = pickle.loads(pickle.dumps(iv))
        assert list(iv2) == [1, 2, 3]

        sm = _PickleSM({"a": 1})
        sm2 = pickle.loads(pickle.dumps(sm))
        assert sm2 == sm

        is_ = _PickleIS([1, 2])
        is2 = pickle.loads(pickle.dumps(is_))
        assert is2 == is_


# =============================================================================
# Stress Tests — Trie Boundaries, Collision Depth, Nested Invariant Cascades
# =============================================================================


class TestStress:
    """Hard tests exercising internal data structure boundaries and deep invariant chains."""

    def test_pvector_trie_level_boundaries(self):
        """PVector uses a 32-way branching trie. At exactly 32, 1024 (32**2), and
        32768 (32**3) elements the trie adds a new level. Verify that append, set,
        and evolver operations all work correctly at and across each boundary.
        A flat-array implementation handles these sizes trivially, but a real trie
        must allocate new root nodes and correctly route indices through multiple levels.
        The evolver block batches scattered writes, appends and repeated front deletes
        in one session and checks the source vector is untouched at the overwritten
        indices."""
        from pyrsistent import pvector

        for boundary in (32, 1024, 32768):
            # Build vector at exactly the boundary size
            vec = pvector(range(boundary))
            assert len(vec) == boundary
            assert vec[0] == 0
            assert vec[boundary - 1] == boundary - 1

            # Append one past the boundary (triggers new trie level)
            vec_plus = vec.append(boundary)
            assert len(vec_plus) == boundary + 1
            assert vec_plus[boundary] == boundary
            assert vec_plus[boundary - 1] == boundary - 1
            assert vec_plus[0] == 0

            # set at the last element of old boundary and first of new
            vec_set = vec_plus.set(boundary - 1, "last_old")
            assert vec_set[boundary - 1] == "last_old"
            vec_set2 = vec_plus.set(boundary, "first_new")
            assert vec_set2[boundary] == "first_new"

            # Original unchanged
            assert vec[boundary - 1] == boundary - 1
            assert vec_plus[boundary] == boundary

            # Evolver at boundary: scattered writes, appends, repeated deletes
            evolver = vec.evolver()
            step = max(4, boundary // 32)
            for i in range(0, boundary, step):
                evolver[i] = -(i + 1)
            evolver[boundary - 1] = "modified"
            evolver.append("appended_1")
            evolver.append("appended_2")
            del evolver[0]
            del evolver[0]
            del evolver[0]
            result = evolver.persistent()
            assert len(result) == boundary - 1  # 2 appends - 3 dels
            assert result[0] == 3  # shifted after three front deletes
            assert result[step - 3] == -(step + 1)  # scattered write survives the deletes
            assert result[boundary - 4] == "modified"
            assert result[boundary - 3] == "appended_1"
            assert result[boundary - 2] == "appended_2"

            # Original unchanged, including at indices the evolver overwrote
            assert len(vec) == boundary
            assert vec[0] == 0
            assert vec[step] == step
            assert vec[boundary - 1] == boundary - 1

    def test_pmap_massive_single_hash_collision(self):
        """Create a PMap with 60 keys that ALL share the exact same hash value.
        This forces the HAMT to build deep collision chains. Verify set, get,
        remove, len, and iteration all remain correct under extreme collision
        pressure. A naive dict wrapper handles collisions via Python's built-in
        dict, but a real HAMT must implement collision node buckets correctly."""
        from pyrsistent import pmap

        class ConstHash:
            """All instances return the same hash to force collision chains."""
            def __init__(self, val):
                self.val = val
            def __hash__(self):
                return 42
            def __eq__(self, other):
                return isinstance(other, ConstHash) and self.val == other.val
            def __repr__(self):
                return f"CH({self.val})"

        # Build map with 60 colliding keys
        items = {ConstHash(i): f"val_{i}" for i in range(60)}
        pm = pmap(items)
        assert len(pm) == 60

        # Verify all keys are retrievable
        for i in range(60):
            assert pm[ConstHash(i)] == f"val_{i}"

        # Remove from the middle of the collision chain
        pm2 = pm.remove(ConstHash(30))
        assert len(pm2) == 59
        assert ConstHash(30) not in pm2
        for i in range(60):
            if i == 30:
                continue
            assert pm2[ConstHash(i)] == f"val_{i}"

        # Multiple removes (every 3rd key)
        pm3 = pm
        for i in range(0, 60, 3):
            pm3 = pm3.remove(ConstHash(i))
        assert len(pm3) == 40

        # Set on existing colliding key (update value)
        pm4 = pm.set(ConstHash(25), "updated")
        assert pm4[ConstHash(25)] == "updated"
        assert pm[ConstHash(25)] == "val_25"  # original unchanged

        # Iteration produces all keys
        keys_from_iter = sorted([k.val for k in pm])
        assert keys_from_iter == list(range(60))

        # Evolver with colliding keys
        evolver = pm.evolver()
        evolver[ConstHash(0)] = "evolver_zero"
        del evolver[ConstHash(59)]
        evolver[ConstHash(100)] = "new_colliding"
        result = evolver.persistent()
        assert len(result) == 60  # -1 + 1
        assert result[ConstHash(0)] == "evolver_zero"
        assert ConstHash(59) not in result
        assert result[ConstHash(100)] == "new_colliding"

    def test_precord_four_level_nested_invariant_cascade(self):
        """A 4-level deep PRecord hierarchy where EVERY level has both field-level
        invariants and a global __invariant__. create() from a nested dict must
        recursively construct all typed sub-records, apply factories, and validate
        ALL invariants at all 4 levels. set() on a deeply nested field must re-fire
        the cascade of factories and invariants through all levels.
        This tests the recursive create() and invariant validation machinery —
        a flat PMap wrapper cannot recursively construct typed sub-records or
        validate cross-field invariants at multiple nesting depths."""
        from pyrsistent import PRecord, field, InvariantException

        class Level4(PRecord):
            __invariant__ = lambda r: (r.score >= 0, 'L4: score must be non-negative')
            score = field(type=int, invariant=lambda s: (s <= 100, 'L4: score must be <= 100'), mandatory=True)
            label = field(type=str, factory=str, mandatory=True)

        class Level3(PRecord):
            __invariant__ = lambda r: (len(r.name) >= 2, 'L3: name must be >= 2 chars')
            name = field(type=str, mandatory=True)
            data = field(type=Level4, mandatory=True)

        class Level2(PRecord):
            __invariant__ = lambda r: (r.priority > 0, 'L2: priority must be positive')
            priority = field(type=int, invariant=lambda p: (p <= 10, 'L2: priority must be <= 10'), mandatory=True)
            child = field(type=Level3, mandatory=True)

        class Level1(PRecord):
            __invariant__ = lambda r: (r.version >= 1, 'L1: version must be >= 1')
            version = field(type=int, mandatory=True)
            nested = field(type=Level2, mandatory=True)

        # Successful 4-level create from plain dicts
        source = {
            "version": 1,
            "nested": {
                "priority": 5,
                "child": {
                    "name": "test",
                    "data": {
                        "score": 85,
                        "label": 42  # factory=str should convert
                    }
                }
            }
        }
        r = Level1.create(source)
        assert isinstance(r.nested, Level2)
        assert isinstance(r.nested.child, Level3)
        assert isinstance(r.nested.child.data, Level4)
        assert r.nested.child.data.score == 85
        assert r.nested.child.data.label == "42"  # factory converted int to str

        # Deep set preserves types and re-validates
        r2 = r.set("nested", r.nested.set("child", r.nested.child.set(
            "data", r.nested.child.data.set("score", 95))))
        assert r2.nested.child.data.score == 95
        assert r.nested.child.data.score == 85  # original unchanged

        # L4 field invariant violation (score > 100)
        with pytest.raises(InvariantException) as exc_info:
            Level1.create({
                "version": 1,
                "nested": {"priority": 5, "child": {
                    "name": "ok", "data": {"score": 200, "label": "x"}
                }}
            })
        assert 'L4: score must be <= 100' in exc_info.value.invariant_errors

        # L4 global invariant violation (score < 0)
        with pytest.raises(InvariantException) as exc_info:
            Level1.create({
                "version": 1,
                "nested": {"priority": 5, "child": {
                    "name": "ok", "data": {"score": -1, "label": "x"}
                }}
            })
        assert 'L4: score must be non-negative' in exc_info.value.invariant_errors

        # L3 global invariant violation (name too short)
        with pytest.raises(InvariantException) as exc_info:
            Level1.create({
                "version": 1,
                "nested": {"priority": 5, "child": {
                    "name": "a", "data": {"score": 50, "label": "x"}
                }}
            })
        assert 'L3: name must be >= 2 chars' in exc_info.value.invariant_errors

        # L2 field invariant violation (priority > 10)
        with pytest.raises(InvariantException) as exc_info:
            Level1.create({
                "version": 1,
                "nested": {"priority": 20, "child": {
                    "name": "ok", "data": {"score": 50, "label": "x"}
                }}
            })
        assert 'L2: priority must be <= 10' in exc_info.value.invariant_errors

        # L1 global invariant violation (version < 1)
        with pytest.raises(InvariantException) as exc_info:
            Level1.create({
                "version": 0,
                "nested": {"priority": 5, "child": {
                    "name": "ok", "data": {"score": 50, "label": "x"}
                }}
            })
        assert 'L1: version must be >= 1' in exc_info.value.invariant_errors



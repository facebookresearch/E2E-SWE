"""End-to-end tests for mongita's public API (a MongoDB-compatible embedded document store).

mongita exposes a pymongo-shaped surface: ``MongitaClientMemory`` / ``MongitaClientDisk`` →
``Database`` → ``Collection``, with a query/update engine (filter operators, dotted-field access,
update operators, sorting, indexes) and lazy ``Cursor`` objects. These tests drive that surface the
way a real user would — only documented imports, no reaching into private engine state — and assert
the observable contracts: result objects, ``bson.ObjectId`` ids, query/sort/update semantics,
index naming, the not-implemented surface, document isolation, and on-disk persistence.
"""

import copy
from datetime import datetime

import bson
import pytest

import mongita
from mongita import (
    MongitaClientMemory,
    MongitaClientDisk,
    ASCENDING,
    DESCENDING,
    errors,
    results,
    collection,
    database,
)

# A small, query-friendly dataset: mixed types (numeric vs string weight, missing fields),
# list fields (continents), and a nested sub-document (attrs) for dotted-field tests.
ANIMALS = [
    {"name": "Meercat", "family": "Herpestidae", "kingdom": "mammal",
     "spotted": datetime(1994, 4, 23), "weight": 0.75, "continents": ["AF"],
     "attrs": {"colors": ["brown"], "species": "Suricata suricatta"}},
    {"name": "Indian grey mongoose", "family": "Herpestidae", "kingdom": "mammal",
     "spotted": datetime(2003, 12, 1), "weight": 1.4, "continents": ["EA"],
     "attrs": {"colors": ["grey"], "species": "Herpestes edwardsii"}},
    {"name": "Honey Badger", "family": "Mustelidae", "kingdom": "mammal",
     "spotted": datetime(1987, 2, 13), "weight": 10.0, "continents": ["EA", "AF"],
     "attrs": {"colors": ["grey", "black"], "species": "Mellivora capensis"}},
    {"name": "King Cobra", "family": "Elapidae", "kingdom": "reptile",
     "spotted": datetime(1997, 2, 22), "weight": 6.0, "continents": ["EA"],
     "attrs": {"colors": ["black", "grey"], "species": "Ophiophagus hannah"}},
    {"name": "Secretarybird", "family": "Sagittariidae", "kingdom": "bird",
     "spotted": datetime(1992, 7, 3), "weight": 4.0, "continents": ["AF"],
     "attrs": {"colors": ["white", "black"], "species": "Sagittarius serpentarius"}},
    {"name": "Human", "family": "Hominidae", "kingdom": "mammal",
     "spotted": datetime(2021, 3, 25), "weight": 70.0, "continents": ["NA", "SA", "EA", "AF"],
     "attrs": {"colors": "brown", "species": "Homo sapien"}},
    {"name": "Placeholder", "spotted": datetime(2021, 3, 25)},
    {"name": "Placeholder2", "spotted": datetime(2021, 3, 25), "weight": "catweight",
     "kingdom": "cat"},
]
N = len(ANIMALS)


def fresh(docs):
    return copy.deepcopy(docs)


@pytest.fixture
def client():
    c = MongitaClientMemory()
    yield c
    c.close()


@pytest.fixture
def coll(client):
    """An empty collection."""
    return client.db.snake_hunter


@pytest.fixture
def populated(coll):
    """A collection pre-loaded with the ANIMALS dataset."""
    coll.insert_many(fresh(ANIMALS))
    return coll


# --------------------------------------------------------------------------- #
# Insert
# --------------------------------------------------------------------------- #
class TestInsert:
    def test_insert_one(self, coll):
        d = fresh(ANIMALS[0])
        ior = coll.insert_one(d)
        assert isinstance(ior, results.InsertOneResult)
        assert isinstance(repr(ior), str)
        assert isinstance(ior.inserted_id, bson.ObjectId)
        # insert must not mutate the caller's document
        assert "_id" not in d
        assert coll.count_documents({}) == 1
        assert coll.find_one({"_id": ior.inserted_id})["name"] == "Meercat"

        # a caller-provided _id is used verbatim
        ior2 = coll.insert_one({"_id": "custom-id", "name": "x"})
        assert ior2.inserted_id == "custom-id"
        assert coll.count_documents({"_id": "custom-id"}) == 1

        # re-inserting an existing document (same _id) is a duplicate-key error
        existing = coll.find_one({"name": "Meercat"})
        with pytest.raises(errors.MongitaError):
            coll.insert_one(existing)

        # validation: _id must be a string/ObjectId, doc must be a mapping
        with pytest.raises(errors.MongitaError):
            coll.insert_one({"_id": 5, "name": "bad"})
        with pytest.raises(errors.MongitaError):
            coll.insert_one("not a dict")
        with pytest.raises(errors.MongitaError):
            coll.insert_one([{"name": "in a list"}])
        with pytest.raises(errors.MongitaError):
            coll.insert_one({"name": "x"}, bypass_document_validation=True)
        with pytest.raises(TypeError):
            coll.insert_one()

    def test_insert_many(self, coll):
        imr = coll.insert_many(fresh(ANIMALS))
        assert isinstance(imr, results.InsertManyResult)
        assert isinstance(repr(imr), str)
        assert len(imr.inserted_ids) == N
        assert all(isinstance(_id, bson.ObjectId) for _id in imr.inserted_ids)
        assert coll.count_documents({}) == N
        assert coll.count_documents({"_id": {"$in": imr.inserted_ids}}) == N

        # ordered (default): stop at the first failing doc, later docs are not inserted
        coll.insert_one({"_id": "id0"})
        with pytest.raises(errors.MongitaError):
            coll.insert_many([{"_id": "id0"}, {"_id": "id1"}])
        assert not coll.find_one({"_id": "id1"})
        # ordered=False: continue past failures
        with pytest.raises(errors.MongitaError):
            coll.insert_many([{"_id": "id0"}, {"_id": "id2"}], ordered=False)
        assert coll.find_one({"_id": "id2"})

        with pytest.raises(errors.MongitaError):
            coll.insert_many({"not": "a list"})
        with pytest.raises(TypeError):
            coll.insert_many()


# --------------------------------------------------------------------------- #
# count_documents
# --------------------------------------------------------------------------- #
class TestCount:
    def test_count_documents(self, populated):
        with pytest.raises(TypeError):
            populated.count_documents()
        assert populated.count_documents({}) == N
        assert populated.count_documents({"kingdom": "mammal"}) == 4
        # the count must reflect the actually-matching documents, not just an arity
        assert {d["name"] for d in populated.find({"kingdom": "mammal"})} == \
            {"Meercat", "Indian grey mongoose", "Honey Badger", "Human"}
        assert populated.count_documents({"kingdom": "fish"}) == 0
        assert populated.count_documents({"nonexistent": "x"}) == 0

        doc = populated.find_one({"name": "Human"})
        assert populated.count_documents({"_id": doc["_id"]}) == 1
        assert populated.count_documents({"_id": "never-existed"}) == 0


# --------------------------------------------------------------------------- #
# find_one / find
# --------------------------------------------------------------------------- #
class TestFind:
    def test_find(self, populated):
        # ---- find_one ----
        doc = populated.find_one()
        assert isinstance(doc, dict)
        assert isinstance(doc["_id"], bson.ObjectId)

        human = populated.find_one({"name": "Human"})
        assert human["kingdom"] == "mammal"
        # dotted access into a nested sub-document resolves to the same document
        assert populated.find_one({"attrs.species": "Homo sapien"})["_id"] == human["_id"]
        # sort by a bare field name, or by an explicit [(field, direction)] list
        assert populated.find_one({}, sort="name")["name"] == "Honey Badger"
        assert populated.find_one({}, sort=[("name", DESCENDING)])["name"] == "Secretarybird"
        # sort + skip
        assert populated.find_one(
            {"family": "Herpestidae"}, sort=[("weight", -1)], skip=1
        )["name"] == "Meercat"
        # combined field + operator filter
        assert populated.find_one(
            {"family": "Herpestidae", "weight": {"$lt": 1}}
        )["name"] == "Meercat"
        assert populated.find_one({"family": "nonexistent"}) is None

        # invalid queries
        with pytest.raises(errors.MongitaError):
            populated.find_one(["not a dict"])
        with pytest.raises(errors.MongitaError):
            populated.find_one({"weight": {"$bigger": 7}})
        with pytest.raises(errors.MongitaError):
            populated.find_one({5: "non-string key"})
        with pytest.raises(errors.MongitaError):
            populated.find_one({"_id": 5})

        # ---- find (lazy cursor) ----
        docs = list(populated.find())
        assert len(docs) == N
        assert all(isinstance(d, dict) and isinstance(d["_id"], bson.ObjectId) for d in docs)

        assert {d["name"] for d in populated.find({"family": "Herpestidae"})} == \
            {"Meercat", "Indian grey mongoose"}

        # a cursor is exhausted after a single full iteration
        cur = populated.find()
        assert len(list(cur)) == N
        assert len(list(cur)) == 0

        ids = [d["_id"] for d in populated.find()]
        assert len(list(populated.find({"_id": {"$in": ids + ["not-a-real-id"]}}))) == N


# --------------------------------------------------------------------------- #
# Query operators
# --------------------------------------------------------------------------- #
class TestQueryOperators:
    def test_query_operators(self, populated):
        # The whole filter-operator surface is one implementation node: a model that gets
        # operator dispatch right passes all of this together, so it is graded as a unit.
        names = lambda flt: {d["name"] for d in populated.find(flt)}
        # comparison operators
        assert populated.count_documents({"weight": {"$eq": 4}}) == 1
        assert populated.count_documents({"weight": {"$ne": 4}}) == N - 1
        assert names({"weight": {"$lt": 4}}) == {"Meercat", "Indian grey mongoose"}
        assert names({"weight": {"$lte": 4}}) == {"Meercat", "Indian grey mongoose", "Secretarybird"}
        assert names({"weight": {"$gt": 4}}) == {"Honey Badger", "King Cobra", "Human"}
        assert names({"weight": {"$gte": 4}}) == {
            "Honey Badger", "King Cobra", "Human", "Secretarybird"}
        # multiple operators on one field are AND-ed together
        assert populated.count_documents({"weight": {"$gt": 1, "$lt": 7}}) == 3
        with pytest.raises(errors.MongitaError):
            list(populated.find({"weight": {"$nope": 7}}))
        # $in / $nin
        assert names({"kingdom": {"$in": ["reptile", "bird"]}}) == {"King Cobra", "Secretarybird"}
        # $nin also matches documents that are missing the field entirely
        assert populated.count_documents({"kingdom": {"$nin": ["reptile", "bird"]}}) == N - 2
        # membership against a list-valued field
        assert names({"continents": {"$in": ["NA", "AF"]}}) == {
            "Meercat", "Honey Badger", "Secretarybird", "Human"}
        assert populated.count_documents({"continents": {"$nin": ["EA", "AF"]}}) == 2
        assert populated.count_documents({"continents": {"$in": []}}) == 0
        # $in / $nin require a list argument
        with pytest.raises(errors.MongitaError):
            list(populated.find({"kingdom": {"$in": "bird"}}))
        with pytest.raises(errors.MongitaError):
            list(populated.find({"kingdom": {"$nin": "bird"}}))

    def test_nested_and_list_queries(self, populated):
        # equality on a scalar inside a list field
        assert populated.count_documents({"continents": "EA"}) == 4
        assert populated.find_one({"continents": "NA"})["name"] == "Human"
        # dotted nested equality + $in
        assert populated.find_one({"attrs.species": "Suricata suricatta"})["name"] == "Meercat"
        assert not populated.find_one({"attrs.species": "does not exist"})
        two = list(populated.find(
            {"attrs.species": {"$in": ["Suricata suricatta", "Mellivora capensis"]}}))
        assert {d["name"] for d in two} == {"Meercat", "Honey Badger"}


# --------------------------------------------------------------------------- #
# Cursor
# --------------------------------------------------------------------------- #
class TestCursor:
    def test_cursor(self, populated):
        # The Cursor is one implementation node (sort / limit / skip / navigation / the
        # not-implemented surface all live on it), so it is exercised as a single unit.
        # ---- sort ----
        # missing values sort before numbers, which sort before strings
        asc = [d["name"] for d in populated.find().sort("weight")]
        assert asc[0] == "Placeholder"          # no weight -> first
        assert asc[1] == "Meercat"              # smallest number
        assert asc[-1] == "Placeholder2"        # string weight -> last
        desc = [d["name"] for d in populated.find().sort("weight", DESCENDING)]
        assert desc[0] == "Placeholder2" and desc[-1] == "Placeholder"
        assert [d["name"] for d in populated.find().sort("name", DESCENDING)][0] == "Secretarybird"

        # multi-key sort
        multi = list(populated.find().sort([("kingdom", ASCENDING), ("weight", DESCENDING)]))
        assert multi[0].get("kingdom") is None    # missing kingdom sorts first
        assert multi[1].get("kingdom") == "bird"
        assert multi[2].get("kingdom") == "cat"
        assert multi[3].get("kingdom") == "mammal" and multi[3]["name"] == "Human"  # heaviest mammal
        assert multi[-1].get("kingdom") == "reptile"

        # invalid sort direction / format
        with pytest.raises(errors.MongitaError):
            list(populated.find().sort("weight", 2))
        with pytest.raises(errors.MongitaError):
            list(populated.find().sort("weight", "ASCENDING"))
        with pytest.raises(errors.MongitaError):
            list(populated.find().sort([(ASCENDING, "kingdom")]))
        # sorting after iteration has begun is illegal
        cur = populated.find().sort("name")
        next(cur)
        with pytest.raises(errors.InvalidOperation):
            cur.sort("kingdom")

        # ---- limit / skip ----
        assert len(list(populated.find().limit(3))) == 3
        assert len(list(populated.find().skip(3))) == N - 3
        assert len(list(populated.find().skip(3).limit(1))) == 1
        assert len(list(populated.find(skip=2).limit(2))) == 2
        assert len(list(populated.find(limit=3).skip(2))) == 3
        # limit/skip compose with sort regardless of call order
        assert {d["name"] for d in populated.find().sort("name").limit(2)} == \
            {"Honey Badger", "Human"}
        assert {d["name"] for d in populated.find().limit(2).sort("name")} == \
            {"Honey Badger", "Human"}
        assert {d["name"] for d in populated.find().sort("name").skip(2).limit(2)} == \
            {"Indian grey mongoose", "King Cobra"}

        # type validation
        with pytest.raises(TypeError):
            populated.find().limit(2.0)
        with pytest.raises(TypeError):
            populated.find().skip(2.0)
        with pytest.raises(TypeError):
            populated.find().skip("2")
        with pytest.raises(ValueError):
            populated.find().skip(-1)
        # limit/skip after iteration has begun is illegal
        cur = populated.find()
        next(cur)
        with pytest.raises(errors.InvalidOperation):
            cur.limit(2)
        with pytest.raises(errors.InvalidOperation):
            cur.skip(2)

        # ---- navigation ----
        cur = populated.find().sort("name")
        assert next(cur)["name"] == "Honey Badger"
        assert next(cur)["name"] == "Human"
        assert cur.next()["name"] == "Indian grey mongoose"
        # clone resets iteration
        clone = cur.clone()
        assert next(clone)["name"] == "Honey Badger"
        # close ends the cursor
        cur.close()
        with pytest.raises(StopIteration):
            next(cur)

        # not-implemented / unknown cursor surface
        with pytest.raises(errors.MongitaNotImplementedError):
            populated.find().count()
        with pytest.raises(errors.MongitaNotImplementedError):
            populated.find().allow_disk_use()
        with pytest.raises(errors.MongitaNotImplementedError):
            populated.find()[0]
        with pytest.raises(AttributeError):
            populated.find().made_up_method()


# --------------------------------------------------------------------------- #
# Update / replace
# --------------------------------------------------------------------------- #
class TestUpdate:
    def test_update_one(self, populated):
        ur = populated.update_one({"name": "Meercat"}, {"$set": {"name": "Mongoose"}})
        assert isinstance(ur, results.UpdateResult)
        assert isinstance(repr(ur), str)
        assert ur.matched_count == 1 and ur.modified_count == 1 and ur.upserted_id is None
        assert populated.find_one({"name": "Mongoose"})

        # $inc on a numeric field
        before = populated.find_one({"name": "Mongoose"})["weight"]
        populated.update_one({"name": "Mongoose"}, {"$inc": {"weight": -1}})
        assert populated.find_one({"name": "Mongoose"})["weight"] == before - 1

        # $push appends; pushing onto a missing field creates a new list
        populated.update_one({"name": "Honey Badger"}, {"$push": {"continents": "ZZ"}})
        assert populated.find_one({"name": "Honey Badger"})["continents"] == ["EA", "AF", "ZZ"]
        populated.update_one({"name": "Honey Badger"}, {"$push": {"nick": "boss"}})
        assert populated.find_one({"name": "Honey Badger"})["nick"] == ["boss"]

        # dotted $set into a nested sub-document
        populated.update_one({"name": "Human"}, {"$set": {"attrs.smart": True}})
        assert populated.find_one({"name": "Human"})["attrs"]["smart"] is True

        # no match -> zero counts
        ur = populated.update_one({"name": "ghost"}, {"$set": {"name": "x"}})
        assert ur.matched_count == 0 and ur.modified_count == 0

        # invalid updates
        with pytest.raises(errors.MongitaError):
            populated.update_one({}, {}, upsert=True)
        with pytest.raises(errors.MongitaError):
            populated.update_one({}, {"name": "no operator"})
        with pytest.raises(errors.MongitaNotImplementedError):
            populated.update_one({}, {"$unset": {"name": ""}})
        with pytest.raises(errors.MongitaError):
            populated.update_one({}, {"$inc": {"name": 10}})       # $inc a non-numeric field
        with pytest.raises(errors.MongitaError):
            populated.update_one({"name": "Honey Badger"}, {"$push": {"name": "x"}})  # $push a scalar

    def test_update_many(self, populated):
        ur = populated.update_many({}, {"$set": {"kingdom": "beast"}})
        assert ur.matched_count == N and ur.modified_count == N and ur.upserted_id is None
        assert populated.distinct("kingdom") == ["beast"]

        ur = populated.update_many({"weight": {"$lt": 4}}, {"$inc": {"weight": 100}})
        assert ur.matched_count == 2 and ur.modified_count == 2
        assert populated.count_documents({"weight": {"$gt": 100}}) == 2

    def test_replace_one(self, populated):
        ur = populated.replace_one({"name": "Meercat"}, {"name": "Brand New", "weight": 5})
        assert isinstance(ur, results.UpdateResult)
        assert ur.matched_count == 1 and ur.modified_count == 1
        assert populated.count_documents({"name": "Meercat"}) == 0
        assert populated.find_one({"name": "Brand New"})["weight"] == 5

        # upsert of a non-existent document yields an ObjectId upserted_id
        ur = populated.replace_one({"name": "Ghost"}, {"name": "Ghost"}, upsert=True)
        assert ur.matched_count == 0 and ur.modified_count == 1
        assert isinstance(ur.upserted_id, bson.ObjectId)
        assert populated.count_documents({"name": "Ghost"}) == 1
        # upsert keyed on a provided _id
        populated.replace_one({"_id": "fixed-id"}, {"val": 1}, upsert=True)
        assert populated.count_documents({"_id": "fixed-id"}) == 1

        # no match, no upsert -> zero counts
        ur = populated.replace_one({"name": "nobody"}, {"x": "y"})
        assert ur.matched_count == 0 and ur.modified_count == 0
        with pytest.raises(TypeError):
            populated.replace_one({"_id": "a"})


# --------------------------------------------------------------------------- #
# Delete
# --------------------------------------------------------------------------- #
class TestDelete:
    def test_delete(self, populated):
        dor = populated.delete_one({"name": "King Cobra"})
        assert isinstance(dor, results.DeleteResult)
        assert isinstance(repr(dor), str)
        assert dor.deleted_count == 1
        assert populated.count_documents({}) == N - 1
        assert populated.delete_one({"_id": "never-existed"}).deleted_count == 0

        # delete_one removes at most one match; delete_many removes all matches
        assert populated.delete_one({"kingdom": "mammal"}).deleted_count == 1
        assert populated.count_documents({"kingdom": "mammal"}) == 3
        assert populated.delete_many({"kingdom": "mammal"}).deleted_count == 3
        assert populated.count_documents({"kingdom": "mammal"}) == 0

        rest = populated.count_documents({})
        assert populated.delete_many({}).deleted_count == rest
        assert populated.count_documents({}) == 0

        with pytest.raises(TypeError):
            populated.delete_one()
        with pytest.raises(TypeError):
            populated.delete_many()


# --------------------------------------------------------------------------- #
# distinct
# --------------------------------------------------------------------------- #
class TestDistinct:
    def test_distinct(self, populated):
        assert set(populated.distinct("name")) == {d["name"] for d in ANIMALS}
        assert set(populated.distinct("family", {"kingdom": "mammal"})) == \
            {"Herpestidae", "Mustelidae", "Hominidae"}
        assert set(populated.distinct("attrs.species")) == \
            {d["attrs"]["species"] for d in ANIMALS if "attrs" in d}
        with pytest.raises(errors.MongitaError):
            populated.distinct(5)


# --------------------------------------------------------------------------- #
# Indexes
# --------------------------------------------------------------------------- #
class TestIndexes:
    def test_create_and_drop(self, populated):
        # a fresh collection has exactly the implicit _id index
        assert len(populated.index_information()) == 1
        assert populated.create_index("kingdom") == "kingdom_1"
        assert populated.create_index([("weight", DESCENDING)]) == "weight_-1"
        assert len(populated.index_information()) == 3

        populated.drop_index("kingdom_1")          # drop by name
        populated.drop_index([("weight", -1)])     # drop by [(field, direction)]
        assert len(populated.index_information()) == 1

        # invalid create
        for bad in ("", 5, [], {"key": 1},
                    [("a", ASCENDING), ("b", ASCENDING)],  # compound is unsupported
                    [("a", 2)]):                            # bad direction
            with pytest.raises(errors.MongitaError):
                populated.create_index(bad)
        with pytest.raises(errors.MongitaError):
            populated.create_index("kingdom", background=True)

        # invalid drop (malformed names) and dropping a non-existent index
        populated.create_index("kingdom")
        for bad in (None, "kingdom1", "kingdom__1", "kingdom_a"):
            with pytest.raises(errors.MongitaError):
                populated.drop_index(bad)
        with pytest.raises(errors.OperationFailure):
            populated.database.totally_fresh.drop_index("nope")

    def test_queries_match_with_index(self, coll):
        coll.create_index("kingdom")
        coll.create_index("weight")
        coll.insert_many(fresh(ANIMALS))
        assert coll.count_documents({"kingdom": "mammal"}) == 4
        assert coll.count_documents({"weight": {"$gte": 6}}) == 3
        assert coll.count_documents({"kingdom": {"$in": ["bird", "reptile"]}}) == 2
        # an index does not change which documents match
        assert {d["name"] for d in coll.find({"weight": {"$lt": 4}})} == \
            {"Meercat", "Indian grey mongoose"}


# --------------------------------------------------------------------------- #
# Collection metadata / not-implemented surface
# --------------------------------------------------------------------------- #
class TestCollectionMeta:
    def test_metadata_and_options(self, coll):
        assert coll.name == "snake_hunter"
        assert coll.full_name == "db.snake_hunter"
        assert isinstance(repr(coll), str)
        # attribute access yields a dotted sub-collection
        sub = coll.blah
        assert isinstance(sub, collection.Collection)
        assert sub.name == "snake_hunter.blah"

        # read/write concern are inert and expose an empty document
        assert coll.read_concern.document == {}
        assert coll.write_concern.document == {}

        # with_options returns an equivalent handle
        coll2 = coll.with_options(read_concern=coll.read_concern)
        assert coll2.name == coll.name and coll2.database == coll.database
        with pytest.raises(errors.MongitaNotImplementedError):
            coll.with_options(codec_options="TEST")

        # unsupported operations
        with pytest.raises(errors.MongitaNotImplementedError):
            coll.count()
        with pytest.raises(errors.MongitaNotImplementedError):
            coll.aggregate_raw_batches()


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
class TestDatabase:
    def test_database_ops(self, populated, client):
        db = client.db
        assert isinstance(db, database.Database)
        assert db.name == "db"
        assert isinstance(repr(db), str)
        assert db.list_collection_names() == ["snake_hunter"]

        listed = list(db.list_collections())
        assert all(isinstance(c, collection.Collection) for c in listed)
        assert "snake_hunter" in [c.name for c in listed]

        # item access and attribute access name the same collection
        assert db["snake_hunter"] == db.snake_hunter
        assert db["other"] == db.other
        # a never-written collection is empty and absent from the listing
        assert db.brandnew.count_documents({}) == 0
        assert "brandnew" not in db.list_collection_names()

        db.drop_collection("snake_hunter")
        assert db.snake_hunter.count_documents({}) == 0

        for bad in ("$reserved", "system.", ""):
            with pytest.raises(errors.MongitaError):
                db[bad]
        with pytest.raises(errors.MongitaNotImplementedError):
            db.add_son_manipulator()
        with pytest.raises(errors.MongitaNotImplementedError):
            db.dereference()


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class TestClient:
    def test_client_ops(self, populated, client):
        assert isinstance(repr(client), str)
        assert client["db"] == client.db
        assert client["other_db"] == client.other_db
        assert client.list_database_names() == ["db"]

        listed = list(client.list_databases())
        assert all(isinstance(d, database.Database) for d in listed)
        assert "db" in [d.name for d in listed]

        client.drop_database("db")
        assert client.db.list_collection_names() == []

        for bad in ("$reserved", ""):
            with pytest.raises(errors.MongitaError):
                client[bad]
        with pytest.raises(errors.MongitaNotImplementedError):
            client.close_cursor()


# --------------------------------------------------------------------------- #
# Persistence (memory is ephemeral; disk survives reopen)
# --------------------------------------------------------------------------- #
class TestPersistence:
    def test_memory_is_ephemeral(self):
        c1 = MongitaClientMemory()
        c1.db.coll.insert_many(fresh(ANIMALS))
        assert c1.db.coll.count_documents({}) == N
        # a second in-memory client shares no state
        c2 = MongitaClientMemory()
        assert c2.db.coll.count_documents({}) == 0
        # close drops everything
        c1.close()
        assert c1.db.coll.count_documents({}) == 0

    def test_disk_persists(self, tmp_path):
        path = str(tmp_path / "mdb")
        c1 = MongitaClientDisk(path)
        c1.db.coll.insert_many(fresh(ANIMALS))
        c1.db.coll.create_index("kingdom")
        c1.close()

        # a brand-new client at the same path sees the data
        c2 = MongitaClientDisk(path)
        assert c2.db.coll.count_documents({}) == N
        assert c2.db.coll.count_documents({"kingdom": "mammal"}) == 4
        assert {d["name"] for d in c2.db.coll.find({"weight": {"$gt": 6}})} == \
            {"Honey Badger", "Human"}
        # nested + datetime values round-trip through disk
        human = c2.db.coll.find_one({"name": "Human"})
        assert human["attrs"]["species"] == "Homo sapien"
        assert isinstance(human["spotted"], datetime)
        # mutations persist again
        assert c2.db.coll.update_many({"kingdom": "mammal"},
                                      {"$set": {"kingdom": "beast"}}).modified_count == 4
        assert c2.db.coll.delete_many({"kingdom": "beast"}).deleted_count == 4
        c2.close()
        c3 = MongitaClientDisk(path)
        assert c3.db.coll.count_documents({}) == N - 4
        c3.close()


# --------------------------------------------------------------------------- #
# Document isolation (stored docs are decoupled from caller / returned objects)
# --------------------------------------------------------------------------- #
class TestDocumentIsolation:
    def test_no_document_leak(self, coll):
        doc = fresh(ANIMALS[0])
        coll.insert_one(doc)
        # mutating the inserted object must not change stored state
        doc["name"] = "Mutated"
        doc["continents"].append("XX")
        stored = coll.find_one({})
        assert stored["name"] == "Meercat"
        assert stored["continents"] == ["AF"]
        # mutating a returned object must not change stored state either
        stored["name"] = "AlsoMutated"
        stored["attrs"]["colors"].append("XX")
        again = coll.find_one({})
        assert again["name"] == "Meercat"
        assert again["attrs"]["colors"] == ["brown"]


# --------------------------------------------------------------------------- #
# Dotted-path updates & list-index addressing
# --------------------------------------------------------------------------- #
class TestNestedDotted:
    TARGET = {"attrs.species": "Suricata suricatta"}  # the Meercat document

    def test_dotted_set_creates_nested_and_extends_lists(self, populated):
        # a dotted $set creates a new nested field
        assert populated.update_one(self.TARGET,
                                    {"$set": {"attrs.adorable": True}}).modified_count == 1
        assert populated.find_one({"attrs.adorable": True})["name"] == "Meercat"

        # $set can assign a list, then a query can index into it by integer position
        populated.update_one(self.TARGET, {"$set": {"attrs.pts": [1, 2, 3]}})
        assert populated.find_one({"attrs.pts.0": 1})["attrs"]["pts"] == [1, 2, 3]

        # $set at a list index past the end extends the list, padding gaps with None
        populated.update_one(self.TARGET, {"$set": {"attrs.pts.5": 10}})
        assert populated.find_one({"name": "Meercat"})["attrs"]["pts"] == [1, 2, 3, None, None, 10]

        # a dotted path addressing a new list index extends the list, filling the new
        # position with None (a path descending further past it has no further effect)
        assert populated.update_one(self.TARGET,
                                    {"$set": {"attrs.pts.6.is.so": "cute"}}).modified_count == 1
        assert populated.find_one({"name": "Meercat"})["attrs"]["pts"] == \
            [1, 2, 3, None, None, 10, None]

    def test_dotted_set_invalid_paths_raise(self, populated):
        populated.update_one(self.TARGET, {"$set": {"attrs.pts": [1, 2, 3]}})
        for bad in ("attrs.pts.seven",            # non-integer index into a list
                    "attrs.pts.eight.boo",        # non-integer index (nested)
                    "attrs.pts.-1.imaginary.boo", # negative index, nested
                    "attrs.pts.0.boo.hoo"):       # descend into a scalar list element
            with pytest.raises(errors.MongitaError):
                populated.update_one(self.TARGET, {"$set": {bad: "x"}})

    def test_dotted_query_addressing_and_whole_value_equality(self, populated):
        populated.update_one(self.TARGET, {"$set": {"attrs.pts": [1, 2, 3],
                                                    "attrs.dd": {"hello": ["w", "orld"]}}})
        # a dotted path that does not resolve matches nothing (it does not raise)
        assert populated.count_documents({"attrs.pts.seven": 8}) == 0   # non-integer index
        assert populated.count_documents({"attrs.pts.11": 8}) == 0      # out-of-range index
        assert populated.count_documents({"attrs.pts.0.hoo": 8}) == 0   # descend into a scalar
        # equality compares whole list / nested-dict values structurally
        assert populated.count_documents({"attrs.pts": [1, 2, 3]}) == 1
        assert populated.count_documents({"attrs.pts": {"$eq": [1, 2, 3]}}) == 1
        assert populated.count_documents({"attrs.pts": [1, 2]}) == 0
        assert populated.count_documents({"attrs.dd": {"hello": ["w", "orld"]}}) == 1
        assert populated.count_documents({"attrs.dd": {"hello": ["w", "orld!"]}}) == 0


# --------------------------------------------------------------------------- #
# Module-level guard
# --------------------------------------------------------------------------- #
class TestModuleGuard:
    def test_module_attributes(self):
        # pymongo names that mongita deliberately does not implement
        with pytest.raises(errors.MongitaNotImplementedError):
            mongita.InsertOne()
        # genuinely unknown attributes are AttributeErrors
        with pytest.raises(AttributeError):
            mongita.mongodb_fictional_method()

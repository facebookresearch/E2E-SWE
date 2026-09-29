"""Tests for django-cqrs's in-process master/replica core.

The suite is deliberately consolidated: each test exercises one implementation
concern through a realistic workflow (no partial credit for trivial variants).
The transaction/concurrency-semantics tests (de-duplication, atomic revision,
commit-time emission) are the discriminating ones; the rest verify the broader
master/replica contract.

A self-contained Django test project (cqrs_harness/, in-memory sqlite + an
in-process CapturingTransport that records produced events and routes them to the
consumer) hosts concrete models built on the implementation's mixins.
"""

import pytest
from django.db import transaction

from cqrs_harness.models import (
    MasterThing,
    ReplicaThing,
    SerializedThing,
    ReplicaMapped,
    TrackedMaster,
    FieldSubsetMaster,
    CommitMaster,
    CommitReplica,
)
from cqrs_harness import transport


def _master_data(pk, name, value, revision):
    return {
        'id': pk,
        'name': name,
        'value': value,
        'cqrs_revision': revision,
        'cqrs_updated': '2024-01-01T00:00:00',
    }


class _Rollback(Exception):
    pass


class TestEndToEndPipeline:
    @pytest.mark.django_db
    def test_master_lifecycle_propagates_to_replica(self, django_capture_on_commit_callbacks):
        """A master create, update, and delete each propagate through the
        transport -> consumer pipeline to the replica."""
        transport.reset()
        with django_capture_on_commit_callbacks(execute=True):
            m = MasterThing.objects.create(name='alpha', value=10)
        assert len(transport.PRODUCED) == 1
        r = ReplicaThing.objects.get(pk=m.pk)
        assert r.name == 'alpha'
        assert r.value == 10
        assert r.cqrs_revision == 0

        with django_capture_on_commit_callbacks(execute=True):
            m2 = MasterThing.objects.get(pk=m.pk)
            m2.value = 20
            m2.save()
        r.refresh_from_db()
        assert r.value == 20
        assert r.cqrs_revision == 1

        with django_capture_on_commit_callbacks(execute=True):
            MasterThing.objects.get(pk=m.pk).delete()
        assert not ReplicaThing.objects.filter(pk=m.pk).exists()


class TestTransactionScopedDeduplication:
    @pytest.mark.django_db
    def test_dedup_is_per_instance_per_transaction(self, django_capture_on_commit_callbacks):
        """De-duplication is per instance per transaction: many saves of one
        instance in a transaction emit exactly one event (carrying the final
        state); saves in separate transactions emit separate events; and distinct
        instances in one transaction each emit their own event."""
        with django_capture_on_commit_callbacks(execute=True):
            m = MasterThing.objects.create(name='a', value=1)

        # Many saves of the same instance in one transaction -> one event.
        transport.reset()
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                m2 = MasterThing.objects.get(pk=m.pk)
                m2.value = 2
                m2.save()
                m2.value = 3
                m2.save()
        assert len(transport.PRODUCED) == 1
        assert ReplicaThing.objects.get(pk=m.pk).value == 3

        # A later, separate transaction -> its own event.
        transport.reset()
        with django_capture_on_commit_callbacks(execute=True):
            m3 = MasterThing.objects.get(pk=m.pk)
            m3.value = 4
            m3.save()
        assert len(transport.PRODUCED) == 1
        assert ReplicaThing.objects.get(pk=m.pk).value == 4

        # Distinct instances in one transaction -> one event each.
        transport.reset()
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                MasterThing.objects.create(name='b', value=5)
                MasterThing.objects.create(name='c', value=6)
        assert len(transport.PRODUCED) == 2


class TestConcurrencySafeRevision:
    @pytest.mark.django_db
    def test_revision_increment_is_atomic_for_stale_instances(self):
        """Two independently loaded (stale) copies saved in sequence each advance
        the stored revision: the increment is applied atomically at the database
        level, not from the in-memory value (0 -> 1 -> 2)."""
        m = MasterThing.objects.create(name='a', value=1)
        assert m.cqrs_revision == 0

        a = MasterThing.objects.get(pk=m.pk)
        b = MasterThing.objects.get(pk=m.pk)

        a.value = 2
        a.save()
        b.name = 'x'
        b.save()

        m.refresh_from_db()
        assert m.cqrs_revision == 2


class TestCommitSemantics:
    @pytest.mark.django_db
    def test_only_committed_changes_emit_events(self, django_capture_on_commit_callbacks):
        """Events fire only on commit: a committed create produces an event and a
        replica row; a change in a transaction that rolls back produces neither."""
        transport.reset()
        with django_capture_on_commit_callbacks(execute=True):
            m = CommitMaster.objects.create(name='committed', value=1)
        assert len(transport.PRODUCED) == 1
        assert CommitReplica.objects.filter(pk=m.pk).exists()

        transport.reset()
        with django_capture_on_commit_callbacks(execute=True):
            try:
                with transaction.atomic():
                    CommitMaster.objects.create(name='rolledback', value=2)
                    raise _Rollback()
            except _Rollback:
                pass
        assert len(transport.PRODUCED) == 0
        assert not CommitReplica.objects.filter(name='rolledback').exists()


class TestReplicaConflictResolution:
    @pytest.mark.django_db
    def test_conflict_resolution_by_revision(self):
        """Replica cqrs_save applies a payload only when its revision is greater
        than the stored one (including skip-ahead gaps); older and duplicate
        (equal) revisions are ignored and leave the row unchanged."""
        ReplicaThing.cqrs_save(_master_data(1, 'orig', 7, 2))
        assert ReplicaThing.objects.get(pk=1).cqrs_revision == 2

        # Older -> ignored.
        ReplicaThing.cqrs_save(_master_data(1, 'older', 0, 1))
        o = ReplicaThing.objects.get(pk=1)
        assert o.name == 'orig' and o.value == 7 and o.cqrs_revision == 2

        # Duplicate (equal) -> ignored.
        ReplicaThing.cqrs_save(_master_data(1, 'dup', 8, 2))
        assert ReplicaThing.objects.get(pk=1).name == 'orig'

        # Newer, even with a gap -> applied.
        ReplicaThing.cqrs_save(_master_data(1, 'new', 9, 5))
        o = ReplicaThing.objects.get(pk=1)
        assert o.name == 'new' and o.value == 9 and o.cqrs_revision == 5


class TestBulkOperations:
    @pytest.mark.django_db
    def test_bulk_create_and_update_emit_per_instance(self, django_capture_on_commit_callbacks):
        """cqrs.bulk_create emits one create event per object; repeated
        cqrs.bulk_update emits one update event per affected instance and advances
        each row's revision by one per call (0 -> 1 -> 2)."""
        transport.reset()
        with django_capture_on_commit_callbacks(execute=True):
            MasterThing.cqrs.bulk_create(
                [MasterThing(name='a', value=1), MasterThing(name='b', value=2)]
            )
        assert len(transport.PRODUCED) == 2
        assert ReplicaThing.objects.count() == 2

        transport.reset()
        with django_capture_on_commit_callbacks(execute=True):
            MasterThing.cqrs.bulk_update(MasterThing.objects.all(), value=9)
        assert len(transport.PRODUCED) == 2   # one update event per affected row

        # A second bulk_update advances each revision again (atomic per-call +1).
        with django_capture_on_commit_callbacks(execute=True):
            MasterThing.cqrs.bulk_update(MasterThing.objects.all(), value=10)
        for r in ReplicaThing.objects.all():
            assert r.value == 10
            assert r.cqrs_revision == 2


class TestMasterSerialization:
    @pytest.mark.django_db
    def test_serializer_and_field_selection(self):
        """A custom CQRS_SERIALIZER builds the payload from its .data; a CQRS_FIELDS
        subset limits the payload to the listed fields. Both append cqrs_revision
        and cqrs_updated."""
        s = SerializedThing.objects.create(name='alpha', value=5)
        sd = s.to_cqrs_dict()
        assert sd['id'] == s.pk
        assert sd['label'] == 'ALPHA'
        assert sd['doubled'] == 10
        assert sd['cqrs_revision'] == 0
        assert 'cqrs_updated' in sd

        f = FieldSubsetMaster.objects.create(name='a', value=10)
        fd = f.to_cqrs_dict()
        assert fd['id'] == f.pk
        assert fd['name'] == 'a'
        assert 'value' not in fd   # excluded by CQRS_FIELDS = ['id', 'name']
        assert fd['cqrs_revision'] == 0


class TestReplicaFieldMapping:
    @pytest.mark.django_db
    def test_cqrs_mapping_renames_master_fields(self):
        """A replica with CQRS_MAPPING stores incoming master fields under the
        mapped replica field names."""
        ReplicaMapped.cqrs_save(_master_data(1, 'alpha', 10, 0))

        obj = ReplicaMapped.objects.get(pk=1)
        assert obj.title == 'alpha'   # master 'name' -> replica 'title'
        assert obj.amount == 10       # master 'value' -> replica 'amount'
        assert obj.cqrs_revision == 0


class TestTrackedFields:
    @pytest.mark.django_db
    def test_tracked_fields_capture_previous_values(self):
        """With CQRS_TRACKED_FIELDS, get_tracked_fields_data() returns the previous
        values of changed tracked fields: None on create, the old value on update."""
        m = TrackedMaster.objects.create(name='a', value=10)
        assert m.get_tracked_fields_data() == {'value': None}

        m2 = TrackedMaster.objects.get(pk=m.pk)
        m2.value = 20
        m2.save()
        assert m2.get_tracked_fields_data() == {'value': 10}

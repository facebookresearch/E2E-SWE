"""Concrete master/replica models built on the agent's mixins.

MasterThing produces CQRS events (default), so the produce->consume pipeline is
exercised end to end against ReplicaThing, which shares the same CQRS_ID.
"""
from django.db import models

from dj_cqrs.mixins import MasterMixin, ReplicaMixin


class MasterThing(MasterMixin):
    CQRS_ID = 'thing'

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)

    class Meta:
        app_label = 'cqrs_harness'


class ReplicaThing(ReplicaMixin):
    CQRS_ID = 'thing'

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)

    class Meta:
        app_label = 'cqrs_harness'


class SerializedThing(MasterMixin):
    """Master model that builds its payload via a custom CQRS_SERIALIZER."""

    CQRS_ID = 'ser'
    CQRS_PRODUCE = False
    CQRS_SERIALIZER = 'cqrs_harness.serializers.LabelSerializer'

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)

    class Meta:
        app_label = 'cqrs_harness'


class ReplicaMapped(ReplicaMixin):
    """Replica whose fields are renamed from the master payload via CQRS_MAPPING."""

    CQRS_ID = 'mapped'
    CQRS_MAPPING = {'id': 'id', 'name': 'title', 'value': 'amount'}

    title = models.CharField(max_length=100)
    amount = models.IntegerField(default=0)

    class Meta:
        app_label = 'cqrs_harness'


class TrackedMaster(MasterMixin):
    """Master that tracks changes to selected fields (CQRS_TRACKED_FIELDS), so the
    previous values of changed fields are captured on save."""

    CQRS_ID = 'tracked'
    CQRS_TRACKED_FIELDS = ['value']

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)

    class Meta:
        app_label = 'cqrs_harness'


class FieldSubsetMaster(MasterMixin):
    """Master that includes only a subset of fields in its CQRS payload."""

    CQRS_ID = 'subset'
    CQRS_PRODUCE = False
    CQRS_FIELDS = ['id', 'name']  # 'value' is intentionally excluded

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)

    class Meta:
        app_label = 'cqrs_harness'



class CommitMaster(MasterMixin):
    """Dedicated master for commit-semantics, isolated from other tests' state."""

    CQRS_ID = 'commit'

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)

    class Meta:
        app_label = 'cqrs_harness'


class CommitReplica(ReplicaMixin):
    CQRS_ID = 'commit'

    name = models.CharField(max_length=100)
    value = models.IntegerField(default=0)

    class Meta:
        app_label = 'cqrs_harness'

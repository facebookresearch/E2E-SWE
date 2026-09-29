"""A minimal serializer for exercising CQRS_SERIALIZER on a master model.

A CQRS serializer is constructed with a model instance and exposes a ``.data``
dict that becomes the payload (the library adds cqrs_revision / cqrs_updated).
"""


class LabelSerializer:
    def __init__(self, instance):
        self._instance = instance

    @property
    def data(self):
        return {
            'id': self._instance.pk,
            'label': self._instance.name.upper(),
            'doubled': self._instance.value * 2,
        }

"""In-process transport for grading (no broker).

produce() records every payload it receives (so tests can assert how many CQRS
events a transaction emits) and routes it straight to the consumer controller,
so the master->replica pipeline runs end to end in one process.
"""
from dj_cqrs.controller import consumer
from dj_cqrs.transport import BaseTransport

PRODUCED = []


def reset():
    PRODUCED.clear()


class CapturingTransport(BaseTransport):
    @staticmethod
    def produce(payload):
        PRODUCED.append(payload)
        consumer.consume(payload)

    @staticmethod
    def consume(payload=None, **kwargs):
        if payload is not None:
            return consumer.consume(payload)

    @staticmethod
    def clean_connection(*args, **kwargs):
        return None

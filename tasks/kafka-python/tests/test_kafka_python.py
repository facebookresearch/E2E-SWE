"""
Tests for kafka-python: a pure Python implementation of the Apache Kafka client library.

Tests cover:
- Integration tests: KafkaProducer and KafkaConsumer against a real Kafka broker
- Unit tests: record serialization, CRC checksums, partitioning, metrics,
  error handling, futures, structs, and partition assignment.
"""

import os
import time
import uuid

import pytest


# ===========================================================================
# Helpers for integration tests
# ===========================================================================

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")


def _wait_for_topic_creation(consumer, topic, timeout=30):
    """Poll consumer until it has partition assignment for the topic."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        consumer.poll(timeout_ms=500)
        assignment = consumer.assignment()
        if assignment:
            return True
    return False


def _random_topic():
    """Generate a random topic name to avoid collisions between tests."""
    return "test_topic_" + uuid.uuid4().hex[:12]


# ===========================================================================
# Unit Tests: Record Serialization
# ===========================================================================

class TestRecordSerialization:
    """Tests for the public record (de)serialization round-trip via kafka.record."""

    def test_memory_records_build_and_read_roundtrip(self):
        """Build a v2 record batch and read it back through the public MemoryRecords API.

        Users serialize records via the public `MemoryRecordsBuilder` and parse them back with
        `MemoryRecords` (the only symbols `kafka.record` exports); a correct wire-format engine
        preserves each record's offset, key, value, and timestamp across the round-trip.
        """
        from kafka.record import MemoryRecordsBuilder, MemoryRecords
        builder = MemoryRecordsBuilder(magic=2, compression_type=0, batch_size=1024 * 1024)
        for i in range(5):
            metadata = builder.append(
                timestamp=1000 + i, key=("key-%d" % i).encode(), value=("val-%d" % i).encode()
            )
            assert metadata is not None
            assert metadata.offset == i
        builder.close()

        records = MemoryRecords(bytes(builder.buffer()))
        read = []
        while records.has_next():
            for rec in records.next_batch():
                read.append(rec)
        assert len(read) == 5
        for i, rec in enumerate(read):
            assert rec.offset == i
            assert rec.key == ("key-%d" % i).encode()
            assert rec.value == ("val-%d" % i).encode()
            assert rec.timestamp == 1000 + i

    def test_legacy_message_set_build_and_read_roundtrip(self):
        """Build legacy MessageSet batches (magic 0 and 1) and read them back the same way.

        The same public builder/reader pair also has to serve the pre-v2 wire formats selected by
        the builder's `magic` argument: offsets, keys, and values must survive the round-trip for
        both, and the v1 message adds the per-message timestamp that v0 has no field for.
        """
        from kafka.record import MemoryRecordsBuilder, MemoryRecords
        for magic in (0, 1):
            builder = MemoryRecordsBuilder(magic=magic, compression_type=0, batch_size=1024 * 1024)
            for i in range(3):
                metadata = builder.append(
                    timestamp=1000 + i, key=("key-%d" % i).encode(), value=("val-%d" % i).encode()
                )
                assert metadata is not None, "magic=%d rejected record %d" % (magic, i)
                assert metadata.offset == i
            builder.close()

            records = MemoryRecords(bytes(builder.buffer()))
            read = []
            while records.has_next():
                for rec in records.next_batch():
                    read.append(rec)
            assert len(read) == 3, "magic=%d round-trip yielded %d records" % (magic, len(read))
            for i, rec in enumerate(read):
                assert rec.offset == i
                assert rec.key == ("key-%d" % i).encode()
                assert rec.value == ("val-%d" % i).encode()
                if magic == 1:
                    assert rec.timestamp == 1000 + i

    def test_builder_refuses_records_once_full_or_closed(self):
        """`append` returns None once the builder is full or closed, without consuming an offset.

        `batch_size` caps the bytes a batch may hold, so a builder given a small budget has to
        account for what it has already written and start refusing records instead of growing
        without bound; a refused record must not advance the auto-assigned offset.
        """
        from kafka.record import MemoryRecordsBuilder
        builder = MemoryRecordsBuilder(magic=2, compression_type=0, batch_size=200)
        accepted = 0
        refused = False
        for i in range(10):
            metadata = builder.append(
                timestamp=1000 + i, key=("k%d" % i).encode(), value=b"v" * 100
            )
            if metadata is None:
                refused = True
                break
            assert metadata.offset == accepted
            accepted += 1
        assert accepted >= 1, "the first record has to fit in the batch"
        assert refused, "append must return None once the batch would exceed batch_size"
        assert builder.next_offset() == accepted

        builder.close()
        assert builder.append(timestamp=2000, key=b"k", value=b"v") is None


# ===========================================================================
# Unit Tests: Murmur2 Partitioner
# ===========================================================================

class TestMurmur2Partitioner:
    """Tests for DefaultPartitioner and murmur2 hash function."""

    def test_murmur2_java_compatibility(self):
        """murmur2 produces identical hashes to the Java Kafka client implementation."""
        from kafka.partitioner.default import murmur2
        # Known values matching Java Utils.murmur2()
        assert murmur2(b"") == 275646681
        assert murmur2(b"hello") == 2132663229
        assert murmur2(b"kafka") == 3496464228
        assert murmur2(b"test") == 716234879
        assert murmur2(b"a") == 2731586172

    def test_partitioner_none_key_uses_available(self):
        """When key is None, partitioner selects from available partitions."""
        from kafka.partitioner.default import DefaultPartitioner
        partitioner = DefaultPartitioner()
        all_partitions = [0, 1, 2, 3, 4]
        available = [2, 3]
        result = partitioner(None, all_partitions, available)
        assert result in available


# ===========================================================================
# Unit Tests: Metrics Framework
# ===========================================================================



class TestQuota:
    """Tests for Quota configuration."""

    def test_quota_upper_bound(self):
        """Users create upper-bound quotas to limit metric rates."""
        from kafka.metrics.quota import Quota
        q = Quota.upper_bound(100.0)
        assert q.is_upper_bound() is True
        assert q.bound == 100.0
        assert q.is_acceptable(99.0) is True
        assert q.is_acceptable(101.0) is False

    def test_quota_lower_bound(self):
        """Users create lower-bound quotas to ensure minimum throughput."""
        from kafka.metrics.quota import Quota
        q = Quota.lower_bound(10.0)
        assert q.is_upper_bound() is False
        assert q.bound == 10.0
        assert q.is_acceptable(11.0) is True
        assert q.is_acceptable(9.0) is False


class TestMetricsRegistry:
    """Tests for the Metrics registry, Sensors, and statistical aggregations."""

    def test_sensor_aggregates_recorded_values(self):
        """A sensor feeds each recorded value through every registered Stat.

        One sensor carries Avg/Count/Max/Min stats over the same recorded series, and each
        KafkaMetric.value() reflects that stat's aggregation -- exercising the shared
        Sensor.record -> Stat plumbing once across the representative stat classes.
        """
        from kafka.metrics.metrics import Metrics
        from kafka.metrics.stats import Avg, Count, Max, Min
        metrics = Metrics()
        try:
            sensor = metrics.sensor("agg-sensor")
            avg_name = metrics.metric_name("avg-val", "test-group")
            count_name = metrics.metric_name("count-val", "test-group")
            max_name = metrics.metric_name("max-val", "test-group")
            min_name = metrics.metric_name("min-val", "test-group")
            sensor.add(avg_name, Avg())
            sensor.add(count_name, Count())
            sensor.add(max_name, Max())
            sensor.add(min_name, Min())
            now = time.time() * 1000
            for v in [10.0, 20.0, 30.0]:
                sensor.record(v, now)
            assert abs(metrics.metrics[avg_name].value(now) - 20.0) < 0.01
            assert metrics.metrics[count_name].value(now) == 3.0
            assert metrics.metrics[max_name].value(now) == 30.0
            assert metrics.metrics[min_name].value(now) == 10.0
        finally:
            metrics.close()

    def test_remove_sensor(self):
        """Users remove sensors when they are no longer needed."""
        from kafka.metrics.metrics import Metrics
        from kafka.metrics.stats import Avg
        metrics = Metrics()
        try:
            sensor = metrics.sensor("removable")
            mn = metrics.metric_name("avg", "group")
            sensor.add(mn, Avg())
            assert metrics.get_sensor("removable") is not None
            metrics.remove_sensor("removable")
            assert metrics.get_sensor("removable") is None
            assert mn not in metrics.metrics
        finally:
            metrics.close()

    def test_duplicate_metric_name_raises(self):
        """Registering a duplicate MetricName raises ValueError."""
        from kafka.metrics.metrics import Metrics
        from kafka.metrics.stats import Avg
        metrics = Metrics()
        try:
            sensor1 = metrics.sensor("s1")
            mn = metrics.metric_name("dup", "group")
            sensor1.add(mn, Avg())
            sensor2 = metrics.sensor("s2")
            with pytest.raises(ValueError):
                sensor2.add(mn, Avg())
        finally:
            metrics.close()


class TestSensorParentChild:
    """Tests for parent-child sensor relationships in the metrics system."""

    def test_child_sensor_records_to_parent(self):
        """When a child sensor records a value, parent sensors also receive it."""
        from kafka.metrics.metrics import Metrics
        from kafka.metrics.stats import Total
        metrics = Metrics()
        try:
            parent = metrics.sensor("parent")
            parent_mn = metrics.metric_name("parent-total", "test")
            parent.add(parent_mn, Total())

            child = metrics.sensor("child", parents=[parent])
            child_mn = metrics.metric_name("child-total", "test")
            child.add(child_mn, Total())

            now = time.time() * 1000
            child.record(10.0, now)
            child.record(20.0, now)

            assert metrics.metrics[child_mn].value(now) == 30.0
            assert metrics.metrics[parent_mn].value(now) == 30.0
        finally:
            metrics.close()


class TestDictReporter:
    """Tests for DictReporter which collects metrics into a dictionary."""

    def test_dict_reporter_captures_metrics(self):
        """Users use DictReporter to snapshot metric values into a dict."""
        from kafka.metrics.metrics import Metrics
        from kafka.metrics.dict_reporter import DictReporter
        from kafka.metrics.stats import Avg
        reporter = DictReporter(prefix='test')
        metrics = Metrics(reporters=[reporter])
        try:
            sensor = metrics.sensor("my-sensor")
            mn = metrics.metric_name("avg-val", "my-group")
            sensor.add(mn, Avg())
            now = time.time() * 1000
            sensor.record(42.0, now)
            snap = reporter.snapshot()
            assert isinstance(snap, dict)
            # Category is built from prefix + group ("test" + "my-group"); the Avg of a
            # single 42.0 record is 42.0. Assert the snapshot actually carries that value.
            assert "test.my-group" in snap
            assert snap["test.my-group"]["avg-val"] == 42.0
        finally:
            metrics.close()


# ===========================================================================
# Unit Tests: Future
# ===========================================================================

class TestFuture:
    """Tests for the thread-safe Future/promise implementation."""

    def test_future_success_path(self):
        """A succeeded future exposes its value, fires success-side callbacks, and propagates.

        Covers the full success contract in one place: is_done/succeeded/value state, add_callback
        and add_both firing with the value, and chain() propagating success to a downstream future.
        """
        from kafka.future import Future
        results = []
        both = []
        downstream = Future()
        f = Future()
        f.add_callback(lambda v: results.append(v))
        f.add_both(lambda v: both.append(v))
        f.chain(downstream)

        assert not f.is_done
        f.success("result")

        assert f.is_done
        assert f.succeeded()
        assert not f.failed()
        assert f.value == "result"
        assert results == ["result"]
        assert both == ["result"]
        # chain() forwards the success (and value) to the downstream future.
        assert downstream.succeeded()
        assert downstream.value == "result"

    def test_future_failure_path(self):
        """A failed future carries its exception, fires error-side callbacks, and propagates.

        Covers the full failure contract in one place: is_done/failed/exception state, add_errback
        and add_both firing with the exception, and chain() propagating failure downstream.
        """
        from kafka.future import Future
        errors = []
        both = []
        downstream = Future()
        f = Future()
        f.add_errback(lambda e: errors.append(e))
        f.add_both(lambda e: both.append(e))
        f.chain(downstream)

        exc = RuntimeError("oops")
        f.failure(exc)

        assert f.is_done
        assert f.failed()
        assert not f.succeeded()
        assert isinstance(f.exception, RuntimeError)
        assert errors == [exc]
        assert both == [exc]
        # chain() forwards the failure to the downstream future.
        assert downstream.failed()

    def test_future_cannot_complete_twice(self):
        """Completing a future twice raises AssertionError."""
        from kafka.future import Future
        f = Future()
        f.success("done")
        with pytest.raises(AssertionError):
            f.success("again")

    def test_future_retriable(self):
        """Future.retriable() delegates to the failing exception's retriable flag.

        This is also the behavioral check for retriable error classes: an error class looked up by
        broker code (for_code) drives a Future to report retriable() per that class's flag, while a
        plain non-Kafka exception is not retriable.
        """
        from kafka.future import Future
        from kafka.errors import for_code, KafkaConnectionError

        # Directly-constructed retriable Kafka error => retriable future.
        f = Future()
        f.failure(KafkaConnectionError("connection lost"))
        assert f.retriable() is True

        # Code-3 (UnknownTopicOrPartitionError) is a retriable broker error; the flag must drive
        # Future.retriable() rather than being a static attribute read in isolation.
        retriable_err_cls = for_code(3)
        f_code = Future()
        f_code.failure(retriable_err_cls("topic missing"))
        assert f_code.retriable() is True

        # A non-retriable plain exception => not retriable.
        f2 = Future()
        f2.failure(RuntimeError("not retriable"))
        assert f2.retriable() is False


# ===========================================================================
# Unit Tests: Error Classes
# ===========================================================================

class TestErrors:
    """Tests for Kafka error classes and error code mapping."""

    def test_for_code_maps_to_error_class(self):
        """Users look up error classes by numeric code from broker responses."""
        from kafka.errors import for_code, NoError, UnknownTopicOrPartitionError
        assert for_code(0) is NoError
        assert for_code(3) is UnknownTopicOrPartitionError

    def test_for_code_unknown_returns_dynamic_class(self):
        """Unknown error codes produce a dynamic subclass of UnknownError."""
        from kafka.errors import for_code, BrokerResponseError
        err_cls = for_code(9999)
        assert issubclass(err_cls, BrokerResponseError)
        assert err_cls.errno == 9999


# ===========================================================================
# Unit Tests: Structs (Named Tuples)
# ===========================================================================




# ===========================================================================
# Unit Tests: Partition Assignors
# ===========================================================================

class TestPartitionAssignors:
    """Tests for partition assignment strategies used in consumer groups."""

    def test_range_assignor_balanced(self, mocker):
        """RangePartitionAssignor distributes partitions evenly among consumers."""
        from kafka.coordinator.assignors.range import RangePartitionAssignor
        from kafka.coordinator.protocol import ConsumerProtocolMemberMetadata_v0

        cluster = mocker.MagicMock()
        cluster.partitions_for_topic.return_value = {0, 1, 2, 3}

        meta = ConsumerProtocolMemberMetadata_v0(0, ["topic1"], b"")
        from kafka.coordinator.subscription import Subscription
        sub = Subscription(meta, None)

        group = {"c1": sub, "c2": sub}
        result = RangePartitionAssignor.assign(cluster, group)
        assert "c1" in result
        assert "c2" in result
        all_assigned = result["c1"].partitions() + result["c2"].partitions()
        assert len(all_assigned) == 4
        assigned_partitions = sorted([(tp.topic, tp.partition) for tp in all_assigned])
        assert assigned_partitions == [("topic1", 0), ("topic1", 1), ("topic1", 2), ("topic1", 3)]

    def test_roundrobin_assignor_balanced(self, mocker):
        """RoundRobinPartitionAssignor distributes partitions in round-robin fashion."""
        from kafka.coordinator.assignors.roundrobin import RoundRobinPartitionAssignor
        from kafka.coordinator.protocol import ConsumerProtocolMemberMetadata_v0

        cluster = mocker.MagicMock()
        cluster.partitions_for_topic.return_value = {0, 1, 2, 3}

        meta = ConsumerProtocolMemberMetadata_v0(0, ["topic1"], b"")
        from kafka.coordinator.subscription import Subscription
        sub = Subscription(meta, None)

        group = {"c1": sub, "c2": sub}
        result = RoundRobinPartitionAssignor.assign(cluster, group)
        all_assigned = result["c1"].partitions() + result["c2"].partitions()
        assert len(all_assigned) == 4
        # Round-robin interleaves the sorted partitions across the sorted consumers:
        # p0->c1, p1->c2, p2->c1, p3->c2. This is distinct from the range split
        # (c1={0,1}, c2={2,3}), so the assertion fails if the assignor is not truly round-robin.
        c1 = sorted((tp.topic, tp.partition) for tp in result["c1"].partitions())
        c2 = sorted((tp.topic, tp.partition) for tp in result["c2"].partitions())
        assert c1 == [("topic1", 0), ("topic1", 2)]
        assert c2 == [("topic1", 1), ("topic1", 3)]

    def test_assignor_metadata_roundtrip(self):
        """Partition assignor metadata round-trips: encoded bytes decode back to the subscription."""
        from kafka.coordinator.assignors.range import RangePartitionAssignor
        from kafka.coordinator.protocol import ConsumerProtocolMemberMetadata_v0
        meta = RangePartitionAssignor.metadata(["topic1", "topic2"])
        encoded = meta.encode()
        assert isinstance(encoded, bytes)
        decoded = ConsumerProtocolMemberMetadata_v0.decode(encoded)
        assert decoded.version == 0
        assert list(decoded.topics) == ["topic1", "topic2"]

    def test_consumer_protocol_assignment_partitions(self):
        """ConsumerProtocolMemberAssignment_v0.partitions() flattens to TopicPartition list."""
        from kafka.coordinator.protocol import ConsumerProtocolMemberAssignment_v0
        from kafka.structs import TopicPartition
        assignment = ConsumerProtocolMemberAssignment_v0(
            0,
            [("topic1", [0, 1]), ("topic2", [0])],
            b""
        )
        partitions = assignment.partitions()
        expected = [
            TopicPartition("topic1", 0),
            TopicPartition("topic1", 1),
            TopicPartition("topic2", 0),
        ]
        assert sorted(partitions, key=lambda tp: (tp.topic, tp.partition)) == expected


# ===========================================================================
# Integration Tests: KafkaProducer and KafkaConsumer against real broker
# (placed last so unit tests always run first within the verifier timeout)
# ===========================================================================

class TestProduceAndConsume:
    """Integration tests verifying end-to-end produce and consume with a real Kafka broker."""

    def test_produce_and_consume_basic(self):
        """Produce N messages and consume them all -- the core end-to-end test."""
        from kafka import KafkaProducer, KafkaConsumer

        topic = _random_topic()
        num_messages = 50

        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            futures = []
            for i in range(num_messages):
                future = producer.send(topic, value=("msg-%d" % i).encode("utf-8"))
                futures.append(future)
            producer.flush(timeout=30)

            for f in futures:
                result = f.get(timeout=30)
                assert result is not None
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            auto_offset_reset='earliest',
            consumer_timeout_ms=30000,
            group_id=None,
        )
        try:
            received = set()
            for msg in consumer:
                received.add(msg.value.decode("utf-8"))
                if len(received) >= num_messages:
                    break
            assert received == set("msg-%d" % i for i in range(num_messages))
        finally:
            consumer.close()

    def test_producer_record_metadata_fields(self):
        """Verify RecordMetadata fields returned by producer.send().get()."""
        from kafka import KafkaProducer, TopicPartition

        topic = _random_topic()
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            future = producer.send(
                topic,
                value=b"test-value",
                key=b"test-key",
                headers=[("hdr", b"val")],
                timestamp_ms=1234567890,
                partition=0,
            )
            record = future.get(timeout=30)

            assert record is not None
            assert record.topic == topic
            assert record.partition == 0
            assert record.topic_partition == TopicPartition(topic, 0)
            assert record.offset >= 0
            # Kafka 4.0 uses message format v2 so timestamp should be what we set
            assert record.timestamp == 1234567890
            assert record.serialized_key_size == 8
            assert record.serialized_value_size == 10
        finally:
            producer.close(timeout=5)

    def test_produce_with_serializers(self):
        """Produce with value_serializer and consume with value_deserializer."""
        from kafka import KafkaProducer, KafkaConsumer

        topic = _random_topic()

        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=str.encode,
            retries=5,
            max_block_ms=30000,
        )
        try:
            for i in range(10):
                producer.send(topic, "hello-%d" % i)
            producer.flush(timeout=30)
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            auto_offset_reset='earliest',
            consumer_timeout_ms=15000,
            group_id=None,
            value_deserializer=bytes.decode,
        )
        try:
            received = set()
            for msg in consumer:
                received.add(msg.value)
                if len(received) >= 10:
                    break
            assert received == set("hello-%d" % i for i in range(10))
        finally:
            consumer.close()

    def test_produce_with_gzip_compression(self):
        """Produce messages with gzip compression and verify they can be consumed."""
        from kafka import KafkaProducer, KafkaConsumer

        topic = _random_topic()
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            compression_type='gzip',
            retries=5,
            max_block_ms=30000,
        )
        try:
            for i in range(20):
                producer.send(topic, value=("compressed-%d" % i).encode("utf-8"))
            producer.flush(timeout=30)
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            auto_offset_reset='earliest',
            consumer_timeout_ms=15000,
            group_id=None,
        )
        try:
            received = set()
            for msg in consumer:
                received.add(msg.value.decode("utf-8"))
                if len(received) >= 20:
                    break
            assert received == set("compressed-%d" % i for i in range(20))
        finally:
            consumer.close()

    def test_consumer_assign_and_seek(self):
        """Use manual partition assignment and seek to verify consumer seek behavior."""
        from kafka import KafkaProducer, KafkaConsumer, TopicPartition

        topic = _random_topic()
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            for i in range(20):
                producer.send(topic, value=("seek-%d" % i).encode("utf-8"), partition=0)
            producer.flush(timeout=30)
        finally:
            producer.close(timeout=5)

        tp = TopicPartition(topic, 0)
        consumer = KafkaConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            auto_offset_reset='earliest',
            consumer_timeout_ms=15000,
            group_id=None,
            enable_auto_commit=False,
        )
        try:
            consumer.assign([tp])
            # Seek to offset 10 -- should get messages 10..19
            consumer.seek(tp, 10)

            received = []
            for msg in consumer:
                received.append(msg.value.decode("utf-8"))
                if len(received) >= 10:
                    break
            assert len(received) == 10
            assert received[0] == "seek-10"
            assert received[-1] == "seek-19"
        finally:
            consumer.close()

    def test_consumer_offset_commit_and_resume(self):
        """Commit offsets with one consumer, resume from committed offset with another."""
        from kafka import KafkaProducer, KafkaConsumer

        topic = _random_topic()
        group_id = "test-group-" + uuid.uuid4().hex[:8]

        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            for i in range(30):
                producer.send(topic, value=("commit-%d" % i).encode("utf-8"), partition=0)
            producer.flush(timeout=30)
        finally:
            producer.close(timeout=5)

        # Consumer 1: read 20 messages, auto-commit, then close
        consumer1 = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=group_id,
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            auto_commit_interval_ms=100,
            consumer_timeout_ms=15000,
        )
        msgs1 = []
        try:
            for msg in consumer1:
                msgs1.append(msg.value.decode("utf-8"))
                if len(msgs1) >= 20:
                    break
        finally:
            consumer1.close()

        assert len(msgs1) == 20

        # Consumer 2: resume from committed offset, should get remaining ~10 messages
        consumer2 = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=group_id,
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            auto_commit_interval_ms=100,
            consumer_timeout_ms=15000,
        )
        msgs2 = []
        try:
            for msg in consumer2:
                msgs2.append(msg.value.decode("utf-8"))
                if len(msgs2) >= 10:
                    break
        finally:
            consumer2.close()

        assert len(msgs2) == 10
        # Verify no overlap -- combined messages should cover all 30
        all_msgs = msgs1 + msgs2
        assert len(all_msgs) == 30

    def test_consumer_poll(self):
        """Use consumer.poll() to fetch messages in batch."""
        from kafka import KafkaProducer, KafkaConsumer

        topic = _random_topic()
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            for i in range(15):
                producer.send(topic, value=("poll-%d" % i).encode("utf-8"))
            producer.flush(timeout=30)
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            auto_offset_reset='earliest',
            consumer_timeout_ms=15000,
            group_id=None,
        )
        try:
            all_msgs = []
            deadline = time.time() + 30
            while len(all_msgs) < 15 and time.time() < deadline:
                records = consumer.poll(timeout_ms=1000)
                for tp, messages in records.items():
                    for msg in messages:
                        all_msgs.append(msg.value.decode("utf-8"))
            assert set(all_msgs) == set("poll-%d" % i for i in range(15))
        finally:
            consumer.close()

    def test_consumer_seek_to_beginning_and_end(self):
        """Test seek_to_beginning and seek_to_end with position()."""
        from kafka import KafkaProducer, KafkaConsumer, TopicPartition

        topic = _random_topic()
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            for i in range(10):
                producer.send(topic, value=b"x", partition=0)
            producer.flush(timeout=30)
        finally:
            producer.close(timeout=5)

        tp = TopicPartition(topic, 0)
        consumer = KafkaConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=None,
            enable_auto_commit=False,
        )
        try:
            consumer.assign([tp])

            consumer.seek_to_end(tp)
            end_pos = consumer.position(tp, timeout_ms=10000)
            assert end_pos == 10

            consumer.seek_to_beginning(tp)
            begin_pos = consumer.position(tp, timeout_ms=10000)
            assert begin_pos == 0
        finally:
            consumer.close()

    def test_producer_partitions_for(self):
        """Verify producer.partitions_for() returns the set of partition ids."""
        from kafka import KafkaProducer

        topic = _random_topic()
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            # Send a message to auto-create the topic
            producer.send(topic, value=b"init").get(timeout=30)
            partitions = producer.partitions_for(topic)
            assert isinstance(partitions, set)
            # The broker is configured with num.partitions=4 (tests/test.sh), so an
            # auto-created topic has exactly partitions {0, 1, 2, 3}.
            assert partitions == {0, 1, 2, 3}
        finally:
            producer.close(timeout=5)

    def test_consumer_subscribe_and_assignment(self):
        """Test subscribe(), subscription(), and assignment() methods."""
        from kafka import KafkaProducer, KafkaConsumer, TopicPartition

        topic = _random_topic()
        group_id = "test-sub-" + uuid.uuid4().hex[:8]

        # Create topic by producing a message
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            producer.send(topic, value=b"init").get(timeout=30)
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=group_id,
            auto_offset_reset='earliest',
        )
        try:
            consumer.subscribe([topic])
            assert topic in consumer.subscription()

            # Poll to trigger group join and get assignment
            deadline = time.time() + 30
            while time.time() < deadline:
                consumer.poll(timeout_ms=500)
                if consumer.assignment():
                    break
            assignment = consumer.assignment()
            # The topic is auto-created by producing one message, so it has the broker's default
            # num.partitions=4 (tests/test.sh). A single subscribed consumer in the group is the
            # sole member, so the assignor gives it every partition: the assignment is
            # deterministically all four partitions, not merely a non-empty subset.
            assert assignment == {TopicPartition(topic, p) for p in (0, 1, 2, 3)}
        finally:
            consumer.close()

    def test_consumer_topics_and_partitions_for_topic(self):
        """Verify consumer.topics() and consumer.partitions_for_topic()."""
        from kafka import KafkaProducer, KafkaConsumer

        topic = _random_topic()

        # Create topic
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            producer.send(topic, value=b"init").get(timeout=30)
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=None,
        )
        try:
            topics = consumer.topics()
            assert topic in topics

            partitions = consumer.partitions_for_topic(topic)
            assert partitions is not None
            assert isinstance(partitions, set)
            # The broker is configured with num.partitions=4 (tests/test.sh), so an auto-created
            # topic has exactly partitions {0, 1, 2, 3} -- matching test_producer_partitions_for.
            assert partitions == {0, 1, 2, 3}
        finally:
            consumer.close()

    def test_consumer_beginning_and_end_offsets(self):
        """Test beginning_offsets() and end_offsets() methods."""
        from kafka import KafkaProducer, KafkaConsumer, TopicPartition

        topic = _random_topic()
        tp = TopicPartition(topic, 0)

        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            for i in range(5):
                producer.send(topic, value=b"x", partition=0)
            producer.flush(timeout=30)
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=None,
        )
        try:
            consumer.assign([tp])
            # Need to poll once to get metadata
            consumer.poll(timeout_ms=5000)

            begin_offsets = consumer.beginning_offsets([tp])
            assert tp in begin_offsets
            assert begin_offsets[tp] == 0

            end_offsets = consumer.end_offsets([tp])
            assert tp in end_offsets
            assert end_offsets[tp] == 5
        finally:
            consumer.close()

    def test_produce_with_key_partitioning(self):
        """Messages with the same key should go to the same partition."""
        from kafka import KafkaProducer

        topic = _random_topic()
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            retries=5,
            max_block_ms=30000,
        )
        try:
            key = b"consistent-key"
            results = []
            for i in range(10):
                future = producer.send(topic, value=b"val", key=key)
                results.append(future.get(timeout=30))
            producer.flush(timeout=30)

            # All messages with the same key should land on the same partition
            partitions = set(r.partition for r in results)
            assert len(partitions) == 1
        finally:
            producer.close(timeout=5)


# ===========================================================================
# Unit Tests: Admin API Data Types and Enums
# ===========================================================================

class TestAdminACLDataTypes:
    """Tests for admin ACL data types: ResourceType, ACLOperation, ACLPermissionType, ResourcePattern, ACL."""

    def test_acl_validation_and_equality(self):
        """ACL enforces its validation rules and compares/hashes by value.

        A concrete ACL rejects the filter-only ANY operation/permission and a ResourcePatternFilter
        (rather than a concrete ResourcePattern), while an ACLFilter -- for which those sentinels
        are exactly what makes it a filter -- accepts them; two ACLs built from equal fields are
        equal and hash-equal, while changing any one field breaks both.
        """
        from kafka.admin import (
            ACL, ACLFilter, ACLOperation, ACLPermissionType,
            ACLResourcePatternType, ResourceType, ResourcePattern, ResourcePatternFilter,
        )
        from kafka.errors import IllegalArgumentError

        resource_pattern = ResourcePattern(
            resource_type=ResourceType.TOPIC,
            resource_name="my-topic",
            pattern_type=ACLResourcePatternType.LITERAL,
        )

        # A concrete ACL refuses the filter-only ANY operation -- real validation logic, not storage.
        with pytest.raises(IllegalArgumentError):
            ACL(
                principal="User:alice", host="*",
                operation=ACLOperation.ANY,
                permission_type=ACLPermissionType.ALLOW,
                resource_pattern=resource_pattern,
            )
        # ...and the filter-only ANY permission type.
        with pytest.raises(IllegalArgumentError):
            ACL(
                principal="User:alice", host="*",
                operation=ACLOperation.READ,
                permission_type=ACLPermissionType.ANY,
                resource_pattern=resource_pattern,
            )
        # ...and a ResourcePatternFilter where a concrete ResourcePattern is required.
        with pytest.raises(IllegalArgumentError):
            ACL(
                principal="User:alice", host="*",
                operation=ACLOperation.READ,
                permission_type=ACLPermissionType.ALLOW,
                resource_pattern=ResourcePatternFilter(
                    resource_type=ResourceType.TOPIC,
                    resource_name="my-topic",
                    pattern_type=ACLResourcePatternType.LITERAL,
                ),
            )

        # The very same sentinels are legal on an ACLFilter -- the validation belongs to the
        # concrete binding only, or describe_acls/delete_acls could never match on ANY.
        acl_filter = ACLFilter(
            principal=None, host=None,
            operation=ACLOperation.ANY,
            permission_type=ACLPermissionType.ANY,
            resource_pattern=ResourcePatternFilter(
                resource_type=ResourceType.ANY,
                resource_name=None,
                pattern_type=ACLResourcePatternType.ANY,
            ),
        )
        assert acl_filter.operation == ACLOperation.ANY
        assert acl_filter.permission_type == ACLPermissionType.ANY
        assert acl_filter.resource_pattern.resource_type == ResourceType.ANY

        # Value semantics: equal fields => equal + hash-equal; one differing field => unequal.
        def make_acl(host="*"):
            return ACL(
                principal="User:alice", host=host,
                operation=ACLOperation.READ,
                permission_type=ACLPermissionType.ALLOW,
                resource_pattern=ResourcePattern(
                    resource_type=ResourceType.TOPIC,
                    resource_name="my-topic",
                    pattern_type=ACLResourcePatternType.LITERAL,
                ),
            )

        acl_a = make_acl()
        acl_b = make_acl()
        acl_diff = make_acl(host="10.0.0.1")
        assert acl_a == acl_b
        assert hash(acl_a) == hash(acl_b)
        assert acl_a != acl_diff


# ===========================================================================
# Integration Tests: KafkaAdminClient against real broker
# ===========================================================================

class TestAdminClient:
    """Integration tests for KafkaAdminClient topic and cluster operations against a real broker."""

    def test_admin_create_list_delete_topic(self):
        """Users create a topic via admin client, verify it appears in list_topics, then delete it."""
        from kafka.admin import KafkaAdminClient, NewTopic

        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        try:
            topic_name = "admin_test_" + uuid.uuid4().hex[:8]

            new_topic = NewTopic(name=topic_name, num_partitions=2, replication_factor=1)
            admin.create_topics([new_topic])
            time.sleep(2)

            topics = admin.list_topics()
            assert topic_name in topics

            admin.delete_topics([topic_name])
            time.sleep(2)

            topics_after = admin.list_topics()
            assert topic_name not in topics_after
        finally:
            admin.close()

    def test_admin_describe_topics(self):
        """Users describe topics to get partition and replica info."""
        from kafka.admin import KafkaAdminClient
        from kafka import KafkaProducer

        topic_name = "admin_desc_" + uuid.uuid4().hex[:8]

        producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, retries=5, max_block_ms=30000)
        try:
            producer.send(topic_name, value=b"init").get(timeout=30)
        finally:
            producer.close(timeout=5)

        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        try:
            described = admin.describe_topics([topic_name])
            assert len(described) >= 1
            topic_info = [t for t in described if t.get('topic', t.get('name', '')) == topic_name]
            assert len(topic_info) == 1
            assert 'partitions' in topic_info[0]
            # The topic is auto-created by producing one message, so it has the broker's default
            # num.partitions=4 (tests/test.sh): describe must report exactly 4 partition entries.
            assert len(topic_info[0]['partitions']) == 4
        finally:
            admin.close()

    def test_admin_describe_cluster(self):
        """Users query cluster metadata to discover brokers and the controller."""
        from kafka.admin import KafkaAdminClient

        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        try:
            cluster_meta = admin.describe_cluster()
            assert 'brokers' in cluster_meta
            # The verifier broker is a single KRaft node (node.id=1) advertised at
            # localhost:9092 (tests/test.sh), so the cluster description is fully deterministic:
            # exactly one broker with node_id 1 at localhost:9092 (spec section 13.4).
            assert len(cluster_meta['brokers']) == 1
            broker = cluster_meta['brokers'][0]
            assert broker['node_id'] == 1
            assert broker['host'] == 'localhost'
            assert broker['port'] == 9092
        finally:
            admin.close()



# ===========================================================================
# Unit Tests: Security / SASL
# ===========================================================================

class TestSASLMechanisms:
    """Tests for SASL authentication mechanism implementations."""

    def test_sasl_mechanism_registry(self):
        """SASL mechanism registry maps each standard mechanism name to its implementation class."""
        from kafka.sasl import get_sasl_mechanism
        from kafka.sasl.plain import SaslMechanismPlain
        from kafka.sasl.scram import SaslMechanismScram
        from kafka.sasl.oauth import SaslMechanismOAuth
        assert get_sasl_mechanism('PLAIN') is SaslMechanismPlain
        assert get_sasl_mechanism('SCRAM-SHA-256') is SaslMechanismScram
        assert get_sasl_mechanism('SCRAM-SHA-512') is SaslMechanismScram
        assert get_sasl_mechanism('OAUTHBEARER') is SaslMechanismOAuth

    def test_sasl_register_get_and_overwrite(self):
        """The SASL registry round-trips a custom mechanism, rejects duplicates, and honors overwrite.

        Registering a name makes get_sasl_mechanism return that class; re-registering the same name
        without overwrite raises ValueError; re-registering with overwrite=True replaces it.
        """
        from kafka.sasl import register_sasl_mechanism, get_sasl_mechanism
        from kafka.sasl.abc import SaslMechanism

        class MechA(SaslMechanism):
            def __init__(self, **config): pass
            def auth_bytes(self): return b'a'
            def receive(self, auth_bytes): pass
            def is_done(self): return True
            def is_authenticated(self): return True

        class MechB(SaslMechanism):
            def __init__(self, **config): pass
            def auth_bytes(self): return b'b'
            def receive(self, auth_bytes): pass
            def is_done(self): return True
            def is_authenticated(self): return True

        name = 'REGISTRY-TEST-' + uuid.uuid4().hex[:6]

        # Register then look up: the registry maps the name to the class.
        register_sasl_mechanism(name, MechA)
        assert get_sasl_mechanism(name) is MechA

        # Duplicate without overwrite is rejected.
        with pytest.raises(ValueError, match="already defined"):
            register_sasl_mechanism(name, MechA)

        # overwrite=True replaces the existing registration.
        register_sasl_mechanism(name, MechB, overwrite=True)
        assert get_sasl_mechanism(name) is MechB

    def test_sasl_plain_auth_bytes(self):
        """SASL PLAIN mechanism produces RFC-4616 auth bytes from username and password."""
        from kafka.sasl.plain import SaslMechanismPlain

        mech = SaslMechanismPlain(
            sasl_plain_username='alice',
            sasl_plain_password='s3cret',
            security_protocol='SASL_SSL',
        )
        auth = mech.auth_bytes()
        parts = auth.split(b'\x00')
        assert len(parts) == 3
        assert parts[0] == b'alice'
        assert parts[1] == b'alice'
        assert parts[2] == b's3cret'
        assert not mech.is_done()

    def test_sasl_plain_receive_success(self):
        """SASL PLAIN marks done and authenticated on receiving empty server response."""
        from kafka.sasl.plain import SaslMechanismPlain

        mech = SaslMechanismPlain(
            sasl_plain_username='bob',
            sasl_plain_password='pass',
            security_protocol='SASL_SSL',
        )
        mech.receive(b'')
        assert mech.is_done()
        assert mech.is_authenticated()

    def test_sasl_plain_missing_credentials_raises(self):
        """SASL PLAIN raises if username or password is missing."""
        from kafka.sasl.plain import SaslMechanismPlain

        with pytest.raises(AssertionError):
            SaslMechanismPlain(sasl_plain_password='pass', security_protocol='SASL_SSL')
        with pytest.raises(AssertionError):
            SaslMechanismPlain(sasl_plain_username='user', security_protocol='SASL_SSL')

    def test_scram_client_sha256_vs_sha512_use_different_hash(self):
        """SCRAM-SHA-256 and SCRAM-SHA-512 produce different client proofs for the same credentials.

        Each mechanism is driven through the public `SaslMechanismScram` wrapper: `auth_bytes()`
        emits the client-first, `receive()` consumes a server-first built from that client's nonce,
        and the next `auth_bytes()` emits the client-final proof. Because the hash differs, a correct
        runtime hash selection must yield different client-final proofs (the `p=` field).
        """
        import base64
        from kafka.sasl.scram import SaslMechanismScram

        proofs = {}
        for mechanism in ('SCRAM-SHA-256', 'SCRAM-SHA-512'):
            mech = SaslMechanismScram(
                sasl_plain_username='u',
                sasl_plain_password='p',
                sasl_mechanism=mechanism,
                security_protocol='SASL_SSL',
            )
            client_first = mech.auth_bytes()
            client_nonce = client_first.split(b'r=')[1]
            server_nonce = client_nonce + b'server-extra'
            server_first = (
                b'r=' + server_nonce
                + b',s=' + base64.b64encode(b'a-fixed-salt-16b')
                + b',i=4096'
            )
            mech.receive(server_first)
            client_final = mech.auth_bytes()
            proofs[mechanism] = client_final.split(b',p=')[1]

        # Same credentials, different hash => different client-final proof.
        assert proofs['SCRAM-SHA-256'] != proofs['SCRAM-SHA-512']

    def test_oauth_mechanism_requires_token_provider(self):
        """SASL OAuth raises if token provider is missing or wrong type."""
        from kafka.sasl.oauth import SaslMechanismOAuth

        with pytest.raises(AssertionError):
            SaslMechanismOAuth()

        with pytest.raises(AssertionError):
            SaslMechanismOAuth(sasl_oauth_token_provider="not-a-provider")

    def test_oauth_token_provider_interface(self):
        """A custom AbstractTokenProvider can be used with OAuth mechanism to produce auth bytes."""
        from kafka.sasl.oauth import SaslMechanismOAuth, AbstractTokenProvider

        class MyTokenProvider(AbstractTokenProvider):
            def token(self):
                return "my-jwt-token-123"
            def extensions(self):
                return {"key1": "val1"}

        mech = SaslMechanismOAuth(sasl_oauth_token_provider=MyTokenProvider())
        auth = mech.auth_bytes()
        assert b'Bearer my-jwt-token-123' in auth
        assert b'key1=val1' in auth
        assert auth.startswith(b'n,,\x01')
        assert auth.endswith(b'\x01\x01')


# ===========================================================================
# Unit Tests: Codec availability detection
# ===========================================================================

class TestCodecAvailability:
    """Tests for codec compression used in record serialization."""

    def test_gzip_encode_decode_roundtrip(self):
        """gzip_encode and gzip_decode correctly roundtrip arbitrary data."""
        from kafka.codec import gzip_encode, gzip_decode
        payload = b"kafka message payload " * 50
        compressed = gzip_encode(payload)
        assert len(compressed) < len(payload)
        decompressed = gzip_decode(compressed)
        assert decompressed == payload


# ===========================================================================
# Additional Admin Tests: create_partitions, list/describe groups, configs
# ===========================================================================

class TestAdminIntegrationExtended:
    """Extended integration tests for KafkaAdminClient operations against a real broker."""

    def test_admin_create_partitions(self):
        """Users increase the partition count of an existing topic via create_partitions."""
        from kafka.admin import KafkaAdminClient, NewTopic, NewPartitions

        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        try:
            topic_name = "admin_parts_" + uuid.uuid4().hex[:8]
            admin.create_topics([NewTopic(name=topic_name, num_partitions=2, replication_factor=1)])
            time.sleep(2)

            admin.create_partitions({topic_name: NewPartitions(total_count=4)})
            time.sleep(2)

            described = admin.describe_topics([topic_name])
            topic_info = [t for t in described if t.get('topic', t.get('name', '')) == topic_name]
            assert len(topic_info) == 1
            assert len(topic_info[0]['partitions']) == 4
        finally:
            admin.close()

    def test_admin_list_consumer_groups(self):
        """Users list all consumer groups in the cluster."""
        from kafka.admin import KafkaAdminClient
        from kafka import KafkaProducer, KafkaConsumer

        topic = "admin_grp_list_" + uuid.uuid4().hex[:8]
        group_id = "test-grp-list-" + uuid.uuid4().hex[:8]

        producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, retries=5, max_block_ms=30000)
        try:
            producer.send(topic, value=b"init").get(timeout=30)
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            topic, bootstrap_servers=KAFKA_BOOTSTRAP, group_id=group_id,
            auto_offset_reset='earliest', consumer_timeout_ms=5000,
        )
        try:
            consumer.poll(timeout_ms=3000)
        finally:
            consumer.close()

        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        try:
            groups = admin.list_consumer_groups()
            assert isinstance(groups, list)
            group_ids = [g[0] if isinstance(g, (list, tuple)) else g for g in groups]
            assert group_id in group_ids
        finally:
            admin.close()

    def test_admin_describe_consumer_groups(self):
        """Users describe a consumer group to see members and state."""
        from kafka.admin import KafkaAdminClient
        from kafka import KafkaProducer, KafkaConsumer

        topic = "admin_grp_desc_" + uuid.uuid4().hex[:8]
        group_id = "test-grp-desc-" + uuid.uuid4().hex[:8]

        producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, retries=5, max_block_ms=30000)
        try:
            producer.send(topic, value=b"init").get(timeout=30)
        finally:
            producer.close(timeout=5)

        consumer = KafkaConsumer(
            topic, bootstrap_servers=KAFKA_BOOTSTRAP, group_id=group_id,
            auto_offset_reset='earliest', consumer_timeout_ms=5000,
        )
        try:
            consumer.poll(timeout_ms=3000)
        finally:
            consumer.close()

        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        try:
            described = admin.describe_consumer_groups([group_id])
            assert isinstance(described, (list, dict))
            # describe must identify the requested group, not merely return some non-empty result.
            if isinstance(described, dict):
                assert group_id in described
            else:
                # Each entry describes one requested group; its `group` field is that group's id.
                described_group_ids = [getattr(d, 'group', d[1] if isinstance(d, (list, tuple)) else d) for d in described]
                assert group_id in described_group_ids
        finally:
            admin.close()

    def test_admin_describe_configs_for_broker(self):
        """Users describe broker configuration via ConfigResource."""
        from kafka.admin import KafkaAdminClient, ConfigResource, ConfigResourceType

        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        try:
            cluster = admin.describe_cluster()
            broker_id = str(cluster['brokers'][0]['node_id'])
            resource = ConfigResource(ConfigResourceType.BROKER, broker_id)
            configs = admin.describe_configs([resource])
            assert configs is not None
            assert len(configs) > 0
            # describe_configs returns the raw list of DescribeConfigsResponse structs (spec section
            # 13.5): each exposes a `resources` array whose entries are positional tuples
            # (error_code, error_message, resource_type, resource_name, config_entries), so
            # config_entries is the last element. A broker with config returns >=1 non-empty entry.
            total_config_entries = sum(
                len(res[-1]) for response in configs for res in response.resources
            )
            assert total_config_entries > 0
        finally:
            admin.close()


class TestClusterMetadataExtended:
    """Extended tests for ClusterMetadata topic/partition/listener management."""

    def test_cluster_topics_and_brokers_populate_on_update(self):
        """ClusterMetadata starts empty and reflects topics/brokers after a real metadata update."""
        from kafka.cluster import ClusterMetadata
        from kafka.protocol.metadata import MetadataResponse
        from kafka.structs import BrokerMetadata

        cluster = ClusterMetadata()
        assert cluster.topics() == set()
        assert cluster.brokers() == set()

        # Apply a v0 MetadataResponse with one broker and one healthy topic (error_code 0) carrying
        # a single partition. update_metadata must parse it so topics()/brokers() become populated.
        # v0 topic entry: (error_code, topic, partitions); v0 partition: (error_code, partition,
        # leader, replicas, isr).
        cluster.update_metadata(
            MetadataResponse[0](
                [(1, "broker-host", 9092)],
                [(0, "topic-a", [(0, 0, 1, [1], [1])])],
            )
        )
        assert cluster.topics() == {"topic-a"}
        assert cluster.brokers() == {BrokerMetadata(1, "broker-host", 9092, None)}
        assert cluster.partitions_for_topic("topic-a") == {0}

    def test_cluster_unknown_lookups_return_none(self):
        """All unknown-id lookups on an empty ClusterMetadata return None."""
        from kafka.cluster import ClusterMetadata
        from kafka.structs import TopicPartition
        cluster = ClusterMetadata()
        assert cluster.partitions_for_topic("nonexistent") is None
        assert cluster.leader_for_partition(TopicPartition("x", 0)) is None
        assert cluster.coordinator_for_group("unknown-group") is None
        assert cluster.broker_metadata(999) is None

    def test_cluster_add_remove_listener(self):
        """A registered listener fires on each metadata update and stops firing once removed."""
        from kafka.cluster import ClusterMetadata
        from kafka.protocol.metadata import MetadataResponse
        cluster = ClusterMetadata()
        events = []
        # Listeners are invoked with the updated cluster as the sole positional argument.
        listener = lambda updated: events.append(updated)
        cluster.add_listener(listener)

        # A non-empty broker list makes update_metadata apply (empty lists are ignored).
        cluster.update_metadata(MetadataResponse[0]([(0, "host", 9092)], []))
        assert events == [cluster]

        # After removal the listener no longer fires on subsequent updates.
        cluster.remove_listener(listener)
        cluster.update_metadata(MetadataResponse[0]([(0, "host", 9092)], []))
        assert events == [cluster]

    def test_cluster_metadata_staleness_and_refresh_timing(self):
        """ClusterMetadata's ttl()/request_update() drive real metadata-refresh timing."""
        from kafka.cluster import ClusterMetadata
        from kafka.future import Future
        cluster = ClusterMetadata(retry_backoff_ms=250)

        # A freshly constructed cluster has no metadata yet, so it is immediately stale:
        # ttl() must compute to 0 (an update is needed right now), not the max-age constant.
        assert cluster.ttl() == 0

        # request_update() flags the metadata for refresh and hands back a pending Future
        # whose result will be the cluster once an update is applied.
        future = cluster.request_update()
        assert isinstance(future, Future)
        assert not future.is_done
        # Still stale until an actual update lands, so ttl() stays 0 rather than resetting.
        assert cluster.ttl() == 0

        # refresh_backoff bounds the retry wait between failed metadata requests.
        assert cluster.refresh_backoff() == 250


# ===========================================================================
# CLI Tests: exercise real CLI command paths end-to-end against the broker
# ===========================================================================

class TestCLIEntryPoints:
    """Integration tests for CLI entry points exercising real command paths."""

    def test_producer_consumer_cli_roundtrip(self):
        """`python -m kafka.producer` publishes stdin lines that `python -m kafka.consumer` reads back."""
        import subprocess
        import sys

        topic = _random_topic()
        group_id = "cli-grp-" + uuid.uuid4().hex[:8]
        lines = ["cli-msg-%d" % i for i in range(5)]

        # Produce: feed the lines on stdin; the producer CLI sends one message per line.
        produce = subprocess.run(
            [sys.executable, "-m", "kafka.producer", "-b", KAFKA_BOOTSTRAP, "-t", topic],
            input="\n".join(lines) + "\n",
            capture_output=True, text=True, timeout=60,
        )
        assert produce.returncode == 0, produce.stderr

        # Consume: the consumer CLI prints each message value; consumer_timeout_ms ends iteration.
        consume = subprocess.run(
            [
                sys.executable, "-m", "kafka.consumer",
                "-b", KAFKA_BOOTSTRAP, "-t", topic, "-g", group_id,
                "-c", "auto_offset_reset=earliest", "-c", "consumer_timeout_ms=15000",
            ],
            capture_output=True, text=True, timeout=60,
        )
        assert consume.returncode == 0, consume.stderr
        out_lines = set(consume.stdout.split())
        for line in lines:
            assert line in out_lines

    def test_admin_cli_topics_list(self):
        """`python -m kafka.admin topics list` lists an existing topic via the real admin command path."""
        import subprocess
        import sys
        from kafka import KafkaProducer

        topic = "cli_admin_" + uuid.uuid4().hex[:8]
        producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP, retries=5, max_block_ms=30000)
        try:
            producer.send(topic, value=b"init").get(timeout=30)
        finally:
            producer.close(timeout=5)

        result = subprocess.run(
            [sys.executable, "-m", "kafka.admin", "-b", KAFKA_BOOTSTRAP, "topics", "list"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert topic in result.stdout


# ===========================================================================
# Additional Security Tests: SCRAM full handshake, SASL overwrite
# ===========================================================================

class TestSASLExtended:
    """Extended SASL tests covering full SCRAM handshake and mechanism overwrite."""

    def test_scram_server_nonce_validation(self):
        """SCRAM rejects a server-first whose nonce doesn't start with the client nonce.

        Driven through the public `SaslMechanismScram` wrapper: `auth_bytes()` emits the
        client-first, and feeding a server-first with a mismatched nonce to `receive()` raises
        `ValueError`. The exact wording is an implementation detail, so only the exception type
        is asserted.
        """
        import base64
        from kafka.sasl.scram import SaslMechanismScram

        mech = SaslMechanismScram(
            sasl_plain_username='user',
            sasl_plain_password='pass',
            sasl_mechanism='SCRAM-SHA-256',
            security_protocol='SASL_SSL',
        )
        mech.auth_bytes()  # client-first; establishes the client nonce.

        bad_server_first = b"r=completely-different-nonce,s=" + base64.b64encode(b"salt") + b",i=4096"
        with pytest.raises(ValueError):
            mech.receive(bad_server_first)

    def test_sasl_plain_non_authenticated_on_nonempty_response(self):
        """SASL PLAIN is done but not authenticated when server sends non-empty response."""
        from kafka.sasl.plain import SaslMechanismPlain
        mech = SaslMechanismPlain(
            sasl_plain_username='user',
            sasl_plain_password='pass',
            security_protocol='SASL_SSL',
        )
        mech.receive(b'error: bad credentials')
        assert mech.is_done()
        assert not mech.is_authenticated()

    def test_scram_mechanism_full_handshake_via_wrapper(self):
        """SaslMechanismScram drives a complete two-round-trip handshake through its state machine.

        Unlike test_scram_full_handshake_sha256 (which exercises the bare ScramClient), this drives
        the SaslMechanismScram wrapper: auth_bytes/receive must dispatch by internal state across
        client-first -> server-first -> client-final -> server-final, ending done and authenticated.
        """
        import base64, hashlib, hmac, os
        from kafka.sasl.scram import SaslMechanismScram

        mech = SaslMechanismScram(
            sasl_plain_username='user',
            sasl_plain_password='pass',
            sasl_mechanism='SCRAM-SHA-256',
            security_protocol='SASL_SSL',
        )
        # State 0: not yet done, and auth_bytes() emits the client-first message.
        assert not mech.is_done()
        assert not mech.is_authenticated()
        client_first = mech.auth_bytes()
        assert client_first.startswith(b'n,,n=user,r=')
        client_nonce = client_first.split(b'r=')[1]
        # The client-first-bare (everything after the b'n,,' gs2 header) opens the auth message.
        client_first_bare = client_first[len(b'n,,'):]

        # Feed a server-first; the wrapper advances to state 1 (still not done).
        salt = os.urandom(16)
        iterations = 4096
        server_nonce = client_nonce + b'server-extra'
        server_first = b'r=' + server_nonce + b',s=' + base64.b64encode(salt) + b',i=' + str(iterations).encode()
        mech.receive(server_first)
        assert not mech.is_done()

        # State 1: auth_bytes() now emits the client-final proof message.
        client_final = mech.auth_bytes()
        assert client_final.startswith(b'c=biws,r=' + server_nonce)
        assert b',p=' in client_final

        # Compute the matching server-final signature purely from the public handshake (RFC 5802)
        # plus the known password -- no reach into the wrapper's private helper. The auth message
        # is client-first-bare + ',' + server-first + ',c=biws,r=' + server-nonce; the salted
        # password is PBKDF2-HMAC-SHA256 over (password, salt, iterations).
        auth_message = client_first_bare + b',' + server_first + b',c=biws,r=' + server_nonce
        salted_password = hashlib.pbkdf2_hmac('sha256', b'pass', salt, iterations)
        server_key = hmac.new(salted_password, b'Server Key', hashlib.sha256).digest()
        server_signature = hmac.new(server_key, auth_message, hashlib.sha256).digest()

        # Feed the matching server-final; the wrapper reaches state 2: done and authenticated.
        mech.receive(b'v=' + base64.b64encode(server_signature))
        assert mech.is_done()
        assert mech.is_authenticated()

# kafka-python

Implement `kafka-python`, a pure Python client library for the Apache Kafka distributed streaming platform ( https://github.com/apache/kafka ). The library provides a high-level KafkaProducer and KafkaConsumer for sending and receiving messages, plus the underlying protocol primitives described below: record batch serialization, compression codecs, metrics collection, partition assignment strategies, a `KafkaAdminClient` for managing topics and other cluster metadata, SASL authentication mechanisms for security, and `python -m` command-line tools for admin, produce, and consume operations.

Implement every interface exactly as specified in the sections that follow. Signatures, default values, return shapes, and byte-level formats are normative — match them precisely. The package must be importable as `import kafka`.

## Dependencies

The environment is **offline**: there is no network access, and every dependency is **already
installed**. Do **not** install anything (no `pip install`, no `apt-get`) and do not add packages to
`pyproject.toml`/`setup.py` expecting them to be fetched. The project is installed for you by a
`setup.sh` that runs **offline** (`pip install -e . --no-build-isolation`), so the package only needs
to be a valid editable install with its `[build-system]` (`setuptools`) — the build backend is
pre-baked. The core library has **no required runtime dependencies**.

The following are pre-installed and available to import conditionally (the library must still degrade
gracefully — i.e. its codec-availability checks must return `False` and raise only when an unavailable
codec is actually used):

- `crc32c` — for hardware-accelerated CRC-32C checksums (a pure-Python fallback must also be provided,
  since the library must work whether or not this package is importable).
- `python-snappy` — for Snappy compression.
- `lz4` — for LZ4 compression.
- `zstandard` — for Zstd compression.

Standard library modules used: `struct`, `io`, `gzip`, `abc`, `collections`, `threading`, `time`,
`uuid`, `functools`, `logging`, `inspect`, `sys`, `copy`, `itertools`, `random`, `socket`, `select`,
`selectors`, `ssl`, `atexit`, `weakref`, `warnings`, `hashlib`, `hmac`, `re`.

## Package Structure

The package is named `kafka`. It should be importable as `import kafka` and provide subpackages for `kafka.protocol`, `kafka.record`, `kafka.metrics`, `kafka.coordinator`, `kafka.partitioner`, `kafka.producer`, `kafka.consumer`, `kafka.admin`,  etc.

Top-level imports:
```python
from kafka import KafkaProducer, KafkaConsumer, TopicPartition, OffsetAndMetadata
```

### Kafka wire protocol

The producer, consumer, and admin client talk to a real broker over the **Apache Kafka binary wire protocol** (request/response framing, API keys, version negotiation, correlation IDs, and the versioned request/response Struct schemas). This protocol is an external published standard — implement it as defined at https://kafka.apache.org/protocol — and expose it under `kafka.protocol.*` (e.g. `kafka.protocol.metadata.MetadataResponse`). The broker-backed and CLI behaviors below assume standard Kafka protocol semantics; the spec specifies the Python public surface and does not restate the wire format.

---

## 1. KafkaProducer (`kafka.producer.kafka` / `kafka.KafkaProducer`)

A Kafka client that publishes records to the Kafka cluster. The producer is thread safe. It maintains a background I/O thread (Sender) that turns buffered records into requests and transmits them to the cluster.

### Constructor

```python
KafkaProducer(**configs)
```

Key configuration parameters (passed as keyword arguments):

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bootstrap_servers` | str or list | `'localhost'` | `host[:port]` string(s) for initial cluster connection |
| `client_id` | str | auto-generated | Client identifier for server-side logging |
| `key_serializer` | callable | None | Serializer for message keys |
| `value_serializer` | callable | None | Serializer for message values |
| `compression_type` | str | None | Compression: `'gzip'`, `'snappy'`, `'lz4'`, `'zstd'`, or None |
| `acks` | int/str | 1 | Number of acknowledgments: 0, 1, or `'all'`/`-1` |
| `retries` | int | inf | Number of retries for failed sends |
| `batch_size` | int | 16384 | Max bytes per batch |
| `linger_ms` | int | 0 | Milliseconds to wait for more records before sending |
| `max_block_ms` | int | 60000 | Max time to block on send/partitions_for |
| `max_request_size` | int | 1048576 | Max size of a request |
| `partitioner` | callable | DefaultPartitioner() | Partitioner for key-based routing |
| `api_version` | tuple | None | Kafka API version; None for auto-detection |
| `enable_idempotence` | bool | False | Enable idempotent producer |
| `transactional_id` | str | None | Transactional ID for exactly-once semantics |
| `metadata_max_age_ms` | int | 300000 | Max age before metadata refresh |
| `request_timeout_ms` | int | 30000 | Client request timeout |
| `retry_backoff_ms` | int | 100 | Backoff between retries |
| `reconnect_backoff_ms` | int | 50 | Reconnect backoff |
| `max_in_flight_requests_per_connection` | int | 5 | Max unacked requests per connection |
| `security_protocol` | str | `'PLAINTEXT'` | Protocol: PLAINTEXT, SSL, SASL_PLAINTEXT, SASL_SSL |
| `allow_auto_create_topics` | bool | True | Allow auto-creation of topics |

The constructor connects to the Kafka cluster, starts the background Sender thread, and is ready to send messages.

### Methods

**`send(topic, value=None, key=None, headers=None, partition=None, timestamp_ms=None)`**
- Asynchronously publishes a message. Returns a `FutureRecordMetadata`.
- `topic` (str): required
- `value` (bytes or None): message value
- `key` (bytes or None): message key for partitioning
- `headers` (list of (str, bytes) tuples): optional headers
- `partition` (int): explicit partition; if None, uses partitioner
- `timestamp_ms` (int): epoch milliseconds; defaults to current time
- The returned future has a `.get(timeout=None)` method that blocks and returns a `RecordMetadata` namedtuple, or raises on error.

**`flush(timeout=None)`**
- Block until all buffered records have been sent. `timeout` is in seconds.

**`close(timeout=None)`**
- Close the producer, flushing pending records. `timeout` is in seconds.

**`partitions_for(topic)`**
- Returns the set of partition IDs for the given topic.

**`metrics(raw=False)`**
- Returns dict of producer performance metrics.

### RecordMetadata

`RecordMetadata` is a namedtuple returned by `future.get()`:

```python
RecordMetadata = namedtuple('RecordMetadata', [
    'topic', 'partition', 'topic_partition', 'offset', 'timestamp',
    'checksum', 'serialized_key_size', 'serialized_value_size',
    'serialized_header_size'
])
```

### FutureRecordMetadata

The future returned by `send()` has:
- `.get(timeout=None)` -> `RecordMetadata` (blocks until result, raises on timeout/error)
- `.succeeded()` -> bool
- `.failed()` -> bool
- `.is_done` -> bool
- `.value` -> RecordMetadata (after success)
- `.exception` -> Exception (after failure)

---

## 2. KafkaConsumer (`kafka.consumer.group` / `kafka.KafkaConsumer`)

Consumes records from a Kafka cluster. Handles server failures, topic-partition migration, and consumer group coordination.

### Constructor

```python
KafkaConsumer(*topics, **configs)
```

Key configuration parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bootstrap_servers` | str or list | `'localhost:9092'` | Broker addresses |
| `client_id` | str | auto-generated | Client identifier |
| `group_id` | str or None | None | Consumer group; None disables group coordination |
| `key_deserializer` | callable | None | Deserializer for keys |
| `value_deserializer` | callable | None | Deserializer for values |
| `auto_offset_reset` | str | `'latest'` | Where to start: `'earliest'`, `'latest'`, `'none'` |
| `enable_auto_commit` | bool | True | Auto-commit offsets |
| `auto_commit_interval_ms` | int | 5000 | Auto-commit interval |
| `consumer_timeout_ms` | int | -1 (infinite) | StopIteration timeout for iterator; -1 = block forever |
| `fetch_min_bytes` | int | 1 | Min bytes for fetch |
| `fetch_max_wait_ms` | int | 500 | Max wait for fetch |
| `fetch_max_bytes` | int | 52428800 | Max bytes per fetch |
| `max_partition_fetch_bytes` | int | 1048576 | Max bytes per partition |
| `request_timeout_ms` | int | 305000 | Request timeout |
| `heartbeat_interval_ms` | int | 3000 | Heartbeat interval |
| `session_timeout_ms` | int | 10000 | Session timeout |
| `max_poll_interval_ms` | int | 300000 | Max poll interval |

### Methods

**`subscribe(topics=(), pattern=None, listener=None)`**
- Subscribe to a list of topics (or a regex pattern). Triggers group rebalance.

**`subscription()`**
- Returns the current set of subscribed topic names.

**`assign(partitions)`**
- Manually assign a list of `TopicPartition` objects. Disables group coordination.

**`assignment()`**
- Returns the set of currently assigned `TopicPartition` objects.

**`poll(timeout_ms=0, max_records=None, update_offsets=True)`**
- Fetch records from assigned partitions. Returns `{TopicPartition: [ConsumerRecord, ...]}`.

**`seek(partition, offset)`**
- Seek to a specific offset on a partition.

**`seek_to_beginning(*partitions)`**
- Seek to the earliest offset on the given partitions.

**`seek_to_end(*partitions)`**
- Seek to the latest offset on the given partitions.

**`position(partition, timeout_ms=None)`**
- Returns the current offset position for the partition.

**`commit(offsets=None, timeout_ms=None)`**
- Synchronous offset commit. If offsets is None, commits current positions.

**`topics()`**
- Returns set of all topic names available from the cluster.

**`partitions_for_topic(topic)`**
- Returns set of partition IDs for a topic.

**`beginning_offsets(partitions)`**
- Returns `{TopicPartition: offset}` for the earliest offsets.

**`end_offsets(partitions)`**
- Returns `{TopicPartition: offset}` for the next-to-be-written offsets.



**`close(autocommit=True, timeout_ms=None)`**
- Close the consumer, optionally committing offsets.

**`metrics(raw=False)`**
- Returns dict of consumer performance metrics.

### Iterator Protocol

KafkaConsumer supports iteration via `__iter__` and `__next__`. When `consumer_timeout_ms` is set, raises `StopIteration` after timeout. Each iteration yields a `ConsumerRecord`.

### ConsumerRecord

Each message consumed is a `ConsumerRecord` with fields:
- `topic` (str)
- `partition` (int)
- `offset` (int)
- `timestamp` (int)
- `timestamp_type` (int)
- `key` (bytes or None)
- `value` (bytes or None)
- `headers` (list of (str, bytes) tuples)
- `checksum` (int or None)
- `serialized_key_size` (int)
- `serialized_value_size` (int)

---

## 3. Record Serialization (`kafka.record`)

### Public package surface (`kafka.record.__init__`)

`kafka.record` exports exactly `MemoryRecords` and `MemoryRecordsBuilder` — the public round-trip surface a user serializes/parses records through. Any per-magic batch/builder classes are internal implementation detail.

**`MemoryRecordsBuilder`** (`kafka.record.memory_records`):
- `__init__(self, magic, compression_type, batch_size, offset=0, transactional=False, producer_id=-1, producer_epoch=-1, base_sequence=-1)`.
- `append(self, timestamp, key, value, headers=[]) -> RecordMetadata or None`: appends one record, auto-assigning the next offset (starting at the constructor `offset`); returns `None` once the builder is full or closed. The returned metadata exposes `offset`.
- `close(self)`: finalizes the batch (idempotent). `buffer(self) -> bytearray`: the serialized bytes (valid after `close()`). `next_offset(self) -> int`, `size_in_bytes(self) -> int`, `is_full(self) -> bool`.

**`MemoryRecords`** (`kafka.record.memory_records`):
- `__init__(self, bytes_data)`: wraps a serialized buffer for reading.
- `has_next(self) -> bool` then `next_batch(self)` returns the next record batch (also iterable directly). Each batch is iterable and yields records exposing `offset`, `timestamp`, `key`, `value`, and `headers`.

Records are serialized in the Apache Kafka on-the-wire record-batch format (magic 2 for the default batch; magics 0/1 for the legacy MessageSet format), with CRC-32 checksums for legacy records and CRC-32C (Castagnoli) checksums for default records. The `crc32c` package is used when available, with a pure-Python fallback otherwise. How the per-magic batch/builder classes and checksum helpers are organized internally is unspecified.

---

## 4. Compression Codecs (`kafka.codec`)

Provides codec availability detection and encode/decode functions used by the record layer and producer compression.

**Availability functions** (each returns `bool`):
- `has_gzip()` — always `True` (uses stdlib `gzip`).
- `has_snappy()` — `True` if `python-snappy` is importable.
- `has_lz4()` — `True` if `lz4` is importable.
- `has_zstd()` — `True` if `zstandard` is importable.

**Encode/decode functions:**
- `gzip_encode(payload: bytes) -> bytes` — compresses with gzip.
- `gzip_decode(payload: bytes) -> bytes` — decompresses gzip data.
- `snappy_encode(payload: bytes) -> bytes` — compresses with Snappy (raises `UnsupportedCodecError` if unavailable).
- `snappy_decode(payload: bytes) -> bytes`
- `lz4_encode(payload: bytes) -> bytes`
- `lz4_decode(payload: bytes) -> bytes`
- `zstd_encode(payload: bytes) -> bytes`
- `zstd_decode(payload: bytes) -> bytes`

---

## 5. Default Partitioner (`kafka.partitioner.default`)

**`DefaultPartitioner`**:
- `__call__(cls, key, all_partitions, available)`: If key is None, random from available. If key is not None, `murmur2(key) & 0x7fffffff % len(all_partitions)`.
- The `__call__` is decorated with `@classmethod`.

**`murmur2(data) -> int`**: Pure-Python MurmurHash2 matching Java Kafka client's `Utils.murmur2()`. Uses seed `0x9747b28c`. Returns an unsigned 32-bit integer (use `& 0xffffffff` to ensure non-negative). Reference values: `murmur2(b"") == 275646681`, `murmur2(b"hello") == 2132663229`, `murmur2(b"kafka") == 3496464228`.

---

## 6. Metrics Framework (`kafka.metrics`)

### MetricName (`kafka.metrics.metric_name`)
- `__init__(self, name, group, description=None, tags=None)`: Raises `ValueError` if name or group is empty.
- `name`, `group`, `description`, `tags` properties.
- Supports equality and hashing based on `name`, `group`, and `tags`.

### MetricConfig (`kafka.metrics.metric_config`)
- `__init__(self, quota=None, samples=2, event_window=sys.maxsize, time_window_ms=30000, tags=None)`.
- `samples` property.

### Quota (`kafka.metrics.quota`)
- Static factories: `Quota.upper_bound(value)`, `Quota.lower_bound(value)`.
- `is_upper_bound()`, `bound`, `is_acceptable(value)`.

### Metrics (`kafka.metrics.metrics`)
- `__init__(self, default_config=None, reporters=None, enable_expiration=False)`.
- `sensor(name, config=None, inactive_sensor_expiration_time_seconds=sys.maxsize, parents=None)`.
- `get_sensor(name)`.
- `remove_sensor(name)`: removes the named sensor (a no-op if no such sensor exists). Removing a sensor also unregisters from the `metrics` registry every `KafkaMetric` that had been added to that sensor — after `remove_sensor`, those `MetricName`s are no longer present in `metrics` and may be re-registered later — and recursively removes that sensor's child sensors.
- `metric_name(name, group, description='', tags=None)`.
- `metrics` property — returns a `dict` mapping `MetricName` → `KafkaMetric`. Each `KafkaMetric` has a `.value(time_ms)` method that returns the current computed value of the stat.
- `config` property, `close()`.

### Sensor
- `add(metric_name, stat)`: Registers a measurable stat under the given metric name. Raises `ValueError` if the metric name is already registered.
- `record(value, time_ms=None)`: Records a value. If this sensor has parents, the value is also recorded on parents.

### Statistical Aggregations (`kafka.metrics.stats`)

| Class | Import |
|-------|--------|
| `Avg` | `kafka.metrics.stats.Avg` |
| `Count` | `kafka.metrics.stats.Count` |
| `Max` | `kafka.metrics.stats.Max` |
| `Min` | `kafka.metrics.stats.Min` |
| `Total` | `kafka.metrics.stats.Total` |

### DictReporter (`kafka.metrics.dict_reporter`)
- `__init__(self, prefix='')`, `snapshot()`.
- `snapshot()` returns a two-level nested `dict`, `{category: {metric_short_name: current_value}}`, where `current_value` is the metric's current computed value (the same value `KafkaMetric.value(...)` returns). The `category` key is the reporter's `prefix` and the metric's `group` (and, if present, its sorted `tags` rendered as `k=v` pairs joined by `,`) joined with `.`, skipping any empty part. An empty prefix is dropped, so the category is just the group.

---

## 7. Future (`kafka.future`)

Thread-safe future/promise implementation.

- `__init__(self)`: `is_done`, `value`, `exception` attributes.
- `succeeded()`, `failed()`, `retriable()`.
- `success(value)`, `failure(e)`. Calling either on an already-completed future raises `AssertionError`.
- `add_callback(f, *args, **kwargs)`, `add_errback(f, *args, **kwargs)`, `add_both(f, *args, **kwargs)`.
- `chain(future)`: forwards THIS future's completion to the supplied downstream `future` — when this future succeeds, the downstream `future` is completed with `future.success(value)` using this future's value; when this future fails, it is completed with `future.failure(exception)` using this future's exception. (Direction is this → argument, so after `f.chain(g); f.success(v)`, `g` is succeeded with value `v`.)

---

## 8. Error Classes (`kafka.errors`)

### Base Errors
- **`KafkaError(RuntimeError)`**: `retriable = False`, `invalid_metadata = False`.
- **`BrokerResponseError(KafkaError)`**: `errno = None`, `message = None`, `description = None`.

### Client-Side Errors
- `KafkaConnectionError(KafkaError)`: `retriable = True`, `invalid_metadata = True`
- `IllegalArgumentError(KafkaError)`, `IllegalStateError(KafkaError)`, `UnsupportedCodecError(KafkaError)`

### Broker Response Errors

| Class | errno | retriable | invalid_metadata |
|-------|-------|-----------|-----------------|
| `NoError` | 0 | False | False |
| `UnknownError` | -1 | False | False |
| `OffsetOutOfRangeError` | 1 | False | False |
| `UnknownTopicOrPartitionError` | 3 | True | True |
| `LeaderNotAvailableError` | 5 | True | True |
| `NotLeaderForPartitionError` | 6 | True | True |
| `RequestTimedOutError` | 7 | True | False |

(Continue through all standard Kafka error codes.)

### Error Lookup
- `for_code(error_code)`: Returns error class. Unknown codes return dynamic `BrokerResponseError` subclass with the given `errno`.

---

## 9. Cluster Metadata (`kafka.cluster`)

**`ClusterMetadata`**: In-memory cache of cluster topology used by clients internally.

```python
class ClusterMetadata:
    def __init__(self, **configs):
```

Constructor accepts optional keyword arguments including `retry_backoff_ms` (int, default 100).

**Methods:**

- `topics() -> set` — Returns the set of known topic names. Empty set if no metadata loaded.
- `brokers() -> set` — Returns the set of known `BrokerMetadata` objects. Empty set initially.
- `partitions_for_topic(topic) -> set or None` — Returns set of partition IDs for the topic, or `None` if topic is unknown.
- `leader_for_partition(topic_partition) -> BrokerMetadata or None` — Returns the leader broker for a `TopicPartition`, or `None` if unknown.
- `coordinator_for_group(group_id) -> BrokerMetadata or None` — Returns the coordinator broker for a consumer group, or `None` if unknown.
- `broker_metadata(node_id) -> BrokerMetadata or None` — Returns `BrokerMetadata` for the given node ID, or `None` if unknown.
- `add_listener(listener)` — Register a callable to be invoked on each metadata update. The callable is invoked with the updated `ClusterMetadata` instance as its sole positional argument.
- `remove_listener(listener)` — Unregister a previously added listener.
- `refresh_backoff() -> int` — Returns the configured `retry_backoff_ms` value.
- `ttl() -> int` — Milliseconds until metadata should be refreshed. Returns `0` when an update is currently needed (e.g. a freshly constructed cache, or after `request_update()`); otherwise it is bounded by `metadata_max_age_ms` since the last successful refresh and `retry_backoff_ms` since the last attempt.
- `request_update() -> Future` — Flags the metadata as needing a refresh (so `ttl()` becomes `0`) and returns a `kafka.future.Future` whose value will be this `ClusterMetadata` once an update is applied. It does not perform the update itself.
- `update_metadata(metadata_response) -> None` — Apply a `MetadataResponse` to the cache and then notify every registered listener. A response whose broker list is empty is ignored (no listeners fire). `metadata_response` is a `kafka.protocol.metadata.MetadataResponse` struct (see below).

`MetadataResponse` is a versioned protocol Struct in `kafka.protocol.metadata`, indexed by version: `MetadataResponse[0]` is the v0 class. Its v0 constructor takes positional args `(brokers, topics)` where `brokers` is a list of `(node_id, host, port)` tuples and `topics` is a list of topic entries — e.g. `MetadataResponse[0]([(0, "host", 9092)], [])`.

---

## 10. Named Tuple Structs (`kafka.structs`)

- `TopicPartition = namedtuple("TopicPartition", ["topic", "partition"])`
- `BrokerMetadata = namedtuple("BrokerMetadata", ["nodeId", "host", "port", "rack"])`
- `OffsetAndMetadata = namedtuple("OffsetAndMetadata", ["offset", "metadata", "leader_epoch"])`

---

## 11. Partition Assignors (`kafka.coordinator.assignors`)

### Consumer Protocol (`kafka.coordinator.protocol`)

The consumer protocol uses Kafka's wire protocol Struct system internally. Protocol messages are defined as Struct subclasses with a SCHEMA attribute.

- `ConsumerProtocolMemberMetadata_v0(Struct)`: SCHEMA fields: `(version: Int16, topics: Array(String), user_data: Bytes)`. Constructor takes positional args `(version, topics, user_data)`.
- `ConsumerProtocolMemberAssignment_v0(Struct)`: SCHEMA with `partitions()` method that flattens `[(topic, [partitions])]` into a list of `TopicPartition` objects. Constructor takes `(version, assignment, user_data)` where `assignment` is `[(topic_name, [partition_ids])]`.

These Struct subclasses support:
- `encode() -> bytes`: Serializes the struct to bytes.
- `decode(cls, data) -> Struct`: Class method to deserialize from bytes.

### Subscription (`kafka.coordinator.subscription`)
- `Subscription(metadata, group_instance_id)`: Properties: `version`, `user_data`, `topics`, `group_instance_id`.

### RangePartitionAssignor (`kafka.coordinator.assignors.range`)
- `name = 'range'`
- `assign(cls, cluster, group_subscriptions)`: For each topic, divides partitions evenly among subscribed consumers. `group_subscriptions` is `{member_id: Subscription}`. The assignor retrieves each member's subscribed topics via `subscription.topics` (a list of topic strings) and partition counts via `cluster.partitions_for_topic(topic)`. Returns `{member_id: ConsumerProtocolMemberAssignment_v0}`.
- `metadata(topics)`: Returns `ConsumerProtocolMemberMetadata_v0` instance.

### RoundRobinPartitionAssignor (`kafka.coordinator.assignors.roundrobin`)
- `name = 'roundrobin'`
- `assign(cls, cluster, group_subscriptions)`: Round-robin distribution of partitions. Same input/output contract as `RangePartitionAssignor.assign`.


## 12. Security/Authentication: SASL (`kafka.sasl`)

The SASL module provides pluggable authentication mechanisms. Each mechanism implements a common abstract interface and is registered by name in a global registry.

### Package Structure

```
kafka/sasl/
├── __init__.py   # Registry: SASL_MECHANISMS dict, register/get functions
├── abc.py        # SaslMechanism abstract base class
├── plain.py      # PLAIN mechanism (RFC 4616)
├── scram.py      # SCRAM-SHA-256/512 mechanism (RFC 5802) + ScramClient helper
├── gssapi.py     # GSSAPI/Kerberos for non-Windows (RFC 2222 §7.2.1)
├── sspi.py       # GSSAPI/Kerberos for Windows via SSPI (RFC 4752 §3)
├── oauth.py      # OAUTHBEARER mechanism + AbstractTokenProvider
└── msk.py        # AWS MSK IAM mechanism (AWS Signature V4)
```

### 12.1 Mechanism Registry (`kafka.sasl.__init__`)

```python
SASL_MECHANISMS = {}

def register_sasl_mechanism(name, klass, overwrite=False):
    """Register a SASL mechanism class under a string name.
    Raises ValueError (message containing 'already defined') if name exists and overwrite=False."""

def get_sasl_mechanism(name):
    """Lookup mechanism class by name. Raises KeyError if not found."""
```

Default registrations at module load:

| Name | Class | Notes |
|---|---|---|
| `'PLAIN'` | `SaslMechanismPlain` | |
| `'SCRAM-SHA-256'` | `SaslMechanismScram` | Hash selected at runtime |
| `'SCRAM-SHA-512'` | `SaslMechanismScram` | Hash selected at runtime |
| `'GSSAPI'` | `SaslMechanismGSSAPI` | Non-Windows |
| `'GSSAPI'` | `SaslMechanismSSPI` | Windows (`platform.system() == 'Windows'`) |
| `'OAUTHBEARER'` | `SaslMechanismOAuth` | |
| `'AWS_MSK_IAM'` | `SaslMechanismAwsMskIam` | |

Users can replace built-in mechanisms with custom implementations via `register_sasl_mechanism(name, klass, overwrite=True)`.

### 12.2 Abstract Base Class (`kafka.sasl.abc`)

```python
class SaslMechanism(metaclass=abc.ABCMeta):
```

All mechanisms implement this interface. The handshake protocol is driven by the connection layer:

```
1. mechanism = MechanismClass(**config)
2. Loop:
   a. outgoing = mechanism.auth_bytes()     # get bytes to send to broker
   b. Send outgoing to broker
   c. incoming = receive from broker
   d. mechanism.receive(incoming)            # process broker response
   e. If mechanism.is_done(): break
3. Check mechanism.is_authenticated()
4. Optionally call mechanism.auth_details() for logging
```

**Abstract methods (must be implemented by every mechanism):**

- `__init__(self, **config)` -- Receives all SASL-related config as keyword arguments.
- `auth_bytes(self)` -- Returns the next `bytes` to send to the broker.
- `receive(self, auth_bytes)` -- Processes `bytes` received from the broker. Advances internal state.
- `is_done(self)` -- Returns `bool`: whether the handshake is complete.
- `is_authenticated(self)` -- Returns `bool`: whether authentication succeeded.

**Concrete method:**

- `auth_details(self)` -- Returns a string describing the authentication (e.g., `'Authenticated via SASL'`). Subclasses override with mechanism-specific details.

### 12.3 PLAIN Mechanism (`kafka.sasl.plain`)

```python
class SaslMechanismPlain(SaslMechanism):
```

RFC 4616. Single round-trip, simple username/password.

**`__init__(self, **config)`:**
- Logs a warning if `security_protocol` is `SASL_PLAINTEXT` (credentials sent in the clear).
- Requires `sasl_plain_username` and `sasl_plain_password` in config. Raises `AssertionError` if either is missing.

**`auth_bytes(self)`:**
- Returns `b'{username}\x00{username}\x00{password}'` (three NUL-separated fields: authzid, authcid, password). Username appears twice per RFC 4616 convention. Splitting the result on `b'\x00'` yields exactly three parts.

**`receive(self, auth_bytes)`:**
- Sets done. Authenticated if broker response is empty bytes (`b''`).

**`auth_details(self)`:** Returns `'Authenticated as {username} via SASL / Plain'`.

**Round-trips:** 1.

### 12.4 SCRAM Mechanism (`kafka.sasl.scram`)

```python
class SaslMechanismScram(SaslMechanism):
```

RFC 5802. Two round-trips, salted challenge-response.

**`__init__(self, **config)`:**
- Requires `sasl_plain_username`, `sasl_plain_password`.
- Requires `sasl_mechanism` to be `'SCRAM-SHA-256'` or `'SCRAM-SHA-512'`.
- Warns if using `SASL_PLAINTEXT`.
- Creates an internal `ScramClient` helper with username, password, and mechanism.
- Initializes `_state = 0` (state machine: 0 → 1 → 2).

**`auth_bytes(self)`:** State 0: `ScramClient.first_message()`. State 1: `ScramClient.final_message()`.

**`receive(self, auth_bytes)`:** State 0: `ScramClient.process_server_first_message()`. State 1: `ScramClient.process_server_final_message()`. Increments `_state`.

**`is_done()` / `is_authenticated()`:** Both return `self._state == 2`.

#### ScramClient helper

```python
class ScramClient:
    MECHANISMS = {
        'SCRAM-SHA-256': hashlib.sha256,
        'SCRAM-SHA-512': hashlib.sha512,
    }

    def __init__(self, user, password, mechanism):
```

Generates a random nonce via `uuid.uuid4()` (hyphens stripped). The hash function is selected at runtime from `MECHANISMS` based on the mechanism name.

**Methods:**
- `first_message(self)` -- Returns `b'n,,' + client_first_bare` where `client_first_bare = 'n={user},r={nonce}'`.
- `process_server_first_message(self, server_first_message)` -- Parses `r`, `s` (salt, base64), `i` (iterations). Validates server nonce starts with client nonce (raises `ValueError` on mismatch). Computes salted password via `hashlib.pbkdf2_hmac`. Derives `client_key`, `stored_key`, `client_signature`, `client_proof`, `server_key`, `server_signature` per RFC 5802.
- `final_message(self)` -- Returns `'c=biws,r={nonce},p={base64(client_proof)}'`.
- `process_server_final_message(self, server_final_message)` -- Parses `v` (verifier). Validates server signature matches. Raises `ValueError` on mismatch.

**Round-trips:** 2.

### 12.5 GSSAPI/Kerberos Mechanism (`kafka.sasl.gssapi`)

```python
class SaslMechanismGSSAPI(SaslMechanism):
```

RFC 2222 §7.2.1. Implements the standard SASL GSSAPI/Kerberos handshake via the `gssapi` library (an optional dependency). It follows the abstract `SaslMechanism` interface (`__init__(**config)` / `auth_bytes` / `receive` / `is_done` / `is_authenticated`); the Kerberos token exchange and SASL QoP negotiation follow the published GSSAPI standard.

**Round-trips:** Variable (typically 2-3 for Kerberos + 1 for QoP).

### 12.6 SSPI Mechanism (`kafka.sasl.sspi`)

```python
class SaslMechanismSSPI(SaslMechanism):
```

RFC 4752 §3. Windows-only SSPI-based Kerberos, functionally equivalent to GSSAPI. Implemented via the Windows-only `sspi`/`pywintypes`/`sspicon`/`win32security` optional dependencies and following the same abstract `SaslMechanism` interface as GSSAPI.

**Round-trips:** Variable (same as GSSAPI).

### 12.7 OAUTHBEARER Mechanism (`kafka.sasl.oauth`)

```python
class SaslMechanismOAuth(SaslMechanism):
```

SASL OAUTHBEARER. Bearer token authentication.

**`__init__(self, **config)`:**
- Requires `sasl_oauth_token_provider` to be present and an instance of `AbstractTokenProvider`. Raises `AssertionError` if missing or wrong type.

**`auth_bytes(self)`:**
- If `_error` is set (from prior failed receive), returns `b'\x01'` (failure acknowledgment).
- Otherwise: gets token from provider, formats extensions, constructs: `b'n,,\x01auth=Bearer {token}{extensions}\x01\x01'`.

**`receive(self, auth_bytes)`:**
- If `auth_bytes` is not empty: error -- stores `_error = b'\x01'` for acknowledgment on next `auth_bytes` call.
- If empty: success -- sets done and authenticated.

**Round-trips:** 1 on success, 2 on failure (error + acknowledgment).

#### AbstractTokenProvider

```python
class AbstractTokenProvider(metaclass=abc.ABCMeta):
    def __init__(self, **config):
        pass

    @abc.abstractmethod
    def token(self):
        """Return a str ID/access token. Must handle reuse and periodic refresh."""

    def extensions(self):
        """Return a dict of str key-value extension pairs. Default: {}."""
        return {}
```

### 12.8 AWS MSK IAM Mechanism (`kafka.sasl.msk`)

```python
class SaslMechanismAwsMskIam(SaslMechanism):
```

AWS Signature V4 pre-signed URL approach for Amazon Managed Streaming for Apache Kafka. Implemented via the optional `botocore` dependency and following the abstract `SaslMechanism` interface. Requires `security_protocol` to be `SASL_SSL`. On success the broker responds with non-empty auth details (opposite of PLAIN), which marks the mechanism authenticated. The auth payload construction follows the published AWS Signature Version 4 signing standard for the `kafka-cluster` service.

**Round-trips:** 1.

---

## 13. Admin API (`kafka.admin`)

The admin API provides programmatic access to Kafka cluster administration. A single `KafkaAdminClient` object exposes all of the admin operations documented in sections 13.3-13.8 (ACL, cluster, config, group, partition, topic, and user administration) plus construction, connection, and request routing. The internal code organization is an implementation detail. The package is importable as `kafka.admin`, and its public names are exported from `kafka.admin` (see the export list below).

Public exports:
```python
__all__ = [
    'KafkaAdminClient',
    'ACL', 'ACLFilter', 'ACLOperation', 'ACLPermissionType', 'ACLResourcePatternType',
    'ResourceType', 'ResourcePattern', 'ResourcePatternFilter',
    'AlterConfigOp', 'ConfigResource', 'ConfigResourceType', 'ConfigType', 'ConfigSourceType',
    'UpdateFeatureType',
    'GroupState', 'GroupType', 'MemberToRemove',
    'NewTopic', 'NewPartitions',
    'OffsetSpec', 'OffsetTimestamp',
    'ScramMechanism', 'UserScramCredentialDeletion', 'UserScramCredentialUpsertion',
]
```

**`NewTopic`**: Data class for topic creation requests.
- `__init__(self, name, num_partitions, replication_factor, **kwargs)`.
- Properties: `name` (str), `num_partitions` (int), `replication_factor` (int).

**`NewPartitions`**: Data class for increasing the partition count of an existing topic.
- `__init__(self, total_count, new_assignments=None)`.
- Properties: `total_count` (int), `new_assignments` (list of replica-id lists, or `None`).

### 13.1 KafkaAdminClient

```python
class KafkaAdminClient:
    def __init__(self, **configs):
```

#### Constructor

Validates that all `configs` keys are recognized (raising `KafkaConfigurationError` for unknown keys), merges them over the defaults below, connects to the cluster, and leaves the client ready to issue admin requests. Constructor arguments are the configuration parameters listed below.

#### Configuration

| Parameter | Type | Default | Description |
|---|---|---|---|
| `bootstrap_servers` | str or list | `'localhost'` | Initial broker(s) |
| `client_id` | str | `'kafka-python-{version}'` | Client identifier |
| `request_timeout_ms` | int | `30000` | Default request timeout |
| `connections_max_idle_ms` | int | `540000` | Close idle connections after this |
| `reconnect_backoff_ms` | int | `50` | Initial reconnect backoff |
| `reconnect_backoff_max_ms` | int | `30000` | Max reconnect backoff |
| `max_in_flight_requests_per_connection` | int | `5` | Max pipelined requests |
| `receive_buffer_bytes` | int | None | TCP receive buffer size |
| `send_buffer_bytes` | int | None | TCP send buffer size |
| `socket_options` | list | `[(IPPROTO_TCP, TCP_NODELAY, 1)]` | Socket options |
| `retry_backoff_ms` | int | `100` | Backoff on retryable errors |
| `metadata_max_age_ms` | int | `300000` | Force metadata refresh interval |
| `security_protocol` | str | `'PLAINTEXT'` | PLAINTEXT, SSL, SASL_PLAINTEXT, SASL_SSL |
| `ssl_context` | SSLContext | None | Pre-configured SSLContext |
| `ssl_check_hostname` | bool | True | Verify cert hostname |
| `ssl_cafile` | str | None | CA file |
| `ssl_certfile` | str | None | Client cert |
| `ssl_keyfile` | str | None | Client key |
| `ssl_password` | str | None | Key password |
| `ssl_crlfile` | str | None | CRL file |
| `api_version` | tuple | None | Explicit version or None for auto-detect |
| `bootstrap_timeout_ms` | int | `2000` | Constructor bootstrap timeout |
| `selector` | class | `selectors.DefaultSelector` | I/O selector |
| `sasl_mechanism` | str | None | SASL mechanism name |
| `sasl_plain_username` | str | None | Username |
| `sasl_plain_password` | str | None | Password |
| `sasl_kerberos_name` | object | None | GSSAPI name |
| `sasl_kerberos_service_name` | str | `'kafka'` | GSSAPI service |
| `sasl_kerberos_domain_name` | str | None | GSSAPI domain |
| `sasl_oauth_token_provider` | object | None | OAuthBearer provider |
| `proxy_url` | str | None | Proxy URL |
| `metric_reporters` | list | `[]` | Metric reporter classes |
| `metrics_num_samples` | int | `2` | Metric samples |
| `metrics_sample_window_ms` | int | `30000` | Metric window |

#### Core Methods

```python
def __enter__(self) -> self
def __exit__(self, exc_type, exc_val, exc_tb)
```
Context manager support.

```python
def close(self) -> None
```
Closes the client and releases its resources. Idempotent.

### 13.2 Data Types and Enums

#### ACL Types (`kafka.admin._acls`)

```python
class ResourceType(IntEnum):
    UNKNOWN = 0; ANY = 1; TOPIC = 2; GROUP = 3; CLUSTER = 4
    TRANSACTIONAL_ID = 5; DELEGATION_TOKEN = 6; USER = 7

class ACLOperation(IntEnum):
    UNKNOWN = 0; ANY = 1; ALL = 2; READ = 3; WRITE = 4; CREATE = 5
    DELETE = 6; ALTER = 7; DESCRIBE = 8; CLUSTER_ACTION = 9
    DESCRIBE_CONFIGS = 10; ALTER_CONFIGS = 11; IDEMPOTENT_WRITE = 12
    CREATE_TOKENS = 13; DESCRIBE_TOKENS = 14

class ACLPermissionType(IntEnum):
    UNKNOWN = 0; ANY = 1; DENY = 2; ALLOW = 3

class ACLResourcePatternType(IntEnum):
    UNKNOWN = 0; ANY = 1; MATCH = 2; LITERAL = 3; PREFIXED = 4
```

**`ResourcePattern`**: Represents a Kafka resource. Fields: `resource_type` (ResourceType), `resource_name` (str), `pattern_type` (ACLResourcePatternType).

**`ResourcePatternFilter`**: Filter version of ResourcePattern with same fields, used for describe/delete queries.

**`ACL`**: A complete ACL binding. Fields: `resource_pattern` (ResourcePattern), `principal` (str), `host` (str), `operation` (ACLOperation), `permission_type` (ACLPermissionType). The concrete `ACL` constructor validates its arguments and raises `kafka.errors.IllegalArgumentError` when `operation` is the filter-only `ACLOperation.ANY`, when `permission_type` is the filter-only `ACLPermissionType.ANY`, or when `resource_pattern` is a `ResourcePatternFilter` rather than a concrete `ResourcePattern` — these filter-only sentinels are valid only for `ACLFilter`, not for a complete binding. `ACL` (and `ResourcePattern`) support value-based equality and hashing over their fields (two bindings with equal fields are `==` and hash-equal; changing any one field makes them unequal).

**`ACLFilter`**: Filter for ACL queries. Fields: `resource_pattern` (ResourcePatternFilter), `principal` (str or None), `host` (str or None), `operation` (ACLOperation), `permission_type` (ACLPermissionType).

#### Config Types (`kafka.admin._configs`)

```python
class ConfigResourceType(IntEnum):
    UNKNOWN = 0; TOPIC = 2; BROKER = 4; BROKER_LOGGER = 8
    CLIENT_METRICS = 16; GROUP = 32

class AlterConfigOp(IntEnum):
    SET = 0; DELETE = 1; APPEND = 2; SUBTRACT = 3

class ConfigFilterType(IntEnum):
    ALL = 0; DYNAMIC = 1; MODIFIED = 2; DEFAULT = 3; STATIC = 4

class ConfigType(IntEnum):
    UNKNOWN = 0; BOOLEAN = 1; STRING = 2; INT = 3; SHORT = 4
    LONG = 5; DOUBLE = 6; LIST = 7; CLASS = 8; PASSWORD = 9

class ConfigSourceType(IntEnum):
    UNKNOWN = 0; DYNAMIC_TOPIC_CONFIG = 1; DYNAMIC_BROKER_CONFIG = 2
    DYNAMIC_DEFAULT_BROKER_CONFIG = 3; STATIC_BROKER_CONFIG = 4
    DEFAULT_CONFIG = 5; DYNAMIC_BROKER_LOGGER_CONFIG = 6
    DYNAMIC_CLIENT_METRICS_CONFIG = 7; DYNAMIC_GROUP_CONFIG = 8
```

**`ConfigResource`**: Identifies a config target.
- `__init__(self, resource_type, name, configs=None)`.
- Properties: `resource_type` (ConfigResourceType), `name` (str), `configs` (dict, optional -- for alter operations).

#### Group Types (`kafka.admin._groups`)

```python
class GroupState(str, Enum):
    UNKNOWN = 'Unknown'; PREPARING_REBALANCE = 'PreparingRebalance'
    COMPLETING_REBALANCE = 'CompletingRebalance'; STABLE = 'Stable'
    DEAD = 'Dead'; EMPTY = 'Empty'; ASSIGNING = 'Assigning'
    RECONCILING = 'Reconciling'

class GroupType(str, Enum):
    UNKNOWN = 'Unknown'; CLASSIC = 'classic'; CONSUMER = 'consumer'; SHARE = 'share'
```

**`MemberToRemove`**: Identifies a group member to remove. Fields: `member_id` (str, optional), `group_instance_id` (str, optional), `reason` (str, optional).

#### Cluster Types (`kafka.admin._cluster`)

```python
class UpdateFeatureType(IntEnum):
    UNKNOWN = 0; UPGRADE = 1; SAFE_DOWNGRADE = 2; UNSAFE_DOWNGRADE = 3
```

#### User Types (`kafka.admin._users`)

```python
class ScramMechanism(IntEnum):
    UNKNOWN = 0; SCRAM_SHA_256 = 1; SCRAM_SHA_512 = 2
```

**`UserScramCredentialDeletion`**: Fields: `user` (str), `mechanism` (ScramMechanism).

**`UserScramCredentialUpsertion`**: Fields: `user` (str), `mechanism` (ScramMechanism), `password` (str), `iterations` (int, optional).

#### Partition Types (`kafka.admin._partitions`)

**`OffsetSpec`** (IntEnum, in `kafka.protocol.consumer.offsets`):
```python
class OffsetSpec(IntEnum):
    LATEST = -1; EARLIEST = -2; MAX_TIMESTAMP = -3
    EARLIEST_LOCAL = -4; LATEST_TIERED = -5
```

**`OffsetTimestamp`**: Subclass of `int`. Represents a milliseconds-since-epoch timestamp for offset lookup.

### 13.3 ACLAdminMixin (`kafka.admin._acls`)

```python
def describe_acls(self, acl_filter) -> tuple[list[ACL], KafkaError]
```
Sends `DescribeAclsRequest` to any broker. Returns `(list_of_ACLs, error)`.

```python
def create_acls(self, acls) -> dict
```
Accepts a list of `ACL` objects. Returns `{'succeeded': [ACL, ...], 'failed': [KafkaError, ...]}`.

```python
def delete_acls(self, acl_filters) -> list[tuple]
```
Accepts a list of `ACLFilter` objects. Returns list of `(ACLFilter, [matched_ACLs], KafkaError)` tuples.

### 13.4 ClusterAdminMixin (`kafka.admin._cluster`)

```python
def describe_cluster(self) -> dict
```
Returns a cluster metadata dict: `{'brokers': [...], 'controller_id': int, 'cluster_id': str, 'authorized_operations': ...}`. Each entry in `brokers` is a dict using the key **`node_id`** (int) plus `host` (str), `port` (int), and `rack` (str or None) — e.g. `{'node_id': 1, 'host': 'localhost', 'port': 9092, 'rack': None}`.

```python
def describe_log_dirs(self, topic_partitions=None, brokers=None) -> list[dict]
```
Sends `DescribeLogDirsRequest` to each broker. `topic_partitions` can be `{topic: [partition_ids]}`, list of topic names, or None. Returns `[{"broker": node_id, "log_dirs": [...]}]`.

```python
def alter_replica_log_dirs(self, replica_assignments) -> dict
```
Moves replicas between log directories. `replica_assignments` maps `TopicPartitionReplica` (or tuple `(topic, partition, broker_id)`) to a destination log dir path. Returns `{TopicPartitionReplica: error_class}`.

```python
def describe_metadata_quorum(self) -> dict
```
Describes KRaft quorum state. Returns dict with leader, voters, observers.

```python
def get_broker_version_data(self, broker_id) -> BrokerVersionData
```
Returns version data for a specific broker.

```python
def api_versions(self) -> dict
```
Returns `{ApiKey: version_range}` from cached broker version data.

```python
def describe_features(self, send_request_to_controller=False) -> dict
```
Returns `{feature_name: {'supported': (min, max), 'finalized': (min, max), 'finalized_epoch': int|None}}`.

```python
def update_features(self, feature_updates, validate_only=False, timeout_ms=60000) -> dict
```
Finalizes cluster-wide feature flags. Routed to controller. Returns `{feature_name: 'OK' | error_message}`.

### 13.5 ConfigAdminMixin (`kafka.admin._configs`)

```python
def describe_configs(self, config_resources, include_synonyms=False) -> list
```
Fetches config parameters. `config_resources` is a list of `ConfigResource`. Broker-type resources route to their specific broker; others go to any broker. Returns the raw broker responses: a `list` of `DescribeConfigsResponse` protocol Structs (one per request that was sent). Each response exposes a `resources` array, and each entry in `resources` is a positional tuple `(error_code, error_message, resource_type, resource_name, config_entries)` — so `config_entries` (itself a list of per-key entry tuples) is the last element. A broker that has configuration returns at least one resource carrying a non-empty `config_entries`.

```python
def alter_configs(self, config_resources, validate_only=False, raise_on_unknown=True, incremental=None) -> dict
```
Alters config parameters. Each `ConfigResource.configs` is `{key: (op, value)}` or `{key: value}` (implicit SET). Auto-detects incremental support (broker >= 2.3). Returns `{resource_type: {resource_name: 'OK' | error}}`.

```python
def reset_configs(self, config_resources, validate_only=False, raise_on_unknown=True, incremental=None) -> dict
```
Resets configs to defaults. Returns same shape as `alter_configs`.

```python
def list_config_resources(self, resource_types=None) -> dict
```
Lists config resources. Returns `{resource_type: [resource_name, ...]}`.

### 13.6 GroupAdminMixin (`kafka.admin._groups`)

```python
def describe_groups(self, group_ids, group_coordinator_id=None, include_authorized_operations=False) -> dict
```
Describes consumer groups. Routes to each group's coordinator. Returns one description per requested group; each description identifies the group it describes (its group id) alongside the group's state and members. Also available as `describe_consumer_groups()`.

```python
def list_groups(self, broker_ids=None, states_filter=None, types_filter=None) -> list[tuple]
```
Lists all consumer groups across all (or specified) brokers. Returns a list of **tuples** (not dicts) whose first element is the group id — e.g. `(group_id, protocol_type)` — matching the consumer-group listing wire response. Also available as `list_consumer_groups()`.

```python
def list_group_offsets(self, group_id, group_coordinator_id=None, partitions=None) -> dict
```
Fetches committed offsets for a group. Returns `{TopicPartition: OffsetAndMetadata}`.

```python
def delete_groups(self, group_ids, group_coordinator_id=None) -> dict
```
Deletes consumer groups. Returns `{group_id: 'OK' | error_name}`.

```python
def alter_group_offsets(self, group_id, offsets, group_coordinator_id=None) -> dict
```
Alters committed offsets (group must be empty/dead). `offsets` maps `TopicPartition` to `OffsetAndMetadata`. Returns `{TopicPartition: KafkaError_class}`.

```python
def reset_group_offsets(self, group_id, offset_specs, group_coordinator_id=None) -> dict
```
Resets committed offsets. Each value can be `OffsetSpec` (EARLIEST/LATEST/MAX_TIMESTAMP), `OffsetTimestamp` (ms since epoch), or a plain `int`. Returns `{TopicPartition: {'error': KafkaError, 'offset': int}}`.

```python
def delete_group_offsets(self, group_id, partitions, group_coordinator_id=None) -> dict
```
Deletes committed offsets. Returns `{TopicPartition: KafkaError_class}`.

```python
def remove_group_members(self, group_id, members, group_coordinator_id=None) -> dict
```
Removes members from a group. `members` is a list of `MemberToRemove`. Returns `{member_id_or_instance_id: KafkaError_class}`.

### 13.7 PartitionAdminMixin (`kafka.admin._partitions`)

```python
def create_partitions(self, topic_partitions, timeout_ms=None, validate_only=False, raise_errors=True) -> response
```
Creates additional partitions. `topic_partitions` maps each topic name to a `NewPartitions` instance, from which the new total partition count is read via `.total_count` and the optional replica assignments via `.new_assignments`. Sent to controller.

```python
def delete_records(self, records_to_delete, timeout_ms=None, partition_leader_id=None) -> dict
```
Deletes records below given offset. `records_to_delete` maps `TopicPartition` to offset (int). Retries on `NotLeaderForPartitionError`. Returns `{TopicPartition: metadata_dict}`.

```python
def elect_leaders(self, election_type, topic_partitions=None, timeout_ms=None, raise_errors=True) -> response
```
Triggers leader election. `election_type`: 0=Preferred, 1=Unclean. Ignores `ElectionNotNeededError`.

```python
def alter_partition_reassignments(self, reassignments, timeout_ms=None, raise_errors=True) -> dict
```
Alters replica sets. `reassignments` maps `TopicPartition` to list of broker IDs (or None to cancel). Sent to controller.

```python
def list_partition_reassignments(self, topic_partitions=None, timeout_ms=None) -> dict
```
Lists ongoing reassignments. Returns `{TopicPartition: {'replicas': [...], 'adding_replicas': [...], 'removing_replicas': [...]}}`.

```python
def describe_topic_partitions(self, topics, response_partition_limit=2000, cursor=None) -> dict
```
KIP-966, broker 3.7+. Pagination support. Returns `{'topics': [...], 'next_cursor': None | {'topic_name': str, 'partition_index': int}}`.

```python
def list_partition_offsets(self, topic_partition_specs, isolation_level='read_uncommitted', timeout_ms=None) -> dict
```
Looks up offsets via `ListOffsetsRequest`. Routes to partition leaders. Returns `{TopicPartition: OffsetAndTimestamp}`.

### 13.8 TopicAdminMixin (`kafka.admin._topics`)

```python
def list_topics(self) -> list[str]
```
Returns all topic names.

```python
def describe_topics(self, topics=None) -> list[dict]
```
Fetches metadata for topics (or all topics when `topics` is `None`). Returns one dict per topic. Each dict carries the topic name under the key `'topic'` and its partition list under the key `'partitions'` — e.g. `{'topic': str, 'partitions': [ {partition metadata...} ], ...}`. The partition list has one entry per partition, so its length equals the topic's partition count.

```python
def create_topics(self, new_topics, timeout_ms=None, validate_only=False, raise_errors=True, wait_for_metadata=False) -> dict
```
Creates topics. `new_topics` can be a list of topic name strings or a dict of `{topic_name: {num_partitions, replication_factor, assignments, configs}}`. `wait_for_metadata` blocks until topics appear with leaders. Sent to controller.

```python
def wait_for_topics(self, topic_names, timeout_ms=10000) -> None
```
Polls until every topic has `error_code == 0` and all partitions have leaders. Raises `KafkaTimeoutError`.

```python
def delete_topics(self, topics, timeout_ms=None, raise_errors=True) -> dict
```
Deletes topics by name (str) or UUID.


---


## 14. Command-Line Tools (`kafka.cli`)

Console tools for quick consuming, producing, and admin operations. Each is invoked via `python -m`.

### Entry Points

Each tool is invoked as a `python -m` module:

| Command | Behavior |
|---|---|
| `python -m kafka` | Prints available interfaces and exits with code 1 |
| `python -m kafka.consumer` | Runs the consumer CLI (see 14.2) |
| `python -m kafka.producer` | Runs the producer CLI (see 14.3) |
| `python -m kafka.admin` | Runs the admin CLI (see 14.4) |

Each tool returns an exit code (0 on success, non-zero on error).

### 14.1 Shared Common Arguments

Every CLI accepts a shared set of connection and logging arguments.

**Connection arguments:**

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `-b` / `--bootstrap-servers` | str (append) | -- | configurable | `host:port` for cluster bootstrap |
| `-S` / `--security-protocol` | str | `'PLAINTEXT'` | No | PLAINTEXT, SSL, SASL_PLAINTEXT, SASL_SSL |
| `-M` / `--sasl-mechanism` | str | `'PLAIN'` | No | SASL mechanism name |
| `-U` / `--sasl-user` | str | None | No | SASL username |
| `-P` / `--sasl-password` | str | None | No | SASL password |

**Logging arguments:**

| Flag | Type | Default | Description |
|---|---|---|---|
| `-l` / `--log-level` | str | `'CRITICAL'` | NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `-L` / `--enable-logger` | str (append) | None | Enable specific loggers |
| `-D` / `--disable-logger` | str (append) | None | Disable specific loggers |
| `-c` / `--extra-config` | str (append) | None | Additional config in `key=val` format |

The connection flags are converted into the corresponding client constructor keyword arguments (`bootstrap_servers`, `security_protocol`, `sasl_mechanism`, `sasl_plain_username`, `sasl_plain_password`). Each `-c key=val` entry is passed as an additional client config keyword, with the value auto-converted to an integer, boolean (`True`/`False`), or `None` where applicable.

### 14.2 Consumer CLI (`kafka.cli.consumer`)

**Program:** `python -m kafka.consumer`

**Arguments** (beyond common):

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `-t` / `--topic` | str (append) | -- | Yes | Topic to subscribe to (repeatable) |
| `-g` / `--group` | str | -- | Yes | Consumer group ID |
| `-i` / `--group-instance-id` | str | None | No | Static group membership ID |
| `-f` / `--format` | str | `'str'` | No | Output: `str`, `raw`, or `full` |
| `--encoding` | str | `'utf-8'` | No | Encoding for str output |

**Behavior:**
1. Creates `KafkaConsumer(group_id=..., group_instance_id=..., **connect_kwargs)`.
2. Calls `consumer.subscribe(topics)`.
3. Iterates `for m in consumer:`, printing each message per format:
   - `str`: `m.value.decode(encoding)`
   - `full`: `repr(m)` (full ConsumerRecord)
   - `raw`: `m.value` (raw bytes)
4. Catches `KeyboardInterrupt` for clean exit. Always calls `consumer.close()` in `finally`.

### 14.3 Producer CLI (`kafka.cli.producer`)

**Program:** `python -m kafka.producer`

**Arguments** (beyond common):

| Flag | Type | Default | Required | Description |
|---|---|---|---|---|
| `-t` / `--topic` | str | -- | Yes | Topic to publish to |
| `--encoding` | str | `'utf-8'` | No | Byte encoding for messages |

**Behavior:**
1. Creates `KafkaProducer(**connect_kwargs)`.
2. Reads lines from stdin via `input()`. On `EOFError`, falls back to `sys.stdin.read().rstrip('\n')` and exits if empty.
3. Each line: `producer.send(topic, value=line.encode(encoding)).add_both(log_result)`.
4. `log_result` callback logs success at INFO or errors at ERROR.
5. Catches `KeyboardInterrupt`. Always calls `producer.close()` in `finally`.

### 14.4 Admin CLI (`kafka.cli.admin`)

**Program:** `python -m kafka.admin`

Uses a two-level subcommand pattern: `python -m kafka.admin GROUP COMMAND [options]`

**Top-level arguments** (beyond common):

| Flag | Type | Default | Description |
|---|---|---|---|
| `--format` | str | `'raw'` | Output: `raw` (pprint) or `json` |

Note: `--bootstrap-servers` is not argparse-required for admin, but a `ValueError` is raised at runtime if it is missing.

**Behavior:**
1. Parses args for GROUP and COMMAND. No GROUP → prints help, exits 1. No COMMAND → prints group help, exits 1.
2. Creates `KafkaAdminClient(**connect_kwargs)`.
3. Invokes the selected group/command against the client, passing the parsed arguments.
4. Formats result as `pprint` (raw) or `json.dumps` (json).
5. Handles `BrokerResponseError`, `ValueError`, `AttributeError`, and generic exceptions.
6. Always calls `client.close()` in `finally`.

#### ACLs Group (`python -m kafka.admin acls`)

| Command | Method | Key Arguments |
|---|---|---|
| `describe` | `describe_acls(filter)` | `--principal`, `--host`, `--operation`, `--permission-type`, `--resource-type`, `--resource-name`, `--pattern-type` |
| `create` | `create_acls([acl])` | Same as describe but `--principal`, `--operation`, `--resource-type`, `--resource-name` required; `--host` defaults to `*`; `--permission-type` defaults to `allow`; `--pattern-type` defaults to `literal` |
| `delete` | `delete_acls([filter])` | Same filter args as describe |

#### Cluster Group (`python -m kafka.admin cluster`)

| Command | Method | Key Arguments |
|---|---|---|
| `describe` | `describe_cluster()` | (none) |
| `describe-quorum` | `describe_metadata_quorum()` | (none) |
| `api-versions` | `api_versions()` | `-k`/`--api-key` (filter), `--raw` |
| `broker-version` | `get_broker_version_data(id)` | `--broker` (required) |
| `describe-features` | `describe_features()` | `-f`/`--feature` (filter) |
| `update-features` | `update_features(...)` | `-f`/`--feature` (feature=value), `--downgrade`, `--unsafe`, `--timeout`, `--validate-only` |
| `describe-log-dirs` | `describe_log_dirs(...)` | `--broker`, `--topic` |
| `alter-log-dirs` | `alter_replica_log_dirs(...)` | `-a`/`--assignment` (format: `TOPIC:PARTITION:BROKER_ID=/path`) |

#### Configs Group (`python -m kafka.admin configs`)

| Command | Method | Key Arguments |
|---|---|---|
| `describe` | `describe_configs(...)` | `-r`/`--resource-type` (required), `-n`/`--resource-name` (required), `-c`/`--config` (filter), `--dynamic`, `--modified`, `--static`, `--default` |
| `alter` | `alter_configs(...)` | `-r` (required), `-n` (required), `-c` (required, `key=value` or `key=set(val)`/`del(val)`/`add(val)`/`sub(val)` for incremental), `-v`/`--validate-only`, `--force-incremental`/`--force-alter` |
| `list` | `list_config_resources(...)` | `-r`/`--resource-type` (filter) |
| `reset` | `reset_configs(...)` | `-r` (required), `-n` (required), `-c` (keys to reset), `-v`/`--validate-only` |

#### Groups Group (`python -m kafka.admin groups` or `python -m kafka.admin consumer-groups`)

Both names route to the same subcommand group and expose identical subcommands (list, describe, delete, etc.). Implement by registering the same subparser configuration under both group names so that `python -m kafka.admin consumer-groups --help` lists all subcommands identically to `python -m kafka.admin groups --help`.

| Command | Method | Key Arguments |
|---|---|---|
| `list` | `list_groups(...)` | `--state`, `--type` |
| `describe` | `describe_groups(ids)` | `-g`/`--group-id` (required) |
| `delete` | `delete_groups(ids)` | `-g` (required) |
| `list-offsets` | `list_group_offsets(id)` | `-g` (required) |
| `alter-offsets` | `alter_group_offsets(...)` | `-g` (required), `-o`/`--offset` (`TOPIC:PARTITION:OFFSET`), `--group-coordinator-id` |
| `reset-offsets` | `reset_group_offsets(...)` | `-g` (required), `-p`/`--partition` (`TOPIC:PARTITION`), plus one of: `-s`/`--spec`, `--to-offset`, `--shift-by`, `--by-duration`, `--to-datetime`, `--to-current` (mutually exclusive, one required) |
| `delete-offsets` | `delete_group_offsets(...)` | `-g` (required), `-p` (required, `TOPIC:PARTITION`), `--group-coordinator-id` |
| `remove-members` | `remove_group_members(...)` | `-g` (required), `-m`/`--member-id`, `-i`/`--group-instance-id`, `--reason`, `--group-coordinator-id` |

#### Partitions Group (`python -m kafka.admin partitions`)

| Command | Method | Key Arguments |
|---|---|---|
| `create` | `create_partitions(...)` | `-p`/`--topic-partitions` (`TOPIC:COUNT`), `--timeout-ms`, `--validate-only` |
| `describe` | `describe_topic_partitions(...)` | `-t`/`--topic` (required), `--response-partition-limit`, `--cursor-topic`, `--cursor-partition` |
| `list-offsets` | `list_partition_offsets(...)` | `-t`/`--topic`, `-s`/`--spec`, `-p`/`--partition` (`TOPIC:PARTITION:SPEC`, partition can be number, range `0-2`, open range `1-`, or `*`) |
| `list-reassignments` | `list_partition_reassignments(...)` | `-p` (`TOPIC:PARTITION`), `--timeout-ms` |
| `alter-reassignments` | `alter_partition_reassignments(...)` | `-r`/`--reassign` (`TOPIC:PARTITION=BROKER_IDS` or `=cancel`), `--timeout-ms`, `--no-raise-errors` |
| `delete-records` | `delete_records(...)` | `-r`/`--record` (`TOPIC:PARTITION:OFFSET`, -1 for high-water mark), `--timeout-ms`, `--partition-leader-id` |
| `elect-leaders` | `elect_leaders(...)` | `--election-type` (preferred/unclean), `-p`, `-t`, `--timeout-ms`, `--no-raise-errors` |

#### Topics Group (`python -m kafka.admin topics`)

| Command | Method | Key Arguments |
|---|---|---|
| `list` | `list_topics()` | (none) |
| `describe` | `describe_topics(topics)` | `-t`/`--topic` |
| `create` | `create_topics(...)` | `-t` (required), `--num-partitions` (default -1), `--replication-factor` (default -1) |
| `delete` | `delete_topics(...)` | `-t` (by name), `--id` (by UUID) |

#### Users Group (`python -m kafka.admin users`)

| Command | Method | Key Arguments |
|---|---|---|
| `describe-scram-credentials` | `describe_user_scram_credentials(...)` | `--user` (optional, repeatable) |
| `alter-scram-credentials` | `alter_user_scram_credentials(...)` | `--delete` (`USER:MECHANISM`), `--upsert` (`USER:MECHANISM:PASSWORD`), `--iterations` |

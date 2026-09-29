#!/bin/bash
# Offline grading. The test harness, compression deps, the Apache Kafka 4.0.1 broker binary, and a
# Java 17 JRE are all pre-baked in the per-task image (see environment/Dockerfile), and PIP_NO_INDEX
# is set. There is NO network — no apt-get / curl / downloads here. The integration tests talk to a
# real broker on localhost:9092, which this script starts from the baked /opt/kafka.
#
# Note: no `set -e` — the reward logic below relies on capturing the test command's exit code.

# /app/.git can arrive owned by a foreign UID: Harbor preserves numeric ownership across the
# artifact round-trip, and this container runs as root. Any git command the build issues would
# then fail with "dubious ownership". System scope is required rather than GIT_CONFIG_* in the
# environment: build tools strip those from subprocesses (pip does, for one), so only on-disk
# config reaches the git call that matters.
git config --system --add safe.directory '*' 2>/dev/null || true

# Install/build the project offline (setup.sh was written by solve.sh / the agent).
bash ./setup.sh

# Start the baked Kafka 4.0.1 broker (KRaft mode) on localhost:9092 using the baked Java 17 JRE.
export JAVA_HOME=${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}
export PATH="$JAVA_HOME/bin:$PATH"
export KAFKA_ROOT=${KAFKA_ROOT:-/opt/kafka}

CLUSTER_ID=$("$KAFKA_ROOT"/bin/kafka-storage.sh random-uuid)

cat > /tmp/kafka-kraft.properties <<PROPEOF
process.roles=broker,controller
node.id=1
controller.quorum.bootstrap.servers=localhost:19093
listeners=PLAINTEXT://localhost:9092,CONTROLLER://localhost:19093
inter.broker.listener.name=PLAINTEXT
advertised.listeners=PLAINTEXT://localhost:9092,CONTROLLER://localhost:19093
controller.listener.names=CONTROLLER
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
log.dirs=/tmp/kraft-combined-logs
num.partitions=4
default.replication.factor=1
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
offsets.commit.timeout.ms=500
offsets.topic.num.partitions=2
group.min.session.timeout.ms=1000
group.initial.rebalance.delay.ms=0
log.cleaner.enable=false
authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer
allow.everyone.if.no.acl.found=true
PROPEOF

"$KAFKA_ROOT"/bin/kafka-storage.sh format --standalone -t "$CLUSTER_ID" -c /tmp/kafka-kraft.properties

"$KAFKA_ROOT"/bin/kafka-server-start.sh /tmp/kafka-kraft.properties &
KAFKA_PID=$!

echo "Waiting for Kafka broker to start..."
KAFKA_READY=0
for i in $(seq 1 60); do
    if "$KAFKA_ROOT"/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092 >/dev/null 2>&1; then
        KAFKA_READY=1
        echo "Kafka broker is ready after ${i}s"
        break
    fi
    sleep 1
done

if [ "$KAFKA_READY" -ne 1 ]; then
    echo "ERROR: Kafka broker failed to start within 60 seconds"
    kill $KAFKA_PID 2>/dev/null
    echo 0 > /logs/verifier/reward.txt
    exit 1
fi

export KAFKA_BOOTSTRAP=localhost:9092
export KAFKA_VERSION=4.0.1

mkdir -p /logs/verifier
pytest --ctrf /logs/verifier/ctrf.json /tests/test_kafka_python.py -v --timeout=300 -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

kill $KAFKA_PID 2>/dev/null

# MQTT 5.0 Command-Line Client

Implement a command-line **MQTT 5.0 client** in **TypeScript**. It connects to MQTT brokers and lets
users publish messages to topics, subscribe to topics and print received messages, and test
connections — all from the terminal, with connection options, QoS, retained messages, MQTT 5.0
properties, will messages, payload format conversion, schema (protobuf/avro) encoding, websocket
transport, benchmarking, and scenario-based simulation.

## Working directory & deliverables

Implement the client **from scratch** by writing source files into the **current working directory**
(the project root — the directory these instructions are in). **Do NOT clone, download, or
`npm install` anything** — the environment is offline and every dependency listed below, together
with the TypeScript compiler that builds and grades the project, is already installed in the shared
tree **`/opt/node_modules`**; the build harness links that tree to `./node_modules` in the project
root before running `setup.sh` (while developing you can link it yourself with
`ln -sfn /opt/node_modules ./node_modules`). Build against it: a `tsc` found elsewhere on `PATH` may
be a different, newer version, so `tsconfig.json` must use only compiler options the TypeScript in
`/opt/node_modules` accepts.

Create exactly this layout in the current directory:

```
./
├── bin/
│   └── index.js        # executable entry: `#!/usr/bin/env node`; requires the compiled CLI and runs it
├── src/                # your TypeScript source (command definitions + implementation)
│   └── index.ts        # entry point; add other src/*.ts as needed
├── package.json        # project manifest
├── tsconfig.json       # compiles src/ → dist/ (outDir "dist", module "commonjs")
└── setup.sh            # builds the project (see the "setup.sh" section at the end)
```

After `setup.sh` runs, invoking **`node bin/index.js <command> [options]`** must run the CLI. So
`bin/index.js` must load the compiled entry (`../dist/src/index.js`), and `tsc` must emit
`dist/src/index.js` from `src/index.ts`.

## Dependencies (pre-installed, available to `import`)

`mqtt` (MQTT.js — the protocol client), `commander` (argument parsing), `chalk` (colored output),
`cbor`, `msgpackr`, `protobufjs`, `avsc`, `json-bigint`, `lodash`, `@faker-js/faker` (simulation data),
`cli-table3` (table output). Use `mqtt` for all broker communication — do not reimplement the MQTT
protocol.

## Commands

Provide these commands:

- **`conn`** — connect to a broker (connectivity check).
- **`pub`** — publish a message to one topic, then exit.
- **`sub`** — subscribe to one or more topics and print each received message; keeps running.
- **`bench conn` / `bench pub` / `bench sub`** — benchmark subcommands (grouped under a `bench` command)
  that open a configurable number of connections and publish/subscribe at a configurable rate.
- **`simulate`** — publish scenario-generated messages (built-in scenarios) at a configurable rate.
- **`ls`** — list information; `ls --scenarios` lists the built-in simulation scenarios.

## Connection options (accepted by `conn`, `pub`, and `sub`)

| Flag | Meaning | Default |
|------|---------|---------|
| `-h, --hostname <HOST>` | broker host | `localhost` |
| `-p, --port <PORT>` | broker port | `1883` |
| `-u, --username <USER>` / `-P, --password <PASS>` | credentials | — |
| `-i, --client-id <ID>` | client id | auto-generated |
| `-V, --mqtt-version <5/3.1.1/3.1>` | protocol version; accept both `5` and `5.0` | `5` |
| `-l, --protocol <PROTO>` | transport protocol: `mqtt`, `mqtts`, `ws`, or `wss` (any other value is an error) | `mqtt` |
| `--path <PATH>` | websocket path (used with `ws`/`wss`) | `/mqtt` |
| `-wh, --ws-headers <KV...>` | websocket headers (`"key: value"`); **only valid on a websocket connection** — using them with a non-websocket protocol is an error | — |
| `-am, --authentication-method <METHOD>` | enhanced-auth method; **only** `SCRAM-SHA-1`, `SCRAM-SHA-256`, `SCRAM-SHA-512` are valid — any other value is an error (see "Errors") | — |

### Will-message options (accepted by `conn`, `pub`, and `sub`)

A client may register a **will message** the broker publishes on its behalf if it disconnects
ungracefully (without a clean DISCONNECT):

| Flag | Meaning |
|------|---------|
| `-Wt, --will-topic <TOPIC>` | will topic |
| `-Wm, --will-message <BODY>` | will payload |
| `-Wq, --will-qos <0/1/2>` | will QoS |
| `-Wr, --will-retain` | mark the will message retained (a retained will is delivered to subscribers that connect after it fires) |
| `-Wct, --will-content-type <TYPE>` | MQTT 5.0 will content-type property |
| `-Wup, --will-user-properties <KV...>` | MQTT 5.0 will user properties (`"key: value"`) |

### Saving & loading options (`conn`, `pub`, `sub`, `bench`, `simulate`)

| Flag | Meaning |
|------|---------|
| `-so, --save-options [PATH]` | save the command's options to a config file (JSON, or YAML when the path ends in `.yaml`/`.yml`); options are stored under a key named for the command (e.g. `pub`) |
| `-lo, --load-options [PATH]` | load options from the config file for this command; options given **explicitly on the command line override** the loaded ones |

When `-so` writes the config file it prints a confirmation naming the saved file — a message
containing `saved`/`config` (e.g. `Configurations saved to <PATH>`).

A global **`--version`** (and `-v` on the top-level program) flag prints the tool's version string.

## `pub` options

| Flag | Meaning |
|------|---------|
| `-t, --topic <TOPIC>` | target topic (**required**; publishing to a topic containing wildcard characters `+`/`#` is an error) |
| `-m, --message <BODY>` | message payload (has a default) |
| `-s, --stdin` | read the message payload from **stdin** instead of `-m` |
| `--file-read <PATH>` | read the message payload from a **file** |
| `-q, --qos <0/1/2>` | QoS (default `0`) |
| `-r, --retain` | publish as a retained message |
| `-f, --format <TYPE>` | payload format — see "Payload formats" |
| `-S, --payload-size <SIZE>` | generate a random payload of the given size (e.g. `1KB`, `512B`, `2.5MB`); units are **binary** — a bare number or `B` = bytes, `1KB` = 1024 bytes, `1MB` = 1024×1024 bytes; **ignored if an explicit `--message` is provided** |
| `-Pp, --protobuf-path <PATH>` | path to a `.proto` schema file (with `-Pmn`) — see "Schema encoding" |
| `-Pmn, --protobuf-message-name <NAME>` | protobuf message type name (with `-Pp`) |
| `-Ap, --avsc-path <PATH>` | path to an `.avsc` avro schema file — see "Schema encoding" |

### MQTT 5.0 publish properties (`pub`)

`pub` also accepts the following MQTT 5.0 message properties. Each is attached to the published
message and, per the MQTT 5.0 spec, forwarded by the broker to subscribers — so in `--output-mode
clean` they appear under `packet.properties` (see below).

| Flag | Property | Notes |
|------|----------|-------|
| `-up, --user-properties <KV...>` | user properties | repeatable / variadic; each value is a `"key: value"` pair (colon-separated). Surfaces as `packet.properties.userProperties` (an object of key→value). |
| `-ct, --content-type <TYPE>` | content type | surfaces as `packet.properties.contentType`. |
| `-e, --message-expiry-interval <NUMBER>` | message expiry (seconds) | surfaces as `packet.properties.messageExpiryInterval` (the broker may forward a slightly decremented value). |
| `-rt, --response-topic <TOPIC>` | response topic | surfaces as `packet.properties.responseTopic`. |
| `-cd, --correlation-data <DATA>` | correlation data | the string's bytes; surfaces as `packet.properties.correlationData` (raw bytes). |
| `-pf, --payload-format-indicator` | payload-format indicator | boolean flag; surfaces as `packet.properties.payloadFormatIndicator` (`true`). |

### Schema encoding (protobuf / avro)

Separately from `-f`, `pub` can encode a JSON `--message` using a schema, and `sub` can decode it:

- **protobuf** — pass `-Pp <file.proto>` **and** `-Pmn <MessageName>`. On `pub`, the JSON message is
  parsed and encoded to protobuf wire bytes with that message type. On `sub`, passing the same
  `-Pp`/`-Pmn` decodes the received bytes back to JSON for display.
- **avro** — pass `-Ap <file.avsc>`. On `pub`, the JSON message is encoded with the avro schema; on
  `sub`, passing `-Ap` decodes it back to JSON for display.

Schema **decoding on `sub` applies in the default output mode** (the decoded JSON is printed). In
`--output-mode clean`, the `payload` reflects the raw received bytes (subject to `-f` only).

## `sub` options

| Flag | Meaning |
|------|---------|
| `-t, --topic <TOPIC...>` | one or more topics (**required**) |
| `-q, --qos <0/1/2...>` | per-topic QoS |
| `-f, --format <TYPE>` | how to decode received payloads for display — see "Payload formats" |
| `-Pp, --protobuf-path <PATH>` / `-Pmn, --protobuf-message-name <NAME>` | decode received payloads with a protobuf schema — see "Schema encoding" |
| `-Ap, --avsc-path <PATH>` | decode received payloads with an avro schema — see "Schema encoding" |
| `-v, --verbose` | (default output mode) also print the full received MQTT packet |
| `--file-write <PATH>` | append each received message to a file |
| `--file-save <PATH>` | write each received message to a **new** file (a numbered variant of `<PATH>` per message) |
| `--delimiter <CHAR>` | delimiter appended after each message written with `--file-write` (default `\n`) |
| `--output-mode <default/clean>` | `clean` prints each received message as a JSON object (see below); `default` prints a human-readable line (see "Default output") |

### Default output

In the **default** output mode (`sub` without `--output-mode clean`), each received message is printed
in a human-readable form that includes the **topic**, the **QoS**, a human-readable **payload size**
(bytes formatted like `5B`, `1.2KB`, …), and the decoded **payload**. Schema (protobuf/avro) decoding
is applied in this mode.

### `--output-mode clean`

In `clean` mode, `sub` prints, for each received message, a JSON object with at least these fields:

```json
{ "topic": "<topic>", "payload": "<decoded payload>", "packet": { ...raw MQTT packet incl. "retain", "qos", "properties" } }
```

`payload` is the message decoded according to `--format`. This mode is intended for programmatic
consumption, so the output must be valid, parseable JSON per message.

## Payload formats (`-f, --format`)

Valid values: `base64`, `json`, `hex`, `cbor`, `msgpack`, `binary`. Any other value is an error.

- **On publish** the format **encodes** the `--message` input:
  - `base64` / `hex` — treat the input string as base64/hex and decode it to the raw bytes that are published.
  - `json` — parse the input as JSON and publish it (large integers beyond 2^53 must be preserved exactly, not rounded).
  - `cbor` / `msgpack` — parse the input as JSON and encode it to CBOR / MessagePack bytes.
  - `binary` — publish the bytes unchanged.
- **On subscribe** the format **decodes** the received bytes for display:
  - `hex` — the payload's bytes rendered as a hex string.
  - `base64` — the payload's bytes rendered as base64.
  - `json` / `cbor` / `msgpack` — decode and display as JSON text (preserving large integers for `json`).

## Behavior the client must exhibit

- **Publish/subscribe round-trip:** a message published to a topic is delivered to a subscriber on
  that topic. A **retained** message is delivered to a subscriber that connects *after* it was
  published, and is marked retained in the received packet.
- **QoS** 0, 1, and 2 are supported end-to-end. The delivered QoS is the minimum of the publish QoS and
  the subscription QoS (a message published at QoS 2 to a QoS 0 subscription is delivered at QoS 0).
- **Protocol versions** 3.1.1 and 5 both connect and publish successfully.
- **`conn`** connects to the broker and, once the connection is established, prints a success
  confirmation containing `Connected` (distinct from the `Connecting...` status printed while the
  attempt is still in progress).
- **Input sources:** the publish payload can come from `-m`, from **stdin** (`-s`), or from a **file**
  (`--file-read`); a subscriber can append received messages to a file (`--file-write`).
- **`--payload-size`** produces a random payload of the requested byte size.
- **Format round-trips** behave as described above (base64 decode-on-publish, hex display,
  json big-integer preservation, cbor/msgpack object round-trips, `binary` publishes bytes unchanged).
- **MQTT 5.0 properties** set on `pub` (user-properties, content-type, message-expiry-interval,
  response-topic, correlation-data, payload-format-indicator) are delivered to a subscriber and appear
  under `packet.properties` in `--output-mode clean`.
- **Multi-topic subscribe:** `sub` accepts several `-t` topics at once and prints messages received on
  any of them.
- **WebSocket transport:** over a `ws` connection, publish/subscribe work as they do over TCP.
- **Will messages:** a client that registers a will and then disconnects ungracefully causes the broker
  to publish the will message to subscribers of the will topic.

(Schema, will, and websocket details are in their respective sections above.)

## `bench` — benchmark subcommands

`bench conn`, `bench pub`, and `bench sub` open a number of connections and report progress. Common
options: `-c, --count <NUMBER>` (number of connections), `-i, --interval <MS>` (connect interval),
`-t/-m/-q` as in `pub`/`sub`, and for `bench pub`: `-im, --message-interval <MS>` and
`-L, --limit <NUMBER>` (max messages to publish; `0` = unlimited).

- **`bench conn -c N`** opens `N` connections and, once all are connected, prints a line reporting
  **`Created N connections`** (with the elapsed time).
- **`bench pub -c N -L M -t <topic> -m <body>`** publishes messages and, on completion, prints a
  summary line reporting the **`Published total: <count>`** (and a message rate). The published
  messages are delivered to subscribers of the topic.
- **`bench sub -c N -t <topic>`** opens `N` subscriber connections and, as messages arrive, reports a
  running **`Received total: <count>`** (and a receive rate).

In `bench pub`/`bench sub` (and `simulate`) topics, the variables **`%i`** (client index, 1-based),
**`%c`** (client id), and **`%u`** (username) are substituted per client — e.g. `bench pub -c 2 -t
'x/%i'` publishes to `x/1` and `x/2`.

## `simulate` — scenario publishing

`simulate` publishes messages produced by a **scenario** generator.

| Flag | Meaning |
|------|---------|
| `-sc, --scenario <NAME>` | a built-in scenario name (see `ls --scenarios`) |
| `-f, --file <PATH>` | a custom scenario `.js` file |
| `-c, --count <N>`, `-i, --interval <MS>`, `-im, --message-interval <MS>`, `-L, --limit <N>`, `-t, --topic <TOPIC>` | as in `bench pub` |

Built-in scenarios include **`smart_home`**, **`tesla`**, **`weather`**, and **`IEM`**. Each scenario
generates a **structured JSON message** and publishes it to the topic. The values are randomly
generated per message, but each scenario emits its own top-level field structure:

- **`smart_home`** — a home identified by `home_id`, plus a `rooms` array whose elements each carry
  `room_type`, `temperature`, and `humidity` (among other per-room fields), and a `timestamp`.
- **`tesla`** — vehicle telemetry including `model`, `state`, and `battery_level` (among many other
  fields).
- **`weather`** — a station identified by `station_id`, with a nested `current` object that carries
  `temp_c` and `humidity` (among other readings).
- **`IEM`** — industrial energy monitoring with `factory_id`, `factory`, and a `values` object of
  per-equipment energy readings, plus a `timestamp`.

`simulate` requires either `-sc` or `-f`; a missing scenario, or an unknown scenario name, is an error.

## `ls` — list scenarios

`ls --scenarios` prints the built-in scenario names (`smart_home`, `tesla`, `weather`, `IEM`) with a
short description of each.

## Errors

The following are usage errors: the client prints an error message and exits with a **non-zero exit
code** (it must not publish/subscribe):

- an invalid `--format` value,
- an invalid `--qos` value (not 0/1/2),
- an invalid `--mqtt-version`,
- publishing (`pub`) to a topic containing wildcard characters (`+` or `#`),
- a missing required `--topic` on `pub` or `sub`,
- an unsupported `--authentication-method`,
- a malformed user-property value that is not a `"key: value"` pair,
- websocket headers (`-wh`) supplied on a non-websocket connection,
- a payload that cannot be encoded in the requested `--format` (e.g. invalid JSON with `-f json`),
- for `simulate`: no scenario/file specified, or an unknown scenario name.

## setup.sh

Write a `setup.sh` in the project root that compiles the TypeScript to `dist/`. Dependencies are
already installed (offline), so it only builds:

```bash
npx tsc
```

`npx` picks `tsc` up from the linked `./node_modules/.bin`, so that is the compiler your
`tsconfig.json` has to satisfy.

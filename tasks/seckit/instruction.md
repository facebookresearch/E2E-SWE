# seckit — JDBC connection-string filtering

Implement the **JDBC connection-string filtering subsystem** of Alibaba's `seckit` security library
in Java. Given an untrusted JDBC URL, the library removes dangerous or malformed connection
parameters (parameters that enable deserialization gadgets, local-file loading, SSRF, log
injection, etc.), injects a few hardening parameters for MySQL-family URLs, and returns a cleaned
URL — or throws when the URL itself is structurally unsafe.

Put your implementation under `/app/src` as Java sources. Target **Java 8** language level (it will
be compiled with a modern JDK; write plain Java — no external libraries are required). Provide an
executable `/app/setup.sh` that compiles your sources offline, e.g.:

```bash
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -encoding UTF-8 -d /app/out
```

## Public API

All entry points are `public static` methods on `com.alibaba.seckit.SecurityUtil`:

```java
package com.alibaba.seckit;

public class SecurityUtil {
    public static String       filterJdbcConnectionSource(String url) throws JdbcURLException;
    public static FilterResult filterJdbcConnectionSourceWithResult(String url) throws JdbcURLException;
    public static void         registerFilter(Filter filter);
}
```

Supporting types live in package `com.alibaba.seckit.jdbc`:

- `JdbcURLException extends java.net.MalformedURLException` — base checked exception (has a no-arg and
  a `String` constructor).
- `JdbcURLUnsafeException extends JdbcURLException` — thrown when a URL is **structurally unsafe**
  (bad host/port, injection attempt, forbidden scheme, malformed userinfo/braces, …).
- `JdbcURLNotSupportedException extends JdbcURLException` — thrown when the scheme is unknown (no
  registered filter matches).
- `FilterResult` — result of `filterJdbcConnectionSourceWithResult`. Getters: `getBefore()` (the
  original URL), `getAfter()` (the filtered URL), `getDeleted()` / `getAdded()`
  (`Map<String,String>` of removed / injected parameters), and **`boolean isSafe()`**. A result is
  **safe iff no parameter was removed and none was injected** — i.e. the input passed through
  unchanged. Any deletion or injection sets `isSafe()` to `false`.
- `Filter` — the per-dialect filter SPI, used by `registerFilter` (see "Custom filters" below).

`filterJdbcConnectionSource(url)` is equivalent to
`filterJdbcConnectionSourceWithResult(url).getAfter()`.

## The filtering model

Each JDBC URL is dispatched to a **dialect filter** chosen by its scheme (the substring up to the
first `//`, lower-cased), then processed as follows:

1. **Parse** the URL into `scheme`, `host` (possibly a comma-separated failover list, possibly with
   `[ipv6]` and `:port`), an optional `database`/path, and an ordered set of `key=value`
   **properties**. Keys and values are trimmed of surrounding whitespace. Structural problems
   (missing `//`, a host that fails the dialect's host pattern, a port outside `0..65535` or not an
   integer, a database that fails the dialect's database pattern) throw `JdbcURLUnsafeException`.
2. **Key filtering.** A property is **kept** only if its key is in the dialect's *accepted-key set*
   **or** its *whitelist*; otherwise it is removed. Unless stated otherwise key matching is
   case-sensitive; some dialects match case-insensitively (noted per dialect).
3. **Value validation.** For a kept key that is **not** whitelisted and has a non-empty value, the
   value must match a regex or it is removed. The default value pattern is
   `^[a-zA-Z0-9_\-.:\[\]]+$`; some keys/dialects use a wider pattern (noted per dialect).
   **Whitelisted keys skip value validation entirely** (their values pass through verbatim).
4. **Injection.** A few dialects add hardening parameters (noted per dialect).
5. **Re-serialize** to `scheme//host[:port][/database]<marker><params>`, where `<params>` are the
   surviving `key=value` pairs joined by the dialect's separator.

### Canonical output format and parameter ordering

The fixed part of the output — scheme, host (with any failover list and `:port`), and database — is
reproduced **exactly** (including any normalization noted per dialect). The **relative order of the
surviving parameters is unspecified**; you may emit them in any order. The tests compare the
parameter section as an unordered set of `key=value` tokens, so any ordering that preserves the
correct set of tokens (with correct values) passes. What you must get right is: which parameters
survive, their exact values (after any documented encoding), the separator/marker, and the fixed
prefix.

Default marker/separator: parameters begin after `?` and are joined by `&`. Dialects that differ are
noted below.

## Dialect contracts

For each family: the schemes it handles, its separator/format, the accepted keys the tests rely on,
whitelisted keys, injected parameters, non-default value patterns, and structural rules. "Any other
key is removed" always applies. Reproduce the exact parameter values shown.

### MySQL family
Schemes: `jdbc:mysql:`, `jdbc:mariadb:`, `jdbc:gbase:`, `jdbc:oceanbase:`, `jdbc:mysql2:`,
`jdbc:mysql+srv:`, `mysqlx:`, `mysqlx+srv:`, and the `:loadbalance:` / `:replication:` / `:failover:`
sub-variants (e.g. `jdbc:mysql:loadbalance:`). Marker `?`, separator `&`.
- Accepted keys include: `useUnicode`, `characterEncoding`, `rewriteBatchedStatements`,
  `socketTimeout`, `connectTimeout`, `serverTimezone`, `enabledTLSProtocols`, `sessionVariables`,
  `user`, `password` (and many other standard MySQL properties). Key matching is case-sensitive, so
  `ConnectTimeout` is not accepted (only `connectTimeout`).
- Whitelist: `user`, `username`, `pass`, `password`, `sessionVariables`.
- **Injected safety parameters (always forced to `false`)**: `allowLoadLocalInfile`,
  `allowUrlInLocalInfile`, `autoDeserialize`, and `allowLocalInfile` — **except** for `jdbc:gbase:`,
  which does **not** inject `allowLocalInfile` (it still injects the other three). These four keys
  are **not** accepted or whitelisted pass-through keys (they are the dangerous
  deserialization / local-file-loading parameters the library removes): any value supplied in the
  input is always stripped first, so each key appears in the output only via injection.
- Value patterns: `serverTimezone` → `^[a-zA-Z0-9_\-.:\[\]/+%]+$` (allows `/ + %`);
  `enabledTLSProtocols` → `^[a-zA-Z0-9_\-.,]+$` (allows `,` but not `:`).
- Database names may contain `$`, Han characters, spaces, `=` and `#`. Failover host lists
  (`host1:3306,host2:1234`) are preserved.

### PostgreSQL family
Schemes: `jdbc:postgresql:`, `jdbc:polardb:`, `jdbc:opengauss:`, `jdbc:kingbase8:`. Marker `?`,
separator `&`.
- Accepted keys include: `stringtype`, `socketTimeout`, `preferQueryMode`, `sslmode`, `user`,
  `password`, `conf:stsToken` (and other standard Postgres properties). Case-sensitive.
- Whitelist: `user`, `username`, `pass`, `password`, `CustomProperties`.
- Value patterns: `conf:stsToken` → `^[a-zA-Z0-9/+=]+$`.
- **Value URL-coding:** property values are URL-decoded when parsed and URL-encoded (UTF-8) when
  serialized. E.g. an input `conf:stsToken=ZGNmdn%2BNnYmhAIy/QlYmFhZ3lobmptaw==` decodes to
  `...+.../...==`, passes the pattern, and is re-emitted as
  `conf:stsToken=ZGNmdn%2BNnYmhAIy%2FQlYmFhZ3lobmptaw%3D%3D`.
- The database name may contain `@`; IPv6/failover host lists (`[::1]:5432,localhost:5432`) are
  preserved.

### SQL Server
Scheme `jdbc:sqlserver:`. Format `jdbc:sqlserver://host[\instance][:port];k=v;k2=v2` (semicolon
marker and separator; the fixed prefix ends at the first `;`). Key matching is **case-insensitive**.
- Accepted keys include: `database`, `databaseName`, `failoverPartner`, `encrypt`, `socketTimeout`,
  `language`, `loginTimeout`, `instanceName`, `schemaName`, `user`, `password`.
- Value pattern for `database`/`databaseName`/`schemaName`: `^[a-zA-Z0-9_\-.\p{script=Han}$@\[\]{}() +]+$`
  (allows Han script, brackets, braces, parentheses and spaces); other keys use the default pattern.
- **Brace/bracket-escaped values** in `databaseName`: a value wrapped in `[...]`, `{...}` or `(...)`
  is kept verbatim; inside `{...}` a doubled `}}` is an escaped literal `}` (both characters kept)
  and a single `}` closes the value. A leading space before the value is trimmed. It is **unsafe**
  (throw `JdbcURLUnsafeException`) if a `{` appears when the value is already non-empty
  (e.g. `databaseName=abc{foo}`), or if any non-space character follows the closing `}`.
- The host may include an `\instanceName` and/or `:port`. A space in the server name or instance
  name is **unsafe** (throw). Whitespace around a value is trimmed.

### Colon/semicolon list dialects
- **DB2** (`jdbc:db2:`): format `jdbc:db2://host[:port]/db:k=v;k2=v2;` — colon after the database,
  semicolons between properties, **and a trailing `;`**. Accepted keys: `currentSchema`,
  `securityMechanism`. Whitelist is **empty** (so `user`/`password` are removed). With no surviving
  properties the output is just `jdbc:db2://host[:port]/db` (no colon, no trailing `;`).
- **Informix** (`jdbc:informix-sqli:`): same colon form but with **no trailing `;`**:
  `jdbc:informix-sqli://host[:port]/db:INFORMIXSERVER=abc`. Accepted key: `INFORMIXSERVER`. Empty
  whitelist.
- **NetSuite** (`jdbc:ns:`): semicolon marker/separator `jdbc:ns://host[:port]/db;k=v`. Accepted
  keys: `ServerDataSource`, `Encrypted`, `CustomProperties`, `NegotiateSSLClose`.
- **As400** (`jdbc:as400:`): semicolon marker/separator. Accepted keys (note embedded spaces):
  `naming`, `errors`, `date format`, `data compression`, `block size`, `data truncation`,
  `decimal data errors`.
- **SAP** (`jdbc:sap:`): marker `?`, separator `&`; the **host may contain `;` and `:`** (e.g.
  `localhost:3200;failover:1234`). Accepted keys: `reconnect`, `databaseName`, `currentSchema`,
  `trustServerCertificate`. Empty whitelist.
- **Impala** (`jdbc:impala:`): semicolon marker/separator. Accepted keys include `AuthMech`,
  `httpPath`, `UID`, `PWD`, `SocketTimeout`, `transportMode`, `principal`. Whitelist: `UID`, `PWD`,
  `DelegationUID`. `httpPath` value pattern allows `/` (`^[a-zA-Z0-9_\-.:\[\]/]+$`).
- **Greenplum** (`jdbc:pivotal:greenplum:`): semicolon marker/separator, **case-insensitive**.
  Accepted keys include `DatabaseName`, `LoginTimeout`, `AuthenticationMethod`, `User`, `Password`.
  Whitelist: `user`, `password`, `ServicePrincipalName`. The semicolon split is literal, so a value
  containing `;` (e.g. `InitializationString=(command1;command2)`) is broken up and dropped as
  non-accepted keys.

### Oracle (thin)
Handled when the URL begins (case-insensitively) with `jdbc:oracle:thin:@`; the scheme is normalized
to lower-case `jdbc:oracle:thin:`. Three address forms:
- **EZConnect / URL**: `@host:port:sid` or `@host:port/service` or `@tcp://hosts:port/service`.
  Trailing `?params` are parsed as flat properties (marker `?`, separator `&`). Accepted flat keys:
  `oracle.net.CONNECT_TIMEOUT`, `oracle.jdbc.ReadTimeout`, `oracle.net.networkCompression`,
  `oracle.net.networkCompressionThreshold`. Other flat params are removed.
- **TNS**: `@(DESCRIPTION=...(ADDRESS=(PROTOCOL=TCP)(HOST=..)(PORT=..))..(CONNECT_DATA=(SERVICE_NAME=..)))`.
  Parse the parenthesized name/value tree, **stripping all incidental whitespace**, and prune it:
  keep only nodes whose (upper-cased) name is one of `DESCRIPTION`, `DESCRIPTION_LIST`, `ADDRESS`,
  `ADDRESS_LIST`, `ALIAS`, `PROTOCOL`, `HOST`, `PORT`, `SOURCE_ROUTE`, `LOAD_BALANCE`, `FAILOVER`,
  `CONNECT_DATA`, `SID`, `SERVER`, `SERVICE_NAME`, `INSTANCE_NAME`, `INSTANCE_ROLE`,
  `CONNECTION_ID_PREFIX`; drop every other node (e.g. `FOO`, `SECURITY`, `RETRY_COUNT`,
  `RETRY_DELAY`, `WALLET_LOCATION`). A `PROTOCOL` entry whose value is not `TCP`/`TCPS`
  (case-insensitive) is itself the only node dropped; its enclosing `ADDRESS` node and that address's
  other retained children (`HOST`, `PORT`, …) are kept. Re-serialize the surviving tree
  compactly as `(NAME=value)`; node order is preserved from the input. A non-accepted wrapper around
  the whole `DESCRIPTION` (e.g. `@(FOO=(DESCRIPTION=...))`) collapses to just `jdbc:oracle:thin:@`.

### Property-list drivers
- **Lindorm** (`jdbc:lindorm:table:`, `jdbc:lindorm:tsdb:`, `jdbc:lindorm:search:`,
  `jdbc:lindorm:phoenix:`, `jdbc:lindorm:analytics:`) and **Phoenix thin** (`jdbc:phoenix:thin:`):
  there is **no host** — the whole remainder after the scheme is a `;`-separated `key=value` list,
  re-serialized as `scheme` immediately followed by the surviving `;`-joined pairs (e.g.
  `jdbc:lindorm:table:url=...;serialization=...`). Lindorm accepted keys include `url`, `timeZone`,
  `serialization`, `user`, `password`, `database`, `lindorm.tsdb.driver.socket.timeout`; whitelist:
  `url`, `timeZone`, `avatica_user`, `avatica_password`, `user`, `username`, `password`. Phoenix
  accepted keys include `url`, `serialization`, `timeZone`, `user`, `password`; whitelist: `url`,
  `timeZone`, `avatica_user`, `avatica_password`, `user`, `password`.
- **DM** (`jdbc:dm:`): marker `?`, separator `&`. Accepted keys include both camelCase and
  UPPER_SNAKE forms, e.g. `schema`, `SCHEMA`, `appName`, `LOGIN_MODE`, `user`, `password`. The value
  pattern additionally allows a plain token, a `"quoted"` token, or a `(parenthesized)` token; a
  malformed value like `(4` (unbalanced) fails and is removed. Log-directory / file-path keys — in
  either case form — are **not** accepted and are removed (they enable local-file loading / log
  injection, mirroring the file-path keys removed for BigQuery).

### Redshift
Schemes `jdbc:redshift:`, `jdbc:redshift:iam:`. **Case-insensitive** keys. Output uses `;` as marker
and separator (input `?`-parameters are converted to `;`-parameters). Property values are
**URL-encoded** on output (e.g. `password=secret$#` → `password=secret%24%23`). Accepted keys
include `User`, `Password`, `SSL`, `SSLMode`, `App_Name`, `App_ID`, `DbUser`, `connectTimeout`,
`socketTimeout` (and other standard Redshift properties). Class-loading / socket-factory
properties (keys whose value names a Java class to instantiate) are **not** accepted and are
removed (mirroring the file-path keys removed for BigQuery). Whitelist includes `User`, `Password`,
`App_Name`, `App_ID`, `DbUser`, `Region`, etc. The non-iam form is `//host[:port]/db`; the iam form
is `jdbc:redshift:iam://host[:port]/http/path`.

### BigQuery
Scheme `jdbc:bigquery:`. Marker/separator `;` with a **trailing `;`** when properties survive. The
host is path-like (`https://www.googleapis.com/bigquery/v2:443`); an **empty host** (URL beginning
`jdbc:bigquery://;`) and a **port outside `0..65535`** (e.g. `:123456`) throw `JdbcURLException`.
Accepted keys include `ProjectId`, `OAuthType`, `OAuthServiceAcctEmail`, `OAuthAccessToken`,
`OAuthClientId`, `OAuthClientSecret`, `OAuthRefreshToken`, `OAuthPvtKey` (and others). Whitelist:
`OAuthPvtKey`. Non-default value patterns (lower-cased key lookup): `oauthserviceacctemail` →
`^[a-zA-Z0-9_\-.:,@]+$` (allows `@`, so a service-account email survives); `additionalprojects` →
`^[a-zA-Z0-9_\-.:,]+$`; `queryproperties` → `^[a-zA-Z0-9_\-.:,=]+$`; `oauthclientsecret` →
`^[a-zA-Z0-9_\-.:,/=+]+$`. **OAuthPvtKey guard:** after trimming, an `OAuthPvtKey` value is removed unless it
begins with `{` (inline JSON) — any value that starts with `/` or contains `../` (a file path /
traversal) is stripped; an inline `{...}` JSON key is kept verbatim. `ProjectId` and other
non-whitelisted values are subject to the default value pattern (so `ProjectId=$$Foo` is removed).
Keys carried as file paths, such as `OAuthPvtKeyPath` and `LogPath`, are not accepted and are removed.

### Userinfo drivers
- **Redis** (`jdbc:redis:`): marker `?`, separator `&`. May carry `user:pass@host` userinfo, which
  is preserved. Accepted keys include `user`, `password`, `database`, `connectionTimeout`,
  `socketTimeout`, `ssl`. Whitelist: `user`, `password`.
- **MongoDB** (`jdbc:mongodb:`, `jdbc:mongodb+srv:`, `mongodb:`, `mongodb+srv:`): the parameter
  separator on input is `&` **or** `;` (either splits parameters), and output joins with `&`. When
  no database is present the path is normalized to a trailing `/` (e.g.
  `mongodb://host/?ssl=true`). Accepted keys include `ssl`, `tls`, `authMechanism`, `authSource`,
  `authMechanismProperties`, `connectTimeoutMS`, `socketTimeoutMS`, `replicaSet`, `readPreference`.
  Whitelist: `user`, `username`, `pass`, `password`, `authMechanismProperties`. Userinfo
  (`user:pass@host`) is preserved and may contain `%`-escapes; malformed userinfo (more than one
  `:` before the `@`, or an `@` inside the userinfo) throws `JdbcURLUnsafeException`. Failover host
  lists are preserved.

### Hive family
- **Hive** (`jdbc:hive:`): **all** connection parameters are stripped; an empty database/path
  collapses (`jdbc:hive://host:8080/?x=y` → `jdbc:hive://host:8080`).
- **Hive2** (`jdbc:hive2:`): URL shape `jdbc:hive2://authority/db;sessionVars?hiveConfs#hiveVars` —
  three sections separated by `;` (session), `?` (conf) and `#` (var), each an independent
  `key=value` list re-emitted with `;` between its own entries and the section markers preserved
  (`...db;a=b?c=d#e=f`). The database name pattern rejects `*` (throw) but allows `$`. In every
  section a key is kept if it is accepted **or** begins with `http.cookie.`. Accepted keys include
  `retries`, `user`, `password`, `principal`, `transportMode`, `hive.server2.transport.mode`,
  `httpPath`, `hive.server2.thrift.http.path`, `token`, `compute-group`, and the `spark.*` tuning
  keys. Whitelist: `user`, `password`, `principal`. Value patterns: `httpPath` and
  `hive.server2.thrift.http.path` allow `/` (`^[a-zA-Z0-9_\-.:\[\]/]+$`). Key matching is
  case-sensitive (`httppath` is not accepted, only `httpPath`).

### Analytics / query-parameter dialects
- **ClickHouse** (`jdbc:clickhouse:`, `jdbc:ch:`, and their `:http:`/`:https:`/`:grpc:` variants):
  marker `?`, separator `&`. Accepted keys include `socket_timeout`, `connect_timeout`,
  `server_time_zone`, `use_time_zone`, `compress`, `database`, `ssl`, `sslmode`. `server_time_zone`
  / `use_time_zone` value pattern allows `/` (`^[a-zA-Z0-9_\-\[\]/+]+$`); a `%` in the value fails
  it. Failover endpoint lists (`endpoint1,server2,server3`) are preserved.
- **Vertica** (`jdbc:vertica:`): marker `?`, separator `&`, **case-insensitive**. Accepted keys
  include `User`, `Password`, `SSL`, `TLSmode`, `LoginTimeout`, `ReadOnly`. Whitelist: `user`,
  `username`, `pass`, `password`, `CustomProperties`. **Injects `DisableCopyLocal=true`** (unless
  already `true`).
- **Presto** (`jdbc:presto:`) and **Trino** (`jdbc:trino:`): marker `?`, separator `&`; the database
  may contain `/` (e.g. `hive/sales`). Presto accepted keys include `user`, `password`, `SSL`,
  `timeZoneId`, `accessToken`, `applicationNamePrefix`, `extraCredentials`; whitelist `user`,
  `password`, `KerberosPrincipal`; `timeZoneId` pattern allows `/`. Trino accepted keys include
  `user`, `password`, `SSL`, `clientTags`, `accessToken`, `sessionProperties`, `roles`,
  `extraCredentials`; whitelist `user`, `password`, `KerberosPrincipal`,
  `KerberosServicePrincipalPattern`. Trino value patterns: `clientTags` allows `,`; `accessToken`
  allows `+ / =`; `sessionProperties`/`roles`/`extraCredentials` allow `;`.
- **Teradata** (`jdbc:teradata:`): **marker `/`, separator `,`** (no database) —
  `jdbc:teradata://host/KEY=val,KEY2=val2`. Accepted keys are upper-case, including `USER`,
  `ACCOUNT`, `DATABASE`, `CHARSET`, `TMODE`, `PASSWORD`, `NEW_PASSWORD`. Real Teradata connection
  properties outside that accepted set are removed too (mirroring the
  real-driver keys stripped for BigQuery, Redshift, and DM). Whitelist: `PASSWORD`,
  `NEW_PASSWORD` (so a `PASSWORD` value may contain arbitrary characters such as `^&()(`).
- **Sybase** (`jdbc:sybase:Tds:`): case-insensitive; marker `?`, separator `&`. **The scheme is
  followed directly by the host with NO `//`** — the output shape is
  `jdbc:sybase:Tds:host[:port][/db]?k=v&k2=v2` (a URL not starting with `jdbc:sybase:Tds:` is
  unsafe). Accepted keys are upper-case, including `LITERAL_PARAMS`, `PACKETSIZE`, `HOSTNAME`,
  `CHARSET`, `DATABASE`, `SERVICENAME`, `USER`, `PASSWORD`. Whitelist: `USER`, `PASSWORD`,
  `NEWPASSWORD`, `SECONDARY_SERVER_HOSTPORT`. A key such as `SYBSOCKET_ FACTORY` (a space splits it)
  is not accepted and is removed.

### Cloud / search dialects
- **Elasticsearch** (`jdbc:es:`, `jdbc:elasticsearch:`) and **OpenSearch** (`jdbc:opensearch:`):
  marker `?`, separator `&`. The host may be prefixed by a connection type `http://` or `https://`
  (e.g. `jdbc:es://http://server:3456/`), which is preserved. When no database is present the path
  is normalized to a trailing `/`. ES accepted keys include `timezone`, `page.size`, `page.timeout`,
  `query.timeout`, `connect.timeout`, `network.timeout`, `ssl`, `user`, `password`; whitelist
  `user`, `password`, `timezone`; case-insensitive. OpenSearch accepted keys include `user`,
  `password`, `useSSL`, `fetchSize`, `auth`, `region`; whitelist `user`, `password`; the database
  pattern allows `/` and `%`.
- **Kylin** (`jdbc:kylin:`): marker `?`, **separator `;`**. Accepted keys: `username`, `password`,
  `ssl`. Whitelist: `username`, `password`.
- **ArrowFlightSQL** (`jdbc:arrow-flight-sql:`, `jdbc:arrow-flight:`): marker `?`, separator `&`.
  Accepted keys: `threadPoolSize`, `useEncryption`, `useSystemTrustStore`,
  `disableCertificateVerification`, `token`, `username`, `password`. Whitelist: `username`,
  `password`, `token`.
- **TDEngine** (`jdbc:taos:`, `jdbc:taos-rs:`): marker `?`, separator `&`. Accepted keys include
  `charset`, `locale`, `timezone`, `user`, `password`, `batchfetch`. Whitelist: `user`, `password`.
- **OTS** (`jdbc:ots:http:`, `jdbc:ots:https:`): marker `?`, separator `&`. Accepted keys include
  `enableRequestCompression`, `enableResponseCompression`, `maxConnections`, `user`, `password`.
  Whitelist: `user`, `password`.
- **ODPS** (`jdbc:odps:http:`, `jdbc:odps:https:`): marker `?`, separator `&`. Accepted keys include
  `charset`, `project`, `accessId`, `accessKey`, `logview`, `tunnelEndpoint`, `stsToken`. Whitelist:
  `accessId`, `accessKey`, `tunnelEndpoint`, `stsToken`, `logview`.

## Scheme safety and unsupported schemes

Some schemes are always rejected with `JdbcURLUnsafeException`, case-insensitively:
`jdbc:mysql:fabric:` (e.g. `jdbc:mysql:Fabric://...`) and any `jdbc:jcr:jndi:` URL (e.g.
`jdbc:jcr:jndi:...`, `jdbc:jcr:jndI:...`). A `null` URL is also unsafe. A URL whose scheme matches no
registered filter throws `JdbcURLNotSupportedException`.

## Custom filters

`registerFilter(Filter)` installs a caller-provided filter; for a given scheme, a later registration
overrides an earlier one. The `com.alibaba.seckit.jdbc.Filter` interface is:

```java
public interface Filter {
    java.util.Set<String> getAcceptedSchemes();
    java.util.Set<String> getAcceptedPropertyKeys();
    void setAcceptedPropertyKeys(java.util.Set<String> propertyKeys);
    void addAcceptedPropertyKey(String... keys);
    java.util.Set<String> getPropertyKeyWhiteList();
    void setPropertyKeyWhiteList(java.util.Set<String> propertyKeyWhiteList);
    void addPropertyKeyWhiteList(String... keys);
    boolean acceptURL(String url);
    UrlParser createUrlParser(String url) throws JdbcURLException;
    String filterProperties(String url) throws JdbcURLException;
    FilterResult filterPropertiesWithResult(String url) throws JdbcURLException;
    FilterResult checkAndFilterProperties(UrlParser parser);
}
```

Dispatch picks a registered filter by scheme: a filter whose `getAcceptedSchemes()` contains the
URL's scheme (the text up to the first `//`, lower-cased) handles that URL, and
`filterJdbcConnectionSource` returns that filter's `filterProperties(url)`. `UrlParser` is a small
interface (`String getInitialUrl()`, `void parse()`, `Map<String,String> getProperties()`); a custom
filter that overrides `filterProperties` need not use it. `FilterResult` has a
`FilterResult(String before)` constructor and a `setAfter(String)` setter.

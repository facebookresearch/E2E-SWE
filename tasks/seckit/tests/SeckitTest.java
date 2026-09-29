package wrg.hidden;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.alibaba.seckit.SecurityUtil;
import com.alibaba.seckit.jdbc.Filter;
import com.alibaba.seckit.jdbc.FilterResult;
import com.alibaba.seckit.jdbc.JdbcURLException;
import com.alibaba.seckit.jdbc.JdbcURLUnsafeException;
import com.alibaba.seckit.jdbc.UrlParser;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Pattern;
import org.junit.jupiter.api.Test;

/**
 * End-to-end contract tests for the seckit JDBC connection-string filtering subsystem, driven
 * entirely through the public {@link SecurityUtil} facade (filterJdbcConnectionSource /
 * filterJdbcConnectionSourceWithResult / registerFilter). Each test drives one realistic
 * per-dialect-family filtering workflow and asserts many exact-value contracts as a unit, so a
 * single behavioral regression fails the whole scenario.
 *
 * FAIRNESS -- parameter ordering. The reference re-serializes surviving connection parameters in
 * Java HashMap iteration order (deterministic for a fixed key set on a given JVM, but NOT something
 * a from-scratch implementation can be expected to reproduce). Where an output carries two or more
 * parameters, tests therefore assert the fixed scheme/host/database prefix EXACTLY and compare the
 * parameter tail as an unordered set (see {@link #assertParams}); single-parameter, zero-parameter
 * and structurally-ordered outputs (e.g. the Oracle DESCRIPTION tree, whose order is input-order
 * preserving) are asserted with exact string equality.
 */
class SeckitTest {

    /**
     * Assert that {@code actual} begins with the exact fixed prefix {@code prefixEnd} (scheme + host
     * [+ port][+ database] + the parameter marker) and that the remaining parameter tail -- split on
     * {@code sep} -- is exactly the given set of {@code key=value} tokens, order-independent. A
     * single trailing separator is tolerated.
     */
    private static void assertParams(final String actual, final String prefixEnd, final String sep,
            final String... params) {
        assertTrue(actual.startsWith(prefixEnd),
                "expected prefix <" + prefixEnd + "> but was <" + actual + ">");
        final String tail = actual.substring(prefixEnd.length());
        final Set<String> got = new LinkedHashSet<>();
        if (!tail.isEmpty()) {
            for (final String p : tail.split(Pattern.quote(sep), -1)) {
                if (!p.isEmpty()) {
                    got.add(p);
                }
            }
        }
        final Set<String> want = new HashSet<>(Arrays.asList(params));
        assertEquals(want, got, "parameter set mismatch for <" + actual + ">");
    }

    // ===================================================================
    // MySQL family: danger-parameter stripping + injected safety parameters
    // ===================================================================

    /**
     * The MySQL-family filter (mysql / mariadb / gbase / oceanbase / mysqlx and their failover and
     * +srv variants): strips non-accepted parameters, always injects the deserialization/local-infile
     * safety parameters, honours the per-key value patterns, and preserves failover host lists and
     * special protocols / database names.
     */
    @Test
    void filtersMySqlFamily() throws JdbcURLException {
        // Danger-param stripping + injected safety params. useUnicode/characterEncoding/
        // rewriteBatchedStatements/socketTimeout/serverTimezone accepted; sessionVariables
        // whitelisted; foo removed; ConnectTimeout removed (case-sensitive, accepted key is
        // connectTimeout); allow* + autoDeserialize forced to false.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql://localhost:3306/test?useUnicode=true&characterEncoding=UTF-8&foo=bar"
                        + "&allowLocalInfile=true&rewriteBatchedStatements=1&sessionVariables=abc"
                        + "&ConnectTimeout=1&socketTimeout=2&serverTimezone=Asia/Shanghai"),
                "jdbc:mysql://localhost:3306/test?", "&",
                "useUnicode=true", "characterEncoding=UTF-8", "rewriteBatchedStatements=1",
                "sessionVariables=abc", "socketTimeout=2", "serverTimezone=Asia/Shanghai",
                "allowLocalInfile=false", "allowLoadLocalInfile=false", "allowUrlInLocalInfile=false",
                "autoDeserialize=false");

        // mariadb behaves identically.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mariadb://localhost:3306/test?useUnicode=true&characterEncoding=UTF-8&foo=bar"
                        + "&allowLocalInfile=true"),
                "jdbc:mariadb://localhost:3306/test?", "&",
                "useUnicode=true", "characterEncoding=UTF-8", "allowLocalInfile=false",
                "allowLoadLocalInfile=false", "allowUrlInLocalInfile=false", "autoDeserialize=false");

        // oceanbase: allowLocalInfile IS injected; user whitelisted; sessionVariables value kept verbatim.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:oceanbase://localhost:13000/test?user=aaa&foo=bar&sessionVariables=foo=bar"
                        + "&allowLocalInfile=true"),
                "jdbc:oceanbase://localhost:13000/test?", "&",
                "sessionVariables=foo=bar", "user=aaa", "allowLocalInfile=false",
                "allowLoadLocalInfile=false", "allowUrlInLocalInfile=false", "autoDeserialize=false");

        // gbase: the ONLY family member that does NOT inject allowLocalInfile.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:gbase://localhost:13000/test?user=aaa&foo=bar&sessionVariables=foo=bar"
                        + "&allowLocalInfile=true"),
                "jdbc:gbase://localhost:13000/test?", "&",
                "sessionVariables=foo=bar", "user=aaa", "allowLoadLocalInfile=false",
                "allowUrlInLocalInfile=false", "autoDeserialize=false");
        assertFalse(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:gbase://localhost:13000/test?allowLocalInfile=true").contains("allowLocalInfile"));

        // enabledTLSProtocols value pattern: comma-list accepted, colon-bearing value rejected.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "mysqlx://localhost:3306/db?enabledTLSProtocols=TLSv1,TLSv1.1,TLSv1.2"),
                "mysqlx://localhost:3306/db?", "&",
                "enabledTLSProtocols=TLSv1,TLSv1.1,TLSv1.2", "allowLocalInfile=false",
                "allowLoadLocalInfile=false", "allowUrlInLocalInfile=false", "autoDeserialize=false");
        assertFalse(SecurityUtil.filterJdbcConnectionSource(
                "mysqlx://localhost:3306/db?enabledTLSProtocols=foo:bar").contains("enabledTLSProtocols"));

        // serverTimezone value pattern (mysql allows +, %, /); a ';' in the value fails it. The full
        // surviving set (the kept value plus every injected safety param) is asserted exactly.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql://localhost:3306/test?serverTimezone=GMT+8"),
                "jdbc:mysql://localhost:3306/test?", "&",
                "serverTimezone=GMT+8", "allowLocalInfile=false", "allowLoadLocalInfile=false",
                "allowUrlInLocalInfile=false", "autoDeserialize=false");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql://localhost:3306/test?serverTimezone=GMT%2B8"),
                "jdbc:mysql://localhost:3306/test?", "&",
                "serverTimezone=GMT%2B8", "allowLocalInfile=false", "allowLoadLocalInfile=false",
                "allowUrlInLocalInfile=false", "autoDeserialize=false");
        assertFalse(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql://localhost:3306/test?serverTimezone=GMT;8").contains("serverTimezone"));

        // Failover host lists and special protocols preserved; +srv and mysql2 accepted.
        assertTrue(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql://localhost:3306,example-domain.com:1234/test?user=zhangsan")
                .startsWith("jdbc:mysql://localhost:3306,example-domain.com:1234/test"));
        assertTrue(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql:loadbalance://localhost:3306,example-domain.com:1234/test?user=zhangsan")
                .startsWith("jdbc:mysql:loadbalance://localhost:3306,example-domain.com:1234/test"));
        assertTrue(SecurityUtil.filterJdbcConnectionSource("jdbc:mysql+srv://localhost:3306/db")
                .startsWith("jdbc:mysql+srv://localhost:3306/db"));
        assertTrue(SecurityUtil.filterJdbcConnectionSource("jdbc:mysql2://localhost:3306/db")
                .startsWith("jdbc:mysql2://localhost:3306/db"));

        // MySQL database names may contain $, Han script, space, '=' and '#'.
        assertTrue(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql://localhost:3307/中文$db?user=zhangsan&foo=bar")
                .startsWith("jdbc:mysql://localhost:3307/中文$db"));
        assertFalse(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql://localhost:3307/中文$db?user=zhangsan&foo=bar").contains("foo=bar"));
        assertTrue(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mysql://localhost:3307/this=is db#name")
                .startsWith("jdbc:mysql://localhost:3307/this=is db#name"));
    }

    // ===================================================================
    // PostgreSQL family: whitelist, value URL-encoding, dispatch aliases
    // ===================================================================

    /**
     * The PostgreSQL-family filter (postgresql / polardb / opengauss / kingbase8): accepted-key
     * filtering, URL-decode-on-parse then URL-encode-on-serialize of parameter values, the '@' and
     * IPv6 host/database forms.
     */
    @Test
    void filtersPostgresFamily() throws JdbcURLException {
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:postgresql://localhost:5432/test?useUnicode=true&stringtype=abc&socket_timeout=-1"
                        + "&foo=bar&user=postgres&password=postgres&socketTimeout=123"),
                "jdbc:postgresql://localhost:5432/test?", "&",
                "stringtype=abc", "socketTimeout=123", "user=postgres", "password=postgres");

        // polardb / opengauss / kingbase8 all dispatch to the Postgres filter.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:polardb://localhost:5432/test?stringtype=abc&socket_timeout=-1&user=postgres"),
                "jdbc:polardb://localhost:5432/test?", "&", "stringtype=abc", "user=postgres");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:opengauss://localhost:5432/test?stringtype=abc&socket_timeout=-1&user=postgres"),
                "jdbc:opengauss://localhost:5432/test?", "&", "stringtype=abc", "user=postgres");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:kingbase8://localhost:5432/test?stringtype=abc&foo=bar&user=postgres"),
                "jdbc:kingbase8://localhost:5432/test?", "&", "stringtype=abc", "user=postgres");

        // Value URL-encoding: the decoded conf:stsToken passes its pattern, then is re-encoded.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:postgresql://hgpostcn-xxxxxx.hologres.aliyuncs.com:80/dbname?preferQueryMode=simple"
                        + "&conf:stsToken=ZGNmdn%2BNnYmhAIy/QlYmFhZ3lobmptaw==&foo=bar&sslmode=true"),
                "jdbc:postgresql://hgpostcn-xxxxxx.hologres.aliyuncs.com:80/dbname?", "&",
                "preferQueryMode=simple", "conf:stsToken=ZGNmdn%2BNnYmhAIy%2FQlYmFhZ3lobmptaw%3D%3D",
                "sslmode=true");

        // IPv6 failover host list is preserved verbatim; '@' is allowed in the database name.
        assertEquals("jdbc:postgresql://[::1]:5432,localhost:5432/db",
                SecurityUtil.filterJdbcConnectionSource("jdbc:postgresql://[::1]:5432,localhost:5432/db"));
        assertTrue(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:postgresql://localhost:5432/test@aabbccdd?stringtype=abc&foo=bar&user=postgres")
                .startsWith("jdbc:postgresql://localhost:5432/test@aabbccdd?"));
    }

    // ===================================================================
    // SQL Server: the semicolon finite-state parser, brace escaping, throws
    // ===================================================================

    /**
     * The SQL Server semicolon parser: case-insensitive key matching, the {@code databaseName={...}}
     * brace-escaping rules, backslash instance names, Han-script values, and the unsafe inputs that
     * must be rejected with {@link JdbcURLUnsafeException}.
     */
    @Test
    void filtersSqlServerSemicolonParser() throws JdbcURLException {
        assertEquals("jdbc:sqlserver://localhost:1433;database=test",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost:1433;database=test;foo=bar"));
        assertEquals("jdbc:sqlserver://localhost\\instance;database=test",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost\\instance;database=test;foo=bar"));
        // Case-insensitive key matching and whitespace trimming around the value.
        assertEquals("jdbc:sqlserver://localhost:1433;DATABASENAME=test",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost:1433;DATABASENAME=test;foo=bar"));
        assertEquals("jdbc:sqlserver://localhost:1433;databaseName=test",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost:1433;databaseName = test ;foo=bar"));
        // Two accepted parameters -> order-independent.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:sqlserver://localhost:1433;databaseName=test;failOverPartner=1.1.1.1"),
                "jdbc:sqlserver://localhost:1433;", ";",
                "databaseName=test", "failOverPartner=1.1.1.1");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:sqlserver://localhost:1433;databaseName=中文数据库;database=中文;"),
                "jdbc:sqlserver://localhost:1433;", ";",
                "database=中文", "databaseName=中文数据库");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:sqlserver://localhost:1234;encrypt=false;language=us_english;loginTimeout=3600"
                        + ";socketTimeout=3600000;databaseName=BS3000+_000_2014"),
                "jdbc:sqlserver://localhost:1234;", ";",
                "databaseName=BS3000+_000_2014", "encrypt=false", "socketTimeout=3600000",
                "language=us_english", "loginTimeout=3600");

        // Brace-escaped database values: [..], { .. }, escaped }} , and parentheses.
        assertEquals("jdbc:sqlserver://localhost:1433;databaseName=[test space]",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost:1433;databaseName=[test space];"));
        assertEquals("jdbc:sqlserver://localhost:1433;databaseName={abc foobar }",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost:1433;databaseName= {abc foobar };"));
        assertEquals("jdbc:sqlserver://localhost:1433;databaseName={aaa}}b}",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost:1433;databaseName={aaa}}b};"));
        // A '{' nested inside a brace-quoted value is kept literally; '}}}' -> '}}' (escaped) + close.
        assertEquals("jdbc:sqlserver://localhost:1433;databaseName={abc{}}}",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost:1433;databaseName={abc{}}};"));
        assertEquals("jdbc:sqlserver://ip:1433;databaseName=dataphin(POC)",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://ip:1433;databaseName=dataphin(POC)"));
        // Instance name with no accepted parameters.
        assertEquals("jdbc:sqlserver://localhost\\instanceName:1433",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sqlserver://localhost\\instanceName:1433;foo=bar"));

        // Unsafe inputs: spaces in the server / instance name, and an unescaped brace mid-value.
        assertThrows(JdbcURLUnsafeException.class, () -> SecurityUtil.filterJdbcConnectionSource(
                "jdbc:sqlserver://xxxx abvc\\instanceName:1433;foo=bar"));
        assertThrows(JdbcURLUnsafeException.class, () -> SecurityUtil.filterJdbcConnectionSource(
                "jdbc:sqlserver://localhost\\xxx abc:1433;foo=bar"));
        assertThrows(JdbcURLUnsafeException.class, () -> SecurityUtil.filterJdbcConnectionSource(
                "jdbc:sqlserver://localhost:1433;databaseName=abc{foo};"));
    }

    // ===================================================================
    // Semicolon / colon separated dialects (DB2, Informix, NS, As400, SAP, Impala, Greenplum)
    // ===================================================================

    /**
     * The colon/semicolon-list dialects, exercising their distinct serialization shapes: DB2's
     * {@code /db:k=v;} (with a trailing ';') vs Informix's {@code /db:k=v} (no trailing), the
     * NetSuite/As400 {@code ;k=v} form, SAP's host that may contain ';', case-insensitive Greenplum,
     * and Impala's whitelist.
     */
    @Test
    void filtersSemicolonAndColonSeparatedDialects() throws JdbcURLException {
        // DB2: empty whitelist -> user/reconnect stripped; currentSchema kept; trailing ';' retained.
        assertEquals("jdbc:db2://localhost:50000/test", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:db2://localhost:50000/test:user=foo;reconnect=true;"));
        assertEquals("jdbc:db2://localhost:50000/test:currentSchema=abc;",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:db2://localhost:50000/test:currentSchema=abc;reconnect=true;"));
        // Informix: same colon form but NO trailing ';'.
        assertEquals("jdbc:informix-sqli://localhost:9088/test:INFORMIXSERVER=abc",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:informix-sqli://localhost:9088/test:INFORMIXSERVER=abc;user=foo"));
        // NetSuite: ';'-separated, Encrypted accepted.
        assertEquals("jdbc:ns://localhost:9088/test;Encrypted=true",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:ns://localhost:9088/test;Encrypted=true;foo=bar"));
        // As400: keys may contain spaces; multiple accepted params -> order-independent.
        assertEquals("jdbc:as400://localhost:1234/db", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:as400://localhost:1234/db;foo=bar"));
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:as400://localhost:1234/db;naming=xxx;errors=xxx;foo=bar"),
                "jdbc:as400://localhost:1234/db;", ";", "naming=xxx", "errors=xxx");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:as400://localhost:1234/db;block size=abc;date format=123;foo=bar"),
                "jdbc:as400://localhost:1234/db;", ";", "block size=abc", "date format=123");
        // SAP: empty whitelist strips user; host may carry ';failover:...'.
        assertEquals("jdbc:sap://localhost:3200/test?reconnect=true",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sap://localhost:3200/test?user=foo&reconnect=true"));
        assertEquals("jdbc:sap://localhost:3200;failover:1234/test?reconnect=true",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:sap://localhost:3200;failover:1234/test?user=foo&reconnect=true"));
        // Impala: UID/PWD whitelisted (value unchecked, '$' allowed); AuthMech/httpPath accepted.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:impala://node1.example.com:18000/default2;AuthMech=3;UID=cloudera$user;PWD=cloudera"),
                "jdbc:impala://node1.example.com:18000/default2;", ";",
                "AuthMech=3", "UID=cloudera$user", "PWD=cloudera");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:impala://node1.example.com:18000/default2;httpPath=/foo/bar;UID=user"),
                "jdbc:impala://node1.example.com:18000/default2;", ";", "UID=user", "httpPath=/foo/bar");
        // Greenplum: case-insensitive; InitializationString stripped; ServicePrincipalName whitelisted.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:pivotal:greenplum://127.0.0.1:5432;DatabaseName=abc"
                        + ";InitializationString=(command1;command2);LoginTimeout=2"),
                "jdbc:pivotal:greenplum://127.0.0.1:5432;", ";", "DatabaseName=abc", "LoginTimeout=2");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:pivotal:greenplum://server1:5432;DatabaseName=greenplumDB;AuthenticationMethod=kerberos"
                        + ";ServicePrincipalName=postgres/myserver.example.com@EXAMPLE.COM;"),
                "jdbc:pivotal:greenplum://server1:5432;", ";", "DatabaseName=greenplumDB",
                "AuthenticationMethod=kerberos",
                "ServicePrincipalName=postgres/myserver.example.com@EXAMPLE.COM");
        assertEquals("jdbc:pivotal:greenplum://127.0.0.1:5432",
                SecurityUtil.filterJdbcConnectionSource("jdbc:pivotal:greenplum://127.0.0.1:5432"));
    }

    // ===================================================================
    // Oracle: EZConnect + TNS DESCRIPTION tree pruning
    // ===================================================================

    /**
     * The Oracle thin driver: EZConnect {@code @host:port:sid} and {@code @tcp://...} forms, flat
     * {@code oracle.net.*} parameters, and DESCRIPTION-tree pruning (drop non-accepted nested keys
     * and non-TCP(S) protocols, strip incidental whitespace). TNS output order is input-order
     * preserving, so exact string equality is fair here.
     */
    @Test
    void filtersOracleTnsAndEzConnect() throws JdbcURLException {
        assertEquals("jdbc:oracle:thin:@127.0.0.1:1231:db_name-test",
                SecurityUtil.filterJdbcConnectionSource("jdbc:oracle:thin:@127.0.0.1:1231:db_name-test"));
        assertEquals("jdbc:oracle:thin:@127.0.0.1:1231:db_name-test",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:oracle:thin:@127.0.0.1:1231:db_name-test?foo=bar"));
        // Scheme normalised to lower case; the accepted flat parameter survives.
        assertEquals("jdbc:oracle:thin:@127.0.0.1:1231:db_name-test?oracle.net.CONNECT_TIMEOUT=123",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:Oracle:thin:@127.0.0.1:1231:db_name-test?oracle.net.CONNECT_TIMEOUT=123&foo=bar"));
        assertEquals("jdbc:oracle:thin:@tcp://mydbhost1,mydbhost2:1521/mydbservice",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:oracle:thin:@tcp://mydbhost1,mydbhost2:1521/mydbservice"
                                + "?wallet_location=/work/wallet&ssl_server_cert_dn=\"Server DN\""));

        // TNS: whitespace stripped, structure preserved.
        final String tns = "jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)  (HOST=mydbhost)"
                + "(PORT=1521)) (CONNECT_DATA=(SERVICE_NAME=mydbservice)))";
        assertEquals(tns.replace(" ", ""), SecurityUtil.filterJdbcConnectionSource(tns));

        // TNS pruning: FOO removed at both levels; the LDAP address is dropped (non-TCP protocol).
        assertEquals("jdbc:oracle:thin:@(DESCRIPTION=(LOAD_BALANCE=on)(ADDRESS_LIST=(ADDRESS=(PROTOCOL=TCP)"
                + "(HOST=host1)(PORT=1521))(ADDRESS=(PROTOCOL=TCPS)(HOST=host2)(PORT=5221))"
                + "(ADDRESS=(HOST=host3)(PORT=5221)))(CONNECT_DATA=(SERVICE_NAME=orcl)))",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:oracle:thin:@(DESCRIPTION= (LOAD_BALANCE=on) (FOO=bar) (ADDRESS_LIST="
                                + "(ADDRESS=(PROTOCOL=TCP)(HOST=host1) (PORT=1521)) "
                                + "(ADDRESS=(PROTOCOL=TCPS)(HOST=host2)(PORT=5221)) "
                                + "(ADDRESS=(PROTOCOL=LDAP)(HOST=host3)(PORT=5221))) "
                                + "(CONNECT_DATA=(SERVICE_NAME=orcl) (FOO=bar)))"));
        // A non-accepted wrapper around DESCRIPTION collapses the whole tree away.
        assertEquals("jdbc:oracle:thin:@", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:oracle:thin:@(FOO=(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)  (HOST=mydbhost)(PORT=1521))"
                        + " (CONNECT_DATA=(SERVICE_NAME=mydbservice))))"));
        // retry_count/retry_delay and the security(ssl_server_dn_match) subtree are pruned.
        assertEquals("jdbc:oracle:thin:@(description=(address=(protocol=tcps)(port=1521)"
                + "(host=111.222.123.123))(connect_data=(service_name=test.adb.oraclecloud.com)))",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:oracle:thin:@(description=(retry_count=20)(retry_delay=3)(address=(protocol=tcps)"
                                + "(port=1521)(host=111.222.123.123))(connect_data="
                                + "(service_name=test.adb.oraclecloud.com))(security=(ssl_server_dn_match=no)))"));
    }

    // ===================================================================
    // Property-list drivers (Lindorm, Phoenix thin, DM)
    // ===================================================================

    /**
     * The property-list drivers: Lindorm/Phoenix ({@code scheme:k=v;k=v}, no host, ';'-joined) and
     * DM ('&'-joined with attack values stripped). Whitelisted keys (url/user/password) bypass value
     * validation; non-accepted and pattern-failing values are dropped.
     */
    @Test
    void filtersPropertyListDrivers() throws JdbcURLException {
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:lindorm:table:url=https://www.aliyun.com/foo/bar;timeZone=Asia/Shanghai"
                        + ";serialization=protobuf"),
                "jdbc:lindorm:table:", ";",
                "url=https://www.aliyun.com/foo/bar", "timeZone=Asia/Shanghai", "serialization=protobuf");
        assertEquals("jdbc:lindorm:table:url=111", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:lindorm:table:url=111;httpclient_factory=aaa;factory=bbb;httpclient_impl=xx"
                        + ";principal=xxx;foo=bar"));
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:lindorm:tsdb:url=http://localhost:8080;user=$%^&*;password=xxxx;database=db_name"
                        + ";lindorm.tsdb.driver.socket.timeout=5000"),
                "jdbc:lindorm:tsdb:", ";",
                "url=http://localhost:8080", "user=$%^&*", "password=xxxx", "database=db_name",
                "lindorm.tsdb.driver.socket.timeout=5000");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:phoenix:thin:url=http://localhost:1234/db;serialization=PROTOBUF;foo=bar"),
                "jdbc:phoenix:thin:", ";", "url=http://localhost:1234/db", "serialization=PROTOBUF");

        // DM: '&'-joined; schema/appName accepted; log-injection style values stripped.
        assertEquals("jdbc:dm://localhost?schema=asdf",
                SecurityUtil.filterJdbcConnectionSource("jdbc:dm://localhost?schema=asdf&i134=asdfa"));
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:dm://localhost/asdfasdf?schema=asdf&i134=asdfa&appName=abc"),
                "jdbc:dm://localhost/asdfasdf?", "&", "schema=asdf", "appName=abc");
        assertEquals("jdbc:dm://logDir?SCHEMA=asdf", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:dm://logDir?logDir=(../../)&SCHEMA=asdf&LOGIN_MODE=(4&i134=asdfa)"));
    }

    // ===================================================================
    // Redshift (? -> ; conversion, encoding) and BigQuery (OAuthPvtKey guard, host validation)
    // ===================================================================

    /**
     * Redshift: case-insensitive keys, conversion of '?'-parameters to ';'-parameters, value
     * URL-encoding, and the iam/ non-iam forms. BigQuery: path-key filtering, host/port validation
     * (rejecting an empty host and an out-of-range port), and the OAuthPvtKey guard that keeps inline
     * JSON keys but strips file-path values (including '../' traversals).
     */
    @Test
    void filtersRedshiftAndBigQuery() throws JdbcURLException {
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:redshift://example.net:8443/dev?user=test&password=secret$#&SSL=true"),
                "jdbc:redshift://example.net:8443/dev;", ";",
                "password=secret%24%23", "user=test", "SSL=true");
        assertEquals("jdbc:redshift://example.net:8443/dev", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:redshift://example.net:8443/dev?sslFactory=com.example.Test"));
        assertEquals("jdbc:redshift:iam://example.net:8443/http/path;App_Name=abc",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:redshift:iam://example.net:8443/http/path;sslFactory=com.example.Test;App_Name=abc"));
        assertEquals("jdbc:redshift:iam://example.net:8443/http/path",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:redshift:iam://example.net:8443/http/path;ssl=abc$"));

        assertEquals("jdbc:bigquery://localhost",
                SecurityUtil.filterJdbcConnectionSource("jdbc:bigquery://localhost;foo=bar"));
        assertThrows(JdbcURLException.class,
                () -> SecurityUtil.filterJdbcConnectionSource("jdbc:bigquery://;foo=bar"));
        assertThrows(JdbcURLException.class,
                () -> SecurityUtil.filterJdbcConnectionSource("jdbc:bigquery://localhost:123456;foo=bar"));
        // LogPath stripped (not accepted).
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;ProjectId=MyBigQueryProject"
                        + ";OAuthType=1;LogPath=passwd"),
                "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;", ";",
                "OAuthType=1", "ProjectId=MyBigQueryProject");
        // ProjectId with '$' fails the value pattern and is stripped.
        assertEquals("jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;OAuthType=1;",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;ProjectId=$$MyBigQueryProject"
                                + ";OAuthType=1;"));
        // OAuthPvtKeyPath (a file path) is not an accepted key and is stripped.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;ProjectId=MyBigQueryProject"
                        + ";OAuthType=0;OAuthServiceAcctEmail=bqtest1@data-driver-testing.iam.gserviceaccount.com"
                        + ";OAuthPvtKeyPath=C:\\SecureFiles\\ServiceKeyFile.p12;"),
                "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;", ";",
                "OAuthType=0", "ProjectId=MyBigQueryProject",
                "OAuthServiceAcctEmail=bqtest1@data-driver-testing.iam.gserviceaccount.com");
        // OAuthPvtKey as an absolute path / '../' traversal is stripped despite being whitelisted.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;ProjectId=MyBigQueryProject"
                        + ";OAuthType=0;OAuthServiceAcctEmail=bqtest1@data-driver-testing.iam.gserviceaccount.com"
                        + ";OAuthPvtKey=foo/../../etc/passwd;"),
                "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;", ";",
                "OAuthType=0", "ProjectId=MyBigQueryProject",
                "OAuthServiceAcctEmail=bqtest1@data-driver-testing.iam.gserviceaccount.com");
        // An inline JSON OAuthPvtKey (starts with '{', no '../') is kept verbatim.
        final String pvtKey = "{  \"type\": \"service_account\",  \"project_id\": \"translation-123123123123\","
                + "  \"private_key_id\": \"0123456789abcdef0124dfdf\",  "
                + "\"private_key\": \"-----BEGIN RSA PRIVATE KEY-----\\n"
                + "xxxxxxxxx\\n"
                + "-----END RSA PRIVATE KEY-----\",  \"client_email\": "
                + "\"foobar@translation-123123123123.iam.gserviceaccount.com\",  "
                + "\"client_id\": \"1231231231231231231\",  \"auth_uri\": "
                + "\"https://accounts.google.com/o/oauth2/auth\",  "
                + "\"token_uri\": \"https://oauth2.googleapis.com/token\",  \"auth_provider_x509_cert_url\": "
                + "\"https://www.googleapis.com/oauth2/v1/certs\", "
                + " \"client_x509_cert_url\": \"https://www.googleapis.com/robot/v1/metadata/x509/"
                + "foobar%40translation-123123123123.iam.gserviceaccount.com\",  "
                + "\"universe_domain\": \"googleapis.com\"}";
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;ProjectId=MyBigQueryProject"
                        + ";OAuthType=0;OAuthServiceAcctEmail=bqtest1@data-driver-testing.iam.gserviceaccount.com"
                        + ";OAuthPvtKey=" + pvtKey),
                "jdbc:bigquery://https://www.googleapis.com/bigquery/v2:443;", ";",
                "OAuthType=0", "ProjectId=MyBigQueryProject",
                "OAuthServiceAcctEmail=bqtest1@data-driver-testing.iam.gserviceaccount.com",
                "OAuthPvtKey=" + pvtKey);
    }

    // ===================================================================
    // Userinfo drivers (Redis, MongoDB)
    // ===================================================================

    /**
     * Redis and MongoDB carry {@code user:pass@host} userinfo. Exercises userinfo passthrough, the
     * MongoDB '&|;' parameter separator and trailing-slash normalisation, whitelist handling of
     * authMechanismProperties, non-jdbc schemes, and rejection of malformed userinfo.
     */
    @Test
    void filtersUserinfoDrivers() throws JdbcURLException {
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:redis://localhost:7890?user=aaa&pass=bbb&password=ccc"),
                "jdbc:redis://localhost:7890?", "&", "password=ccc", "user=aaa");
        assertEquals("jdbc:redis://foo:bar@localhost?user=root", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:redis://foo:bar@localhost?aaa=bbb&user=root"));

        // MongoDB: '&' or ';' separate params; no database -> normalised trailing '/'.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mongodb://localhost?ssl=true;foo=bar&tls=true"),
                "jdbc:mongodb://localhost/?", "&", "tls=true", "ssl=true");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:mongodb://localhost/db?ssl=true&authMechanismProperties=foo:bar"),
                "jdbc:mongodb://localhost/db?", "&", "authMechanismProperties=foo:bar", "ssl=true");
        // Non-jdbc scheme + userinfo + failover host list, all preserved.
        assertEquals("mongodb://root:P%4033w04d@localhost,1.1.1.1:2377/db?ssl=true",
                SecurityUtil.filterJdbcConnectionSource(
                        "mongodb://root:P%4033w04d@localhost,1.1.1.1:2377/db?ssl=true"));
        assertEquals("mongodb://localhost,1.1.1.1:2377/?ssl=true", SecurityUtil.filterJdbcConnectionSource(
                "mongodb://localhost,1.1.1.1:2377/?ssl=true"));
        // Malformed userinfo is rejected.
        assertThrows(JdbcURLUnsafeException.class, () -> SecurityUtil.filterJdbcConnectionSource(
                "mongodb+srv://root:foobar:foo=bar@1.1.1.1/db"));
    }

    // ===================================================================
    // Hive family (Hive strips everything; Hive2 multi-section)
    // ===================================================================

    /**
     * Hive strips all connection parameters. Hive2 splits sessionVars ({@code ;}) / hiveConfs
     * ({@code ?}) / hiveVars ({@code #}), enforces its database-name pattern, applies the httpPath
     * value patterns, and accepts any {@code http.cookie.*} key.
     */
    @Test
    void filtersHiveFamily() throws JdbcURLException {
        assertEquals("jdbc:hive://localhost:8080/db",
                SecurityUtil.filterJdbcConnectionSource("jdbc:hive://localhost:8080/db?user=zhangsan"));
        assertEquals("jdbc:hive://localhost:8080",
                SecurityUtil.filterJdbcConnectionSource("jdbc:hive://localhost:8080/?user=zhangsan"));

        // Hive2 database-name pattern: '*' rejected, '$' accepted.
        assertThrows(JdbcURLUnsafeException.class, () -> SecurityUtil.filterJdbcConnectionSource(
                "jdbc:hive2://localhost:123/db*name;foo=bar"));
        assertEquals("jdbc:hive2://localhost:123/db$name", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:hive2://localhost:123/db$name;foo=bar"));
        // Only accepted sessionVars survive; query + fragment sections dropped.
        assertEquals("jdbc:hive2://localhost:123/db;retries=2", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:hive2://localhost:123/db;foo=bar;retries=2?foo=bar#f=b"));
        // Two whitelisted sessionVars -> order-independent (value pass$word kept verbatim).
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:hive2://localhost:123/db;user=user;password=pass$word?hive.reloadable.aux.jars.path=xxxx"),
                "jdbc:hive2://localhost:123/db;", ";", "user=user", "password=pass$word");
        // One parameter surviving in each of the three sections.
        assertEquals("jdbc:hive2://localhost:123/db;user=user1?user=user2#user=user3",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:hive2://localhost:123/db;user=user1?user=user2#user=user3"));

        // httpPath patterns + http.cookie.* prefix acceptance; case-sensitive httppath rejected.
        final String hp = SecurityUtil.filterJdbcConnectionSource(
                "jdbc:hive2://abcd.aliuyuncs.com/;transportMode=http;httpPath=http/path/foobar"
                        + ";http.cookie.sessionId=abcabcabc;hive.server2.thrift.http.path=/http/path/foobar"
                        + ";httppath=abc");
        assertTrue(hp.contains("transportMode=http"));
        assertTrue(hp.contains("httpPath=http/path/foobar"));
        assertTrue(hp.contains("http.cookie.sessionId=abcabcabc"));
        assertTrue(hp.contains("hive.server2.thrift.http.path=/http/path/foobar"));
        assertFalse(hp.contains("httppath=abc"));
    }

    // ===================================================================
    // Analytics/query-param dialects (ClickHouse, Vertica, Presto, Trino, Teradata)
    // ===================================================================

    /**
     * The query-parameter analytics dialects. ClickHouse (server_time_zone / socket_timeout value
     * patterns, failover endpoints), Vertica (injects DisableCopyLocal=true), Presto/Trino (http-path
     * databases, per-key patterns permitting ',', ';', '+', '/'), and Teradata (comma-separated,
     * '/'-marker property list).
     */
    @Test
    void filtersAnalyticsQueryDialects() throws JdbcURLException {
        assertEquals("jdbc:clickhouse://localhost:8123/test?socket_timeout=-1",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:clickhouse://localhost:8123/test?useUnicode=true&socket_timeout=-1&foo=bar"));
        assertEquals("jdbc:ch:http://server1.domain,server2.domain,server3.domain",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:ch:http://server1.domain,server2.domain,server3.domain"));
        assertEquals("jdbc:ch:http://endpoint1,server2.domain,server3.domain/db?server_time_zone=Asia/Shanghai",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:ch:http://endpoint1,server2.domain,server3.domain/db?server_time_zone=Asia/Shanghai"));

        // Vertica injects DisableCopyLocal=true; user/password whitelisted (value '123$$$' kept).
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:vertica://localhost/test?ssl=true&user=zhangsan&password=123$$$"),
                "jdbc:vertica://localhost/test?", "&",
                "password=123$$$", "DisableCopyLocal=true", "ssl=true", "user=zhangsan");

        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:presto://example.net:8080/hive/sales?user=test&password=secret&SSL=true"),
                "jdbc:presto://example.net:8080/hive/sales?", "&",
                "password=secret", "user=test", "SSL=true");
        assertEquals("jdbc:presto://example.net:8080/hive/sales?timeZoneId=Asia/ShangHai",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:presto://example.net:8080/hive/sales?timeZoneId=Asia/ShangHai"
                                + "&customHeaders=foo:bar;aaa:bbb"));
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:trino://example.net:8443/hive/sales?clientTags=abc,xyz&foo=bar"
                        + "&sessionProperties=abc:xyz;example.foo:bar&accessToken=foo+dsf="),
                "jdbc:trino://example.net:8443/hive/sales?", "&",
                "clientTags=abc,xyz", "accessToken=foo+dsf=", "sessionProperties=abc:xyz;example.foo:bar");

        // Teradata: '/'-marker, ','-separator; USER/ACCOUNT accepted, BROWSER/LOGDATA dropped;
        // PASSWORD whitelisted so its '^&()(' value is kept verbatim.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:teradata://localhost/USER=zhangsan,BROWSER=xxxx,ACCOUNT=xxxx"),
                "jdbc:teradata://localhost/", ",", "ACCOUNT=xxxx", "USER=zhangsan");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:teradata://localhost/PASSWORD=dsfm^&()(,LOGDATA=sdfasd&^(,ACCOUNT=xxxx"),
                "jdbc:teradata://localhost/", ",", "ACCOUNT=xxxx", "PASSWORD=dsfm^&()(");

        // Sybase: the scheme is followed DIRECTLY by the host (no '//'); PASSWORD whitelisted.
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:sybase:Tds:myserver:1234/mydatabase?LITERAL_PARAMS=true&PACKETSIZE=512"
                        + "&HOSTNAME=myhost&password=P$w$d"),
                "jdbc:sybase:Tds:myserver:1234/mydatabase?", "&",
                "LITERAL_PARAMS=true", "PACKETSIZE=512", "HOSTNAME=myhost", "password=P$w$d");
        assertEquals("jdbc:sybase:Tds:myserver:1234/mydatabase", SecurityUtil.filterJdbcConnectionSource(
                "jdbc:sybase:Tds:myserver:1234/mydatabase?SYBSOCKET_ FACTORY=com.example.Soket"));
    }

    // ===================================================================
    // Cloud / search / driver dialects (ES, OpenSearch, Kylin, ArrowFlight, TDEngine, OTS, ODPS)
    // ===================================================================

    /**
     * The remaining accepted-key-filtering dialects, exercising their connection-type prefixes and
     * separator variants: Elasticsearch/OpenSearch ({@code http://} connType, '/'-and-'%' databases),
     * Kylin ('?'-marker with ';'-separator), ArrowFlightSQL, TDEngine, OTS and ODPS.
     */
    @Test
    void filtersCloudAndSearchDialects() throws JdbcURLException {
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:es://http://server:3456/?timezone=UTC&page.size=250&debug.output=err.log"),
                "jdbc:es://http://server:3456/?", "&", "timezone=UTC", "page.size=250");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:elasticsearch://server:3456/?timezone=UTC&page.size=250&proxy.http=127.0.0.1:18808"),
                "jdbc:elasticsearch://server:3456/?", "&", "timezone=UTC", "page.size=250");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:opensearch://localhost:9200/x1231/%aax?user=addfo!!!__&password=P@ssw0rd"
                        + "&useSSL=false&a=bc"),
                "jdbc:opensearch://localhost:9200/x1231/%aax?", "&",
                "password=P@ssw0rd", "user=addfo!!!__", "useSSL=false");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:kylin://localhost:7070/kylin_project_name?ssl=true;username=aa;something=xxx"),
                "jdbc:kylin://localhost:7070/kylin_project_name?", ";", "ssl=true", "username=aa");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:arrow-flight-sql://localhost:1111/dd?threadPoolSize=11&trustStore=dddasf/"
                        + "&token=asdfl2.12390x.adsf"),
                "jdbc:arrow-flight-sql://localhost:1111/dd?", "&",
                "threadPoolSize=11", "token=asdfl2.12390x.adsf");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:taos://localhost:1111/dd?user=dddca_123!!&cfgdir=ddcs&charset=UTF-8"),
                "jdbc:taos://localhost:1111/dd?", "&", "charset=UTF-8", "user=dddca_123!!");
        assertParams(SecurityUtil.filterJdbcConnectionSource(
                "jdbc:ots:http://myinstance.cn-hangzhou.ots.aliyuncs.com/myinstance"
                        + "?enableRequestCompression=true&dd=false&user=LTAI..."),
                "jdbc:ots:http://myinstance.cn-hangzhou.ots.aliyuncs.com/myinstance?", "&",
                "enableRequestCompression=true", "user=LTAI...");
        assertEquals("jdbc:odps:http://localhost:8080?charset=UTF-8",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:odps:http://localhost:8080?charset=UTF-8&foobar=abc"));
        assertEquals("jdbc:odps:https://localhost:8080",
                SecurityUtil.filterJdbcConnectionSource(
                        "jdbc:odps:https://localhost:8080?aaa=xxxx&foobar=abc&dsfasf=sdfasfd"));
    }

    // ===================================================================
    // Scheme safety, FilterResult, and custom filter registration
    // ===================================================================

    /**
     * Rejection of known-unsafe schemes (mysql:fabric, jcr:jndi -- case-insensitive), the
     * FilterResult.isSafe() contract (false when anything was removed or injected, true when the URL
     * passes through unchanged), and pluggable filter registration via registerFilter.
     */
    @Test
    void enforcesSchemeSafetyFilterResultAndRegistration() throws JdbcURLException {
        assertThrows(JdbcURLUnsafeException.class,
                () -> SecurityUtil.filterJdbcConnectionSource("jdbc:mysql:Fabric://localhost/"));
        assertThrows(JdbcURLUnsafeException.class,
                () -> SecurityUtil.filterJdbcConnectionSource("jdbc:jcr:jndi:a?foo=bar"));
        assertThrows(JdbcURLUnsafeException.class,
                () -> SecurityUtil.filterJdbcConnectionSource("jdbc:jcr:jndI:a?foo=bar"));

        // isSafe() == false when a dangerous parameter was removed (or a safety param injected).
        final FilterResult unsafe = SecurityUtil.filterJdbcConnectionSourceWithResult(
                "jdbc:mysql://localhost:8080/?foo=bar");
        assertFalse(unsafe.isSafe());
        // isSafe() == true when nothing had to change.
        final FilterResult safe = SecurityUtil.filterJdbcConnectionSourceWithResult(
                "jdbc:hive://localhost:8080/db");
        assertTrue(safe.isSafe());

        // A custom filter registered for a novel scheme takes over that scheme.
        SecurityUtil.registerFilter(new CustomDbFilter());
        assertEquals("filtered-by-custom",
                SecurityUtil.filterJdbcConnectionSource("jdbc:customdb://host:1234/db?foo=bar"));
    }

    /** Minimal {@link Filter} implementation used to verify {@code registerFilter} dispatch. */
    private static final class CustomDbFilter implements Filter {
        private Set<String> acceptedPropertyKeys = new HashSet<>();
        private Set<String> propertyKeyWhiteList = new HashSet<>();

        @Override
        public Set<String> getAcceptedSchemes() {
            return new HashSet<>(Arrays.asList("jdbc:customdb:"));
        }

        @Override
        public Set<String> getAcceptedPropertyKeys() {
            return acceptedPropertyKeys;
        }

        @Override
        public void setAcceptedPropertyKeys(final Set<String> propertyKeys) {
            this.acceptedPropertyKeys = propertyKeys;
        }

        @Override
        public void addAcceptedPropertyKey(final String... keys) {
            this.acceptedPropertyKeys.addAll(Arrays.asList(keys));
        }

        @Override
        public Set<String> getPropertyKeyWhiteList() {
            return propertyKeyWhiteList;
        }

        @Override
        public void setPropertyKeyWhiteList(final Set<String> whiteList) {
            this.propertyKeyWhiteList = whiteList;
        }

        @Override
        public void addPropertyKeyWhiteList(final String... keys) {
            this.propertyKeyWhiteList.addAll(Arrays.asList(keys));
        }

        @Override
        public boolean acceptURL(final String url) {
            return false;
        }

        @Override
        public UrlParser createUrlParser(final String url) {
            return null;
        }

        @Override
        public String filterProperties(final String url) {
            return "filtered-by-custom";
        }

        @Override
        public FilterResult filterPropertiesWithResult(final String url) {
            final FilterResult result = new FilterResult(url);
            result.setAfter("filtered-by-custom");
            return result;
        }

        @Override
        public FilterResult checkAndFilterProperties(final UrlParser parser) {
            return new FilterResult("");
        }
    }
}

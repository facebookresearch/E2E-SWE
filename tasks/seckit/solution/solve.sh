#!/bin/bash
set -e

# Ground-truth solution for the `seckit` task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON for this one clone (git is pre-baked in the image). It places
# the REFERENCE JDBC connection-string filtering subsystem as the agent's deliverable and writes the
# offline build script. Pinned to a specific commit for reproducibility.
git clone https://github.com/alibaba/seckit.git /tmp/repo
cd /tmp/repo
git checkout 29cef38679c39ebc59e7fd49ac34d08a871a552f

# The agent's deliverable = the JDBC filtering subsystem (package com.alibaba.seckit.jdbc and its
# subpackages) plus a JDBC-scoped SecurityUtil facade. The SSRF and XXE subsystems are OUT OF SCOPE
# (see report.txt); the repo's real SecurityUtil imports those, so we substitute a facade that
# exposes exactly the three in-scope JDBC entry points with the identical delegating bodies.
mkdir -p /app/src/com/alibaba/seckit
cp -a /tmp/repo/src/main/java/com/alibaba/seckit/jdbc /app/src/com/alibaba/seckit/jdbc

cat > /app/src/com/alibaba/seckit/SecurityUtil.java <<'EOF'
package com.alibaba.seckit;

import com.alibaba.seckit.jdbc.Filter;
import com.alibaba.seckit.jdbc.FilterResult;
import com.alibaba.seckit.jdbc.JdbcTool;
import com.alibaba.seckit.jdbc.JdbcToolImpl;
import com.alibaba.seckit.jdbc.JdbcURLException;

public class SecurityUtil {

    private static final JdbcTool jdbcTool = new JdbcToolImpl();

    public static String filterJdbcConnectionSource(String url) throws JdbcURLException {
        return jdbcTool.filterConnectionSource(url);
    }

    public static FilterResult filterJdbcConnectionSourceWithResult(String url) throws JdbcURLException {
        return jdbcTool.filterConnectionSourceWithResult(url);
    }

    public static void registerFilter(Filter filter) {
        jdbcTool.registerFilter(filter);
    }
}
EOF

cd /app
rm -rf /tmp/repo

# setup.sh builds the library OFFLINE with plain javac against the baked lombok (annotation
# processor) + slf4j-api jars (/opt/seckit/libs). It is SOURCED (not executed) by the grading
# harness, so it must not call `exit`. This mirrors what the agent is expected to produce from
# instruction.md (an agent writing plain Java needs no jars at all; lombok/slf4j are only required
# by the lombok-annotated ground-truth reference).
cat > /app/setup.sh <<'EOF'
LOMBOK=$(ls /opt/seckit/libs/lombok-*.jar 2>/dev/null | head -1)
SLF4J=$(ls /opt/seckit/libs/slf4j-api-*.jar 2>/dev/null | head -1)
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -encoding UTF-8 -cp "$SLF4J:$LOMBOK" -d /app/out || return 1
EOF
chmod +x /app/setup.sh

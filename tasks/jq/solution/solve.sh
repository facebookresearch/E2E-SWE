#!/bin/bash
set -e

# Ground-truth solution for the jq processor task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON. The reference processor (jackson-jq, the real library this task
# replicates) is the "answer", so it is NOT baked into the image; this script fetches it + its runtime
# deps into /app/gt-lib and provides a thin JqEngine that wraps it (evaluate -> compact-JSON output
# stream, one value per line, or "ERROR"). The agent flow never runs this script, so the agent never
# has jackson-jq on its classpath.

mkdir -p /app/gt-lib
fetch() { # <group-path> <artifact> <version>
    local rel="$1/$2/$3/$2-$3.jar" out="/app/gt-lib/$2-$3.jar"
    for base in \
        "https://maven-central.storage-download.googleapis.com/maven2" \
        "https://repo1.maven.org/maven2" \
    ; do
        curl -fSL --connect-timeout 10 --retry 8 --retry-delay 6 --retry-all-errors -o "$out" "$base/$rel" && [ -s "$out" ] && return 0
    done
    return 1
}
fetch net/thisptr jackson-jq 1.6.2
fetch com/fasterxml/jackson/core jackson-databind 2.17.2
fetch com/fasterxml/jackson/core jackson-core 2.17.2
fetch com/fasterxml/jackson/core jackson-annotations 2.17.2
fetch org/jruby/joni joni 2.2.6
fetch org/jruby/jcodings jcodings 1.0.58
for j in jackson-jq-1.6.2 jackson-databind-2.17.2 jackson-core-2.17.2 jackson-annotations-2.17.2 joni-2.2.6 jcodings-1.0.58; do
    test -s /app/gt-lib/$j.jar
done

# The reference JqEngine: jackson-jq as a jq 1.6 processor. Contract == the agent's:
# evaluate(program, inputJson) -> compact-JSON output stream (one value per line), or "ERROR" on error.
mkdir -p /app/src/com/wrg/jq
cat > /app/src/com/wrg/jq/JqEngine.java <<'JAVA'
package com.wrg.jq;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import net.thisptr.jackson.jq.JsonQuery;
import net.thisptr.jackson.jq.Scope;
import net.thisptr.jackson.jq.Versions;
import net.thisptr.jackson.jq.BuiltinFunctionLoader;
import net.thisptr.jackson.jq.module.loaders.BuiltinModuleLoader;

public class JqEngine {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Scope ROOT;
    static {
        Scope s = Scope.newEmptyScope();
        BuiltinFunctionLoader.getInstance().loadFunctions(Versions.JQ_1_6, s);
        s.setModuleLoader(BuiltinModuleLoader.getInstance());
        ROOT = s;
    }

    public String evaluate(String program, String inputJson) {
        try {
            JsonNode in = MAPPER.readTree(inputJson);
            JsonQuery q = JsonQuery.compile(program, Versions.JQ_1_6);
            final StringBuilder sb = new StringBuilder();
            final int[] count = {0};
            q.apply(Scope.newChildScope(ROOT), in, (JsonNode n) -> {
                if (count[0] > 0) sb.append('\n');
                try { sb.append(n == null ? "null" : MAPPER.writeValueAsString(n)); }
                catch (Exception e) { throw new RuntimeException(e); }
                count[0]++;
                if (count[0] > 200000 || sb.length() > 8000000) throw new RuntimeException("cap");
            });
            return sb.toString();
        } catch (Throwable t) {
            return "ERROR";
        }
    }
}
JAVA

# setup.sh compiles the reference engine OFFLINE against the fetched jars.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -encoding UTF-8 -cp "/app/gt-lib/*" -d /app/out
EOF

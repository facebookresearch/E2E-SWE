#!/bin/bash
set -e

# Ground-truth solution for the Prolog processor task. Runs only during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON. The reference engine (Projog, the real library this task
# replicates) is the "answer", so it is NOT baked into the image; this script fetches it into
# /app/gt-lib and provides a thin PrologEngine that wraps it (solve -> canonical solution stream, or
# "ERROR"). The agent flow never runs this script, so the agent never has Projog on its classpath.

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
fetch org/projog projog-core 0.11.0
fetch org/projog projog-clp 0.3.0     # projog-core references CLP classes at bootstrap
test -s /app/gt-lib/projog-core-0.11.0.jar && test -s /app/gt-lib/projog-clp-0.3.0.jar

# The reference PrologEngine: Projog. Contract == the agent's: solve(program, query) -> canonical
# solution stream (one solution per line; "true"/"false"; or "ERROR").
mkdir -p /app/src/com/wrg/prolog
cat > /app/src/com/wrg/prolog/PrologEngine.java <<'JAVA'
package com.wrg.prolog;

import java.io.StringReader;
import java.util.*;
import org.projog.api.Projog;
import org.projog.api.QueryResult;

public class PrologEngine {
    public String solve(String program, String query) {
        try {
            Projog p = new Projog();
            p.consultReader(new StringReader(program));
            String q = query.trim();
            if (!q.endsWith(".")) q = q + ".";
            QueryResult r = p.executeQuery(q);
            List<String> vars = new ArrayList<>(r.getVariableIds());
            Collections.sort(vars);
            StringBuilder sb = new StringBuilder();
            int n = 0;
            while (r.next()) {
                if (n > 0) sb.append('\n');
                if (vars.isEmpty()) {
                    sb.append("true");
                } else {
                    for (int i = 0; i < vars.size(); i++) {
                        if (i > 0) sb.append(", ");
                        sb.append(vars.get(i)).append("=").append(p.formatTerm(r.getTerm(vars.get(i))));
                    }
                }
                if (++n > 10000) break;
            }
            if (n == 0) return "false";
            return sb.toString();
        } catch (Throwable e) {
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

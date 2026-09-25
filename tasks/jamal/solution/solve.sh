#!/bin/bash
set -e

git clone https://github.com/verhas/jamal.git /tmp/repo
cd /tmp/repo
git checkout 406b70974c783eb54e2ba3bd1944c18bfb0801ff

# Copy four modules' source + resources into /app
mkdir -p /app/src
cp -a /tmp/repo/jamal-api/src/main/java/. /app/src/
cp -a /tmp/repo/jamal-tools/src/main/java/. /app/src/
cp -a /tmp/repo/jamal-engine/src/main/java/. /app/src/
cp -a /tmp/repo/jamal-core/src/main/java/. /app/src/
cd /app
rm -rf /tmp/repo

# Stub external dependency (Levenshtein)
mkdir -p /app/src/javax0/levenshtein
cat > /app/src/javax0/levenshtein/Levenshtein.java << 'LEV'
package javax0.levenshtein;
public class Levenshtein {
    public static int distance(String a, String b) {
        int[][] dp = new int[a.length()+1][b.length()+1];
        for (int i = 0; i <= a.length(); i++) dp[i][0] = i;
        for (int j = 0; j <= b.length(); j++) dp[0][j] = j;
        for (int i = 1; i <= a.length(); i++)
            for (int j = 1; j <= b.length(); j++)
                dp[i][j] = Math.min(dp[i-1][j]+1, Math.min(dp[i][j-1]+1, dp[i-1][j-1]+(a.charAt(i-1)==b.charAt(j-1)?0:1)));
        return dp[a.length()][b.length()];
    }
}
LEV

# setup.sh compiles the Java source offline + copies SPI resources
cat > ./setup.sh << 'SETUP'
#!/bin/bash
mkdir -p /app/out
find /app/src -name "module-info.java" -delete 2>/dev/null
find /app/src -name "*.java" > /tmp/sources.txt
javac -d /app/out @/tmp/sources.txt 2>/dev/null || true
# Copy META-INF/services for SPI macro discovery
mkdir -p /app/out/META-INF/services
echo "javax0.jamal.builtins.Define
javax0.jamal.builtins.Comment
javax0.jamal.builtins.Block
javax0.jamal.builtins.Import
javax0.jamal.builtins.Include
javax0.jamal.builtins.Env
javax0.jamal.builtins.Export
javax0.jamal.builtins.Sep
javax0.jamal.builtins.Eval
javax0.jamal.builtins.Begin
javax0.jamal.builtins.End
javax0.jamal.builtins.For
javax0.jamal.builtins.If
javax0.jamal.builtins.Use
javax0.jamal.builtins.Options
javax0.jamal.builtins.Ident
javax0.jamal.builtins.Try
javax0.jamal.builtins.Escape
javax0.jamal.builtins.Require
javax0.jamal.builtins.Undefine
javax0.jamal.builtins.Defer
javax0.jamal.builtins.Macro
javax0.jamal.builtins.Catch
javax0.jamal.builtins.Error" > /app/out/META-INF/services/javax0.jamal.api.Macro
SETUP

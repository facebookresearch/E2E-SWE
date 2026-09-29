#!/bin/bash
set -e

# Ground-truth solution for the quickfixj task. Runs during `--mode=evaluate_gt`, in the
# Container A that keeps internet ON (git clone below needs it). The clone from github is
# the ONLY runtime network dependency; Maven codegen is replaced by a small in-repo Python
# generator that reads the baked-in FIX XML dictionaries.
#
# Steps:
#   1. Clone quickfixj and pin the target tag.
#   2. Copy quickfixj-base's hand-written sources.
#   3. Copy the subset of quickfixj-core we need (spec §7 session layer).
#   4. Generate the quickfix.field.* classes with generate_fields.py from the FIX
#      dictionaries already baked at /app/dictionaries/ — replaces `mvn install` codegen.
#   5. Stub quickfix.mina.SessionConnector (referenced by EventHandlingStrategy but never
#      called in this scope).
#   6. Patch Session's package-private constructor to public (spec calls for direct
#      instantiation from user code / tests).
#   7. Rename package quickfix -> io.fix everywhere.
#   8. Apply four API adaptations that align the reference to the io.fix spec
#      (single-arg validate, 3-arg Message parse, static dual-dict validate, CharsetSupport shim).
#   9. Write the offline plain-javac setup.sh that grading (Container B) will run.
#

# --- 1. Clone -------------------------------------------------------------------------------
git clone https://github.com/quickfix-j/quickfixj.git /tmp/repo
cd /tmp/repo
git checkout QFJ_RELEASE_3_0_1

# --- 2. Base sources (hand-written codec + validator + FieldMap + etc.) ---------------------
mkdir -p /app/src/quickfix
cp -R /tmp/repo/quickfixj-base/src/main/java/quickfix/. /app/src/quickfix/
cp -R /tmp/repo/quickfixj-base/src/main/java/org        /app/src/org  # org.quickfixj utils, kept as-is

# --- 3. Core session-layer subset -----------------------------------------------------------
CORE=/tmp/repo/quickfixj-core/src/main/java/quickfix
for f in \
    Session LogUtil SessionException NoTagValue MessageSessionUtils ApplicationExtended \
    SessionState Log LogFactory MessageStore MessageStoreFactory MessageQueue MessageQueueFactory \
    Application Responder MemoryStore MemoryStoreFactory InMemoryMessageQueue \
    InMemoryMessageQueueFactory RejectLogon \
    Connector Initiator SessionFactory DefaultSessionFactory \
    SessionSchedule DefaultSessionSchedule SessionScheduleFactory DefaultSessionScheduleFactory \
    SessionStateListener SessionNotFound ListenerSupport \
    DataDictionaryProvider DefaultDataDictionaryProvider \
    MessageFactory DefaultMessageFactory SessionSettings MessageCracker \
    AbstractLog LocationAwareLogFactory \
    ScreenLog ScreenLogFactory SLF4JLog SLF4JLogFactory; do
    [ -f "$CORE/$f.java" ] && cp "$CORE/$f.java" /app/src/quickfix/
done

# --- 4. Generate quickfix.field.* from the baked-in FIX dictionaries ------------------------
# `--only` is derived from what our shipped CORE actually imports (grep for imports); this
# keeps generation to the ~50 field classes we compile against, rather than emitting the
# full 900+ of the reference codegen output.
NEEDED=$(grep -rhoE 'import quickfix\.field\.[A-Z][A-Za-z]+' /app/src/quickfix/*.java \
    | sort -u | sed 's/import quickfix.field.//;s/;$//')
python3 "$(dirname "$0")/generate_fields.py" \
    --xml /app/dictionaries/FIX44.xml \
    --xml /app/dictionaries/FIXT11.xml \
    --xml /app/dictionaries/FIX50SP2.xml \
    --out /app/src/quickfix/field \
    --only "$NEEDED"

# --- 5. Stub quickfix.mina.SessionConnector -------------------------------------------------
mkdir -p /app/src/quickfix/mina
cp "$CORE/mina/EventHandlingStrategy.java" /app/src/quickfix/mina/
cat > /app/src/quickfix/mina/SessionConnector.java <<'JAVA'
package quickfix.mina;
/** Stub of quickfix.mina.SessionConnector — the transport-layer connector class that pulls in
 *  Apache Mina at runtime. Kept as a marker interface here because the io.fix scope excludes
 *  the network transport; Session references it via EventHandlingStrategy.getSessionConnector()
 *  which is never called in this test scope. */
public interface SessionConnector {}
JAVA

# --- 6. Public Session constructor ----------------------------------------------------------
perl -i -pe 's/^(    )(Session\(Application application, MessageStoreFactory messageStoreFactory, SessionID sessionID,)/\1public \2/' /app/src/quickfix/Session.java

# --- 7. Package rename quickfix -> io.fix ---------------------------------------------------
( cd /app/src && mkdir -p io && mv quickfix io/fix )
find /app/src/io/fix -name '*.java' -print0 | xargs -0 perl -i -pe 's/\bquickfix\b/io.fix/g'

# --- 8. API adaptations to align the reference with the io.fix spec -------------------------
# (a0) 4-arg Session convenience constructor. Spec §5 exposes only the minimal user-facing
#      ctor (Application, MessageStoreFactory, SessionID, int heartbeatInterval); the reference
#      keeps its full 9-arg form for internal use and this shim populates the plumbing args
#      (DDP, ValidationSettings, SessionSchedule=null, LogFactory, MessageFactory) with defaults.
#      A private NoOpLogFactory (below) silences all Log callbacks so the harness's stdout
#      isn't polluted by session-level errors (which would break the CTRF JSONL parser).
cat > /app/src/io/fix/NoOpLogFactory.java <<'JAVA'
package io.fix;
/** Package-private silent LogFactory used by Session's 4-arg convenience constructor.
 *  Every callback is a no-op — no stdout/stderr writes at any log level. */
final class NoOpLogFactory implements LogFactory {
    public Log create(SessionID id) { return NOOP; }
    public Log create(SessionID id, String callerFQCN) { return NOOP; }
    private static final Log NOOP = new Log() {
        public void clear() {}
        public void onIncoming(String message) {}
        public void onOutgoing(String message) {}
        public void onEvent(String text) {}
        public void onErrorEvent(String text) {}
    };
}
JAVA
perl -0777 -pi -e 's|(    public Session\(Application application, MessageStoreFactory messageStoreFactory, SessionID sessionID,)|    public Session(Application application, MessageStoreFactory messageStoreFactory, SessionID sessionID, int heartbeatInterval) {\n        this(application, messageStoreFactory, sessionID, new DefaultDataDictionaryProvider(), new ValidationSettings(), null, new NoOpLogFactory(), new DefaultMessageFactory(), heartbeatInterval);\n    }\n\n$1|' /app/src/io/fix/Session.java
# (a) Single-arg DataDictionary.validate(Message).
perl -0777 -pi -e 's/(public void validate\(Message message, ValidationSettings settings\))/public void validate(Message message) throws IncorrectTagValue, FieldNotFound, IncorrectDataFormat {\n        validate(message, false, new ValidationSettings());\n    }\n\n    $1/' /app/src/io/fix/DataDictionary.java
# (b) 3-arg Message(String, DataDictionary, DataDictionary) parse constructor for FIXT.1.1 dual-dict.
perl -0777 -pi -e 's/(public Message\(String string, DataDictionary sessionDictionary, DataDictionary applicationDictionary, ValidationSettings validationSettings, boolean validate\) throws InvalidMessage \{\n        initializeHeader\(\);\n        fromString\(string, sessionDictionary, applicationDictionary, validationSettings, validate, true\);\n    \})/$1\n\n    public Message(String string, DataDictionary sessionDictionary, DataDictionary applicationDictionary) throws InvalidMessage {\n        initializeHeader();\n        fromString(string, sessionDictionary, applicationDictionary, new ValidationSettings(), true, true);\n    }/' /app/src/io/fix/Message.java
# (c) Static DataDictionary.validate(Message, DataDictionary, DataDictionary) dual-dict validation.
perl -0777 -pi -e 's/(public void validate\(Message message, ValidationSettings settings\))/public static void validate(Message message, DataDictionary sessionDictionary, DataDictionary applicationDictionary) throws IncorrectTagValue, FieldNotFound, IncorrectDataFormat {\n        validate(message, sessionDictionary, applicationDictionary, new ValidationSettings());\n    }\n\n    $1/' /app/src/io/fix/DataDictionary.java
# (d) io.fix.CharsetSupport shim (spec API is io.fix.*; engine helper lives at org.quickfixj.CharsetSupport, un-renamed).
cat > /app/src/io/fix/CharsetSupport.java <<'JAVA'
package io.fix;

import java.io.UnsupportedEncodingException;

public final class CharsetSupport {
    private CharsetSupport() {}
    public static void setCharset(String charset) throws UnsupportedEncodingException {
        org.quickfixj.CharsetSupport.setCharset(charset);
    }
    public static String getCharset() { return org.quickfixj.CharsetSupport.getCharset(); }
    public static void setDefaultCharset() throws UnsupportedEncodingException {
        org.quickfixj.CharsetSupport.setDefaultCharset();
    }
}
JAVA

cd /app
rm -rf /tmp/repo

# --- 9. Offline build script (Container B / grading, or agent's own container) --------------
# Plain javac; no `set -e` so a compile failure cannot abort the (no-set-e) test.sh that sources it.
cat > /app/setup.sh <<'EOF'
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -cp "/opt/deps/*" -d /app/out
EOF

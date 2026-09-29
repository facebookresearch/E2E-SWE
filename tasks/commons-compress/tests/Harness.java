import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Grading harness for the commons-compress replication task. Loads the agent's
 *  com.wrg.compress.Archives and runs each baked case (cases.dat, length-prefixed:
 *  op, arg, input, expected). Ops: list|detect|decompress|compress-rt|write-rt|list-error|
 *  decompress-error. One case = one CTRF entry; per-case daemon-thread timeout + overall budget. */
public class Harness {
    static Class<?> cls; static Constructor<?> ctor;
    static Method mList, mDetect, mDecompress, mCompress, mWrite;

    public static void main(String[] args) throws Exception {
        String casesPath = args[0], outPath = args[1];
        long timeoutMs = args.length > 2 ? Long.parseLong(args[2]) : 10000;
        long budgetMs = args.length > 3 ? Long.parseLong(args[3]) : 1500000L;
        long deadline = System.nanoTime() + budgetMs * 1_000_000L;

        cls = Class.forName("com.wrg.compress.Archives");
        ctor = cls.getDeclaredConstructor();
        mList = cls.getMethod("list", String.class, byte[].class);
        mDetect = cls.getMethod("detect", byte[].class);
        mDecompress = cls.getMethod("decompress", String.class, byte[].class);
        mCompress = cls.getMethod("compress", String.class, byte[].class);
        mWrite = cls.getMethod("write", String.class, String.class);

        final AtomicInteger tnum = new AtomicInteger();
        ExecutorService exec = Executors.newCachedThreadPool(r -> {
            Thread t = new Thread(r, "w-" + tnum.incrementAndGet()); t.setDaemon(true); return t; });

        BufferedInputStream in = new BufferedInputStream(new FileInputStream(casesPath));
        int n = 0, budgetSkipped = 0;
        try (PrintWriter out = new PrintWriter(new OutputStreamWriter(new FileOutputStream(outPath), StandardCharsets.UTF_8), true)) {
            while (true) {
                int opLen = readIntLine(in); if (opLen == Integer.MIN_VALUE) break;
                final String op = new String(readBytes(in, opLen), StandardCharsets.US_ASCII);
                final String arg = new String(readBytes(in, readIntLine(in)), StandardCharsets.US_ASCII);
                final byte[] input = readBytes(in, readIntLine(in));
                final byte[] expected = readBytes(in, readIntLine(in));
                n++;
                if (System.nanoTime() > deadline) { budgetSkipped++; continue; }
                final String name = "case-" + n + "-" + op + "-" + arg;
                boolean ok = false; String msg = "";
                Future<byte[]> fut = exec.submit(() -> run(op, arg, input));
                try {
                    byte[] got = fut.get(timeoutMs, TimeUnit.MILLISECONDS);
                    ok = Arrays.equals(expected, got);
                    if (!ok) msg = "op=" + op + " arg=" + arg + " expLen=" + expected.length + " gotLen=" + (got==null?-1:got.length)
                            + " exp=" + brief(expected) + " got=" + (got==null?"null":brief(got));
                } catch (TimeoutException te) { fut.cancel(true); msg = "timed out";
                } catch (Throwable e) { Throwable c = (e instanceof ExecutionException && e.getCause()!=null)? e.getCause(): e;
                    msg = "threw " + c.getClass().getSimpleName() + ": " + c.getMessage(); }
                out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"" + (ok?"passed":"failed")
                        + "\",\"message\":\"" + esc(msg.length()>220?msg.substring(0,220):msg) + "\"}");
            }
        }
        exec.shutdownNow();
        if (budgetSkipped > 0) System.err.println("budget exceeded; " + budgetSkipped + " unrun");
    }

    /** Compute the agent's result bytes for a case. */
    static byte[] run(String op, String arg, byte[] input) throws Exception {
        Object A = ctor.newInstance();
        switch (op) {
            // list/decompress error-tolerant: a thrown exception -> "ERROR" sentinel (matches capture).
            case "list": try { return str((String) mList.invoke(A, arg, input)); }
                         catch (Throwable t) { return str("ERROR"); }
            case "decompress": try { return (byte[]) mDecompress.invoke(A, arg, input); }
                               catch (Throwable t) { return str("ERROR"); }
            case "detect": return str((String) mDetect.invoke(A, input));
            case "compress-rt": {
                byte[] comp = (byte[]) mCompress.invoke(A, arg, input);
                return (byte[]) mDecompress.invoke(A, arg, comp);
            }
            case "write-rt": {
                byte[] arc = (byte[]) mWrite.invoke(A, arg, new String(input, StandardCharsets.UTF_8));
                return str((String) mList.invoke(A, arg, arc));
            }
        }
        throw new IllegalArgumentException(op);
    }

    static byte[] str(String s) { return s.getBytes(StandardCharsets.UTF_8); }
    static String brief(byte[] b) { String s = new String(b, StandardCharsets.UTF_8);
        s = s.replace("\n","\\n").replace("\t"," "); return s.length()>80? s.substring(0,80)+"..." : s; }
    static int readIntLine(InputStream in) throws IOException { int c=in.read(); if(c==-1) return Integer.MIN_VALUE;
        StringBuilder b=new StringBuilder(); while(c!=-1&&c!='\n'){b.append((char)c);c=in.read();} return Integer.parseInt(b.toString().trim()); }
    static byte[] readBytes(InputStream in,int nn) throws IOException { byte[] b=new byte[nn]; int off=0,r;
        while(off<nn){r=in.read(b,off,nn-off); if(r==-1) throw new EOFException(); off+=r;} return b; }
    static String esc(String s){ StringBuilder b=new StringBuilder(); for(int i=0;i<s.length();i++){char c=s.charAt(i);
        switch(c){case '"':b.append("\\\"");break;case '\\':b.append("\\\\");break;case '\n':b.append("\\n");break;
        case '\r':b.append("\\r");break;case '\t':b.append("\\t");break;
        default: if(c<0x20||c>0x7E) b.append(String.format("\\u%04x",(int)c)); else b.append(c);}} return b.toString(); }
}

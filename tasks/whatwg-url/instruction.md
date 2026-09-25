# Implement a WHATWG URL parser

## What you are building

You are implementing a **URL parser** that follows the **WHATWG URL Standard** — the same algorithm
web browsers use. URLs look simple, but the standard is precise and full of interacting rules and
edge cases, including which inputs are simply **invalid** and must be rejected. The difficulty is not
"split a string on `/` and `:`" — it is reproducing the **exact** behavior the standard defines.

Your program reads one URL and prints its parsed components, or reports that the URL is invalid.

## Input / output contract

- The URL **input** is given on **standard input** as raw bytes — read all of stdin, and treat it
  exactly as given (do not trim or add whitespace/newlines; the input may itself contain spaces, tabs,
  or newlines that the standard says to handle).
- An optional **base URL** is passed as the **first command-line argument** (`argv[1]`). If present,
  parse the input *relative to* this base, exactly as the standard's parser does with a base URL. If
  there is no argument, there is no base.
- If the input parses to a valid URL, print a single **JSON object** with the URL's components (see
  below) to **standard output** and exit with status **0**.
- If the input is **not** a valid URL (or a base is given but is itself not a valid URL), exit with a
  **non-zero** status. Output is ignored in that case.

## The component fields (your JSON must contain exactly these keys)

Emit a JSON object with these ten string fields, holding the standard's serialized values:

| field      | what it is                          | note |
|------------|-------------------------------------|------|
| `href`     | the whole URL, serialized           | the normalized URL string |
| `protocol` | the scheme                          | includes the trailing `:` (e.g. `"http:"`) |
| `username` | the username                        | `""` if none |
| `password` | the password                        | `""` if none |
| `host`     | host **and** port                   | e.g. `"example.com:8080"`; `""` if none |
| `hostname` | host without port                   | `""` if none |
| `port`     | the port                            | `""` when absent or equal to the scheme's default |
| `pathname` | the path                            | e.g. `"/a/b"` |
| `search`   | the query                           | includes the leading `?` when non-empty, else `""` |
| `hash`     | the fragment                        | includes the leading `#` when non-empty, else `""` |

For example, the input `http://example.com/foo?bar#baz` (no base) parses to:

```json
{"href":"http://example.com/foo?bar#baz","protocol":"http:","username":"","password":"",
 "host":"example.com","hostname":"example.com","port":"","pathname":"/foo","search":"?bar","hash":"#baz"}
```

(JSON formatting — whitespace and key order — does not matter; the grader compares the field values.)

## The specification is the contract

Implement the WHATWG URL Standard. The **full standard is available on disk at
`/opt/whatwg-url/url-spec.txt`** — read it directly for the exact rules (it is also published at
<https://url.spec.whatwg.org/>). It is the authoritative
definition of how a URL is parsed (with or without a base URL) and of which inputs are failures. Read
it for the exact rules. Your parser is graded by feeding it many `(input, base)` cases from the
standard's own conformance test data and checking that valid URLs produce the right component values
and invalid URLs are rejected.

### Grading clarifications

Two points refine the contract for this task. Where they differ from `/opt/whatwg-url/url-spec.txt`,
**these take precedence** (the grading corpus follows them):

- **Internationalized (non-ASCII) hosts are out of scope.** You do **not** need to implement host
  *domain-to-ASCII* — i.e. IDNA / Unicode ToASCII / Punycode (`xn--`) encoding, decoding, or
  validation, and the associated Unicode mapping/NFC tables. The grader does not test URLs whose
  host contains non-ASCII characters or a Punycode (`xn--`) label, so a plain standard-library
  implementation is sufficient. Handle only ASCII domain hosts, IPv4, and IPv6 literals. (Opaque
  hosts of non-special schemes are still percent-encoded exactly as the standard describes — that
  is not IDNA.)

- **`^` (U+005E) is excluded from the path percent-encode set.** Do not percent-encode `^` in a
  URL path — keep it literal (e.g. the path `/a^b` serializes with a literal `^`, not `%5E`). The
  baked `url-spec.txt` lists `^` in the path percent-encode set, but for this task it is excluded,
  matching the conformance corpus. **This exclusion applies to the URL path only — it does not
  cascade to the other percent-encode sets that `url-spec.txt` defines in terms of the path set.**
  In particular, the **userinfo** percent-encode set (used to serialize `username` and `password`)
  still percent-encodes `^`: a caret in a username or password serializes as `%5E` (e.g. the
  username `a^b` becomes `a%5Eb`). Only in the path is `^` kept literal.

## How it is built and run

- Put your C/C++ source under **`/app/src/`**.
- Create **`/app/setup.sh`** that compiles your sources into an executable at **`/app/urlparse`**,
  for example:
  ```bash
  g++ -O2 -std=c++17 /app/src/*.cpp -o /app/urlparse
  ```
  (use `gcc` for C sources). There is no network at evaluation time; only the C++ toolchain and a
  standard library are available. Implement the parser yourself using only the standard library — do
  not rely on any third-party URL or parsing library.
- `/app/urlparse` must follow the contract above, e.g.
  `printf 'http://example.com/' | /app/urlparse` prints the components with exit 0, while an input
  the standard considers invalid exits non-zero.

## Scope

Implement the WHATWG URL parsing behavior (subject to the grading clarifications above). The grader
runs the standard's conformance suite (hundreds of cases spanning every part of the algorithm, plus
failure cases); each case is scored independently, so a partial implementation is credited for the
cases it handles correctly.

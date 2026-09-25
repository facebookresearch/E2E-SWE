# Task: `rxdisasm` — an x86-64 (long mode) instruction disassembler

Implement a command-line **x86-64 (64-bit / long mode) instruction disassembler** in **Rust**,
using **only the Rust standard library** (no third-party crates, no external tools). Building the
project must produce an executable at **`/app/rxdisasm`**.

## Build contract

Provide a Rust project that builds offline. Grading runs a script that will, if present, execute
`/app/setup.sh` and expects the finished binary at `/app/rxdisasm`. A minimal `setup.sh` such as

```sh
cd /app/src && cargo build --release --offline
cp /app/src/target/release/rxdisasm /app/rxdisasm
```

is sufficient (adapt paths to your layout). You may use only the Rust standard library.

Implementation note: the decoder is large. Split it across several small source modules (e.g.
separate files for the one-byte map, the `0F`/`0F38`/`0F3A` maps, VEX/EVEX, x87, and the operand
formatter) and build it up with incremental edits — avoid emitting one very large source file in a
single step.

## CLI contract

`rxdisasm` reads **standard input**, one instruction per line, each line a **hex byte string**
(whitespace within a line is insignificant, e.g. `48 01 d8` == `4801d8`). For each non-empty input
line it writes exactly **one line** to standard output:

- the textual disassembly of the **single** instruction decoded starting at byte 0 of that line's
  bytes (any trailing bytes beyond that one instruction are ignored), **or**
- a line beginning with `ERR: ` if the bytes are not a legal encoding of a supported instruction, or
  the instruction would need more bytes than the line provides. The text after `ERR: ` is not graded;
  only the `ERR: ` prefix is. A *legal* instruction must never produce `ERR:`.

The process must exit 0. Empty input lines produce no output line.

## Decoding

Decode a single instruction per the standard **x86-64 (Intel 64 / AMD64) encoding** documented in
the Intel SDM Vol. 2 and AMD APM Vol. 3:

- **Legacy prefixes**: operand-size `0x66`, address-size `0x67`, `lock` `0xF0`, `rep`/mandatory
  `0xF2`/`0xF3`, and segment overrides. (The `66`/`F2`/`F3` bytes also act as *mandatory prefixes*
  selecting the SSE variant on the `0F` maps.)
- **REX** (`0x40`–`0x4F`): `W` → 64-bit operand; `R`/`X`/`B` extend `ModRM.reg` / `SIB.index` /
  `r/m`-or-`base` to registers 8–15.
- **Opcode maps**: the 1-byte map; the `0x0F` two-byte map; the `0x0F 0x38` and `0x0F 0x3A`
  three-byte maps.
- **ModR/M + SIB** addressing: `disp8`/`disp32`, RIP-relative (`mod=00, r/m=101`), and the SIB
  no-base / absolute forms.
- **Immediates** of the encoded width, sign-extended where the encoding calls for it.
- **VEX** (2-byte `0xC5`, 3-byte `0xC4`) and **EVEX** (`0x62`) vector encodings: decode the map
  select, implied prefix `pp`, second source `vvvv`/`V'`, `W`, vector length `L`/`L'L`, the
  register-high bits (`R'`/`R`/`X`/`B`), opmask `aaa`, zeroing `z`, and broadcast/rounding `b`.
- **x87 FPU**: opcodes `0xD8`–`0xDF`.
- **Legality**: reject (with `ERR:`) undefined opcodes and encodings that violate the architectural
  field constraints for the specific instruction — e.g. a VEX/EVEX field combination the instruction
  does not permit (an illegal `W`, an opmask on an op that forbids one, static rounding/`sae` on a
  memory or non-permitted form, an out-of-range vector length, or a byte pattern not assigned in the
  selected map). Legality follows the SDM per-instruction definitions and its `#UD` conditions for
  the VEX/EVEX encoding fields.
- **Supported surface**: the tool does not implement every extension a current SDM/APM revision
  assigns. An encoding introduced by an out-of-scope (very recent) extension is rejected with `ERR:`
  even though it is a legal, assigned encoding in a recent manual — its rejection is a scope limit,
  not a field-constraint violation. In particular the VNNI opcodes on the `0F38` map (`50`–`53`, e.g.
  `vpdpbusd`) are **not** supported and must produce `ERR:`.

## Output format

Intel syntax, all lowercase. `mnemonic`, then — if there are operands — one space and the operands
separated by `, ` (comma + space) in **destination, source(s)** order. Mnemonic spellings must
match exactly; notably the tool uses `jz`/`jnz` (not `je`/`jne`), `cmovnz`/`cmovg`/`setl`-style
condition spellings, `loopz`/`loopnz`, `jnb`/`jna`-style, `tzcnt`/`lzcnt`/`popcnt`, `movsxd`,
`movdqu`/`movdqa`/`movaps`/`movups`, `int 0x3`, and `nop`.

### Registers (no `%` sigil)

- 8-bit: `al cl dl bl spl bpl sil dil r8b`..`r15b`; the legacy high-byte set `ah ch dh bh` is used
  only when the instruction has **no** REX prefix.
- 16-bit `ax cx …`; 32-bit `eax ecx …`; 64-bit `rax rcx rdx rbx rsp rbp rsi rdi r8`..`r15`.
- MMX `mm0`..`mm7`; SSE `xmm0`..`xmm15`; AVX `ymm…`; AVX-512 `zmm…` (0..31 via the EVEX high bits);
  x87 `st(0)`..`st(7)`; opmask `k0`..`k7`.

### Memory operands

`SIZE [ADDR]`, where `SIZE` ∈ {`byte word dword qword mword xmmword ymmword zmmword`} is the memory
access size the instruction implies (`mword` = the x87 80-bit / m80 form). `ADDR` joins the present
components with ` + `:

- the base register, then `index * scale` (scale is the literal `1`/`2`/`4`/`8`, and the
  `* scale` term is **always** shown when an index register is present — including `* 1`), then the
  displacement.
- The displacement is signed hex: `+ 0xN` when ≥ 0, `- 0xN` when < 0. A **zero** displacement is
  omitted when a base or index is present.
- **RIP-relative** uses base `rip`: `[rip + 0x7]`, `[rip - 0xc]`.
- The **absolute** form (no base, no index) prints only the displacement, as an **unsigned** hex
  value: `[0xfffffff0]`, `[0x10]`.
- Under the `0x67` address-size prefix, base/index registers print in **32-bit** form: `[eax]`.

### Immediates and branch targets

Immediates are hex. An immediate that carries a **numeric operand value** renders as the **signed
two's-complement of the immediate's width**: `-0xN` (magnitude in hex) when the value's top bit is
set, otherwise `0xN` (e.g. `mov eax, -0x1`). An immediate that is a **count, bit index, or
control/select byte** renders as **unsigned** `0xN`. Which of the two an instruction's immediate is
follows its SDM operand definition. PC-relative branch targets (short/near `jcc`/`jmp`/`call rel`)
print as the **signed relative displacement** `$+0xN` / `$-0xN` — the operand value, not an
absolute address.

### EVEX displacement compression (`disp8 * N`)

When an EVEX instruction encodes an 8-bit displacement (`ModRM mod=01`), the stored signed `disp8`
is **scaled by N** and the *scaled* value is printed. `N` follows the instruction's SDM **tuple
type** together with the vector length and broadcast:

- Full-vector memory (no broadcast): `N` = the vector byte width = `16`/`32`/`64` for
  `xmm`/`ymm`/`zmm`.
- Broadcast element (`{1toK}`): `N` = the broadcast element size (`4` for a dword element, `8` for a
  qword element).
- Other tuple types (e.g. tuple1-scalar, half-vector) scale by their defined element / sub-vector
  size. `disp32` forms and non-EVEX encodings are **not** scaled.

### EVEX/VEX decorators

Rendered as suffixes on the **destination**, and the opmask always comes **first**: `{k1}` opmask
(when `aaa` ≠ 0), then `{z}` (when EVEX.z = 1), or `{k1}` then the rounding/SAE decorator — i.e.
`xmm0{k3}{ru-sae}`, `xmm0{k7}{z}`, never the reverse order. These are rendering rules only: whether
a given combination of decorator fields is a legal encoding at all is decided by **Legality** above.
Static rounding / SAE render on the destination as `{rn-sae}` / `{rd-sae}` / `{ru-sae}` /
`{rz-sae}` (rounding; when EVEX.b = 1 on a reg-reg form, with `L'L` selecting the mode) or `{sae}`.
A broadcast memory **source** renders its `{1toK}` suffix
immediately after the bracketed address (`dword [rax]{1to4}`). Three/four-operand vector forms print
`op dest, src1, src2[, imm8]`.

## Tool-specific rendering conventions

The tool has a few fixed conventions that differ from a naive reading — reproduce them:

- **Shifts/rotates**: the group-2 `/4` encoding prints `shl`; the `/6` encoding prints `sal`
  (both are the shift-left operation but keep their distinct spelling by encoding).
- **Flags stack ops** print the short mnemonics `pushf` / `popf` (not `pushfq` / `popfq`).
- **`prefetch*` and `clflush`** print their memory operand with size `zmmword`.
- **`cmpxchg16b`** prints `cmpxchg16b xmmword [..]`.
- **SSE variable-blend** (`pblendvb` / `blendvps` / `blendvpd`) print **only** their two explicit
  operands (destination and source); the architecturally-implicit `xmm0` mask operand is **not**
  shown (two operands, not three).
- **String ops** print both operands with size and segment, plus the rep word:
  `rep movs byte es:[rdi], byte ds:[rsi]`, `stos byte es:[rdi], al`, `lods al, byte [rsi]`,
  `scas qword es:[rdi], rax`. A `lock` prefix prints a leading `lock `.
- **`pshufw`** uses MMX (`mm`) registers; the mandatory prefix selects `pshufd`(66) / `pshuflw`(F2)
  / `pshufhw`(F3).
- **x87**: memory arithmetic forms print an explicit `st(0)` destination
  (`fadd st(0), qword [rax + 0x8]`, `fld st(0), mword [rsp]`, `fild st(0), dword [rsp]` — integer
  loads use `word`/`dword`/`qword`); stores are `fstp qword [..], st(0)`; register forms are
  `fdivrp st(1), st(0)`, `fcomi st(0), st(1)`, `fucom st(0), st(0)`; no-operand ops are `fld1`,
  `fldz`, `fptan`, `fsincos`, `fninit`, `fnstsw ax`, `fucompp`, …; environment ops use the size word
  `ptr` (`fnstenv ptr [rsp - 0x10]`).
- System group `0F 01`: `xgetbv`, `invlpg byte [..]`, `vmcall`, etc.

## Worked examples (input hex → exact output)

```
33c0                       xor eax, eax
4801d8                     add rax, rbx
8b4c2404                   mov ecx, dword [rsp + 0x4]
488d15f4ffffff             lea rdx, qword [rip - 0xc]
b8ffffffff                 mov eax, -0x1
c70102000000               mov dword [rcx], 0x2
7405                       jz $+0x5
ff5008                     call qword [rax + 0x8]
6a7f                       push 0x7f
f3480fbcc1                 tzcnt rax, rcx
9c                         pushf
660f70c14e                 pshufd xmm0, xmm1, 0x4e
0f70c14e                   pshufw mm0, mm1, 0x4e
f3a4                       rep movs byte es:[rdi], byte ds:[rsi]
0f18042510000000           prefetchnta zmmword [0x10]
6766488b00                 mov rax, qword [eax]
d9e8                       fld1
db2c24                     fld st(0), mword [rsp]
dc4008                     fadd st(0), qword [rax + 0x8]
d97424f0                   fnstenv ptr [rsp - 0x10]
0f0138                     invlpg byte [rax]
62f17c48584002             vaddps zmm0, zmm0, zmmword [rax + 0x80]
62f17c0858407f             vaddps xmm0, xmm0, xmmword [rax + 0x7f0]
62f14c18581001             vaddps xmm2, xmm6, dword [rax]{1to4}
62f17c1858c1               vaddps zmm0{rn-sae}, zmm0, zmm1
62f27dcf4dc1               vrcp14ss xmm0{k7}{z}, xmm0, xmm1
62f34d4025c10555           vpternlogd zmm0, zmm22, zmm1, 0x5
62f37d481902017f           vextractf32x4 xmmword [rdx], zmm0, 0x1
c4020508c1                 vpsignb ymm8, ymm15, ymm9
62f17d48587f01             ERR: (illegal encoding)
```

Your program is graded byte-exact over a held-out set of instructions spanning the full surface
described above.

# BARF — Binary Analysis and Reverse engineering Framework

Build `barf`, a Python framework for binary analysis and reverse engineering. It
loads executable files, disassembles native instructions for **Intel x86 (32 and
64 bit)** and **ARM (32 bit)**, lifts every instruction to an architecture-neutral
intermediate language called **REIL**, and provides analyses on top of REIL: an
instruction emulator, control-flow-graph and call-graph recovery, an SMT-backed
code analyzer, a symbolic execution engine, and a ROP-gadget find/classify/verify
pipeline.

All analyses operate on REIL, so they are architecture-agnostic: native code is
translated to REIL once and every analysis consumes REIL.

## Dependencies

The environment is **offline**: every dependency below is **already installed**, and the project
itself is installed for you by a `setup.sh` that runs offline. **Do not install anything** (no
`pip install`, no `apt-get`) — there is no network, and attempting to fetch packages will fail.

- **Python packages** (pre-installed): `capstone` (disassembly backend — use the **capstone 4.x
  API**), `pyelftools` (ELF parsing), `pefile` (PE parsing), `pyparsing` (assembly and REIL text
  parsers), `networkx` and `pydot` (graphs), `future`, `pygments`.
- **System** (pre-installed): the **`z3` SMT solver executable** is on `PATH`. All SMT
  functionality drives the solver by spawning `z3 -smt2 -in` as a subprocess and
  exchanging SMT-LIB2 text (availability is detected with `which z3`). If `z3` is
  not found, SMT-dependent components must degrade gracefully (see the `BARF`
  facade below), but for this task assume `z3` is present.

## Package structure (import paths used by callers)

Expose at least the following fully-qualified import paths. Organise the rest of
the package however you like.

```
barf                                   -> BARF
barf.arch                              -> ARCH_X86, ARCH_ARM,
                                          ARCH_X86_MODE_32, ARCH_X86_MODE_64,
                                          ARCH_ARM_MODE_ARM, ARCH_ARM_MODE_THUMB
barf.arch.x86                          -> X86ArchitectureInformation
barf.arch.x86.parser                   -> X86Parser
barf.arch.x86.disassembler             -> X86Disassembler
barf.arch.x86.translator               -> X86Translator
barf.arch.arm.parser                   -> ArmParser
barf.core.binary                       -> BinaryFile
barf.core.symbols                      -> load_symbols
barf.core.reil                         -> ReilRegisterOperand, ReilImmediateOperand
barf.core.reil.parser                  -> ReilParser
barf.core.reil.container               -> ReilContainer, ReilSequence
barf.core.reil.emulator                -> ReilEmulator, ReilCpuZeroDivisionError
barf.core.smt.smtsolver                -> Z3Solver
barf.core.smt.smtsymbol                -> BitVec
barf.core.smt.smttranslator            -> SmtTranslator
barf.analysis.codeanalyzer             -> CodeAnalyzer
barf.analysis.graphs                   -> CFGRecoverer, RecursiveDescent,
                                          ControlFlowGraph
barf.analysis.graphs.callgraph         -> CallGraph
barf.analysis.symbolic.emulator        -> ReilSymbolicEmulator, State, SymExecResult
barf.analysis.gadgets.finder           -> GadgetFinder
barf.analysis.gadgets.classifier       -> GadgetClassifier
barf.analysis.gadgets.verifier         -> GadgetVerifier
barf.analysis.gadgets.gadget           -> GadgetType
barf.utils.reil                        -> ReilContainerBuilder
```

## Architecture constants (`barf.arch`)

Module-level integer constants identifying the architecture and its mode:

- Architecture: `ARCH_X86`, `ARCH_ARM`.
- x86 modes: `ARCH_X86_MODE_32`, `ARCH_X86_MODE_64`.
- ARM modes: `ARCH_ARM_MODE_ARM`, `ARCH_ARM_MODE_THUMB`.

`BinaryFile` reports these values, and the architecture-specific classes
(`X86ArchitectureInformation`, parsers, disassemblers, translators) accept the
corresponding mode constant. Distinct architectures and distinct modes must
compare unequal.

## `BinaryFile` (`barf.core.binary`)

`BinaryFile(filename)` loads an ELF or PE executable (format auto-detected) and
exposes, as read attributes:

- `architecture` — `ARCH_X86` or `ARCH_ARM`.
- `architecture_mode` — the mode constant (e.g. `ARCH_X86_MODE_32` /
  `ARCH_X86_MODE_64`) derived from the file.
- `text_section` — the executable section's bytes, indexable by **absolute
  virtual address**: `binary.text_section[addr]` returns the integer byte
  (0–255) mapped at `addr`.
- `ea_start`, `ea_end` — first and last virtual addresses of the text section
  (`ea_end > ea_start`).

## `X86ArchitectureInformation` (`barf.arch.x86`)

`X86ArchitectureInformation(arch_mode)` describes the x86 target. Analyses read
from it; the attributes used by callers are:

- `address_size` — pointer width in bits (32 or 64).
- `registers_size` — mapping of register name → bit width.
- `alias_mapper` — mapping describing sub-register aliases (e.g. `al`/`ah` within
  `eax`), used to relate aliased registers when translating to SMT.

## Assembly parsing

### `X86Parser` (`barf.arch.x86.parser`)

`X86Parser(arch_mode)`; `parse(text)` returns an instruction object. The object's
`str()` is the **canonical** assembly form and is mutable via `.address` and
`.size`. Canonicalisation rules (so `str(parse(text))` is stable):

- Mnemonic and operands separated by a single space, operands by `", "`.
- Memory operands print with **no internal spaces**:
  `[base+index*scale+disp]`, e.g. `add eax, [ebx + edx * 4 + 0x10]` →
  `"add eax, [ebx+edx*4+0x10]"`.
- Operand size prefixes are lowercase: `"inc dword ptr [ebx+edx*4+0x10]"`.
- Displacements keep their **signed** textual form:
  `"mov dword ptr [-0x21524111], ecx"` stays negative.
- 64-bit register names (`rax`, `r8`, `r15`, …) are supported in
  `ARCH_X86_MODE_64`.

### `ArmParser` (`barf.arch.arm.parser`)

`ArmParser(arch_mode)`; `parse(text)` returns an instruction whose `str()`
round-trips standard ARM syntax: data-processing forms (`"mov r0, #0"`,
`"add r3, r3, #1"`, `"cmp r7, r8"`), shifted register operands
(`"sub r10, r9, r8, lsr #4"`), and load/store addressing (`"ldr r2, [r3, #4]"`).

## Disassembler (`barf.arch.x86.disassembler`)

`X86Disassembler(arch_mode)` decodes raw bytes into instruction objects using
capstone. It is consumed by the CFG recoverer and the gadget finder (they call
into it); a standalone decode API is not required by callers.

## REIL intermediate language

REIL is a small, side-effect-explicit RISC-like IR (per Dullien & Porst). Each
REIL instruction has a mnemonic and exactly **three operands** (any of which may
be empty). Operands are registers (including temporaries like `t0`), immediates,
or empty.

### Mnemonics

Support this instruction set (textual names in parentheses): `ADD` (`add`),
`SUB` (`sub`), `MUL` (`mul`), `DIV` (`div`), `MOD` (`mod`), `BSH` (`bsh`,
bit-shift; negative count shifts right), `AND` (`and`), `OR` (`or`), `XOR`
(`xor`), `LDM` (`ldm`, load memory), `STM` (`stm`, store memory), `STR` (`str`,
copy/assign), `BISZ` (`bisz`, boolean-is-zero), `JCC` (`jcc`, conditional jump),
`UNKN` (`unkn`), `UNDEF` (`undef`), `NOP` (`nop`), `SEXT` (`sext`), `SDIV`
(`sdiv`), `SMOD` (`smod`), `SMUL` (`smul`).

### REIL addresses

A REIL instruction's address packs the native address in the high bits and the
intra-instruction index in the low byte: `reil_addr = (native_addr << 8) | i`.
Callers start a `ReilEmulator.execute` run at `native_addr << 8`.

### Operands (`barf.core.reil`)

- `ReilRegisterOperand(name, size)` — named register/temporary of `size` bits.
- `ReilImmediateOperand(value, size)` — constant of `size` bits.
- Operands compare equal iff same type, size and name/value.
- A register operand's `str()` is just its name; size is carried separately.

### REIL text parser (`barf.core.reil.parser`)

`ReilParser()`; `parse(list_of_strings)` returns a list of REIL instruction
objects. Input syntax: `"<mnemonic> [<op0>, <op1>, <op2>]"`, where an operand may
carry an optional size keyword, e.g. `"add [DWORD t0, DWORD t1, DWORD t2]"`, and
`EMPTY` denotes an empty operand. Each parsed instruction has a settable
`.address` and a list `.operands` of three operands; each operand exposes `.size`
in bits.

Size resolution: a size keyword sets the operand width (`BYTE`=8, `WORD`=16,
`DWORD`=32, `QWORD`=64, `DQWORD`=128, `DDQWORD`=256, `POINTER`); an `EMPTY`
operand has size `0`; an operand given with **no** size keyword has size `None`.

Instruction `str()` form: the mnemonic left-justified to width 5 followed by
`" [op0, op1, op2]"`. A non-empty operand renders as `"<SIZE> <name>"` where
`<SIZE>` is the size keyword for its bit width (e.g. `DWORD`) or `UNK` when its
size is `None`; an empty operand renders as `EMPTY`. For example, parsing
`"str [eax, EMPTY, t0]"` then `str()`-ing it yields `"str   [UNK eax, EMPTY, UNK t0]"`,
and `"add [t0, t1, t2]"` yields `"add   [UNK t0, UNK t1, UNK t2]"`.

### REIL containers (`barf.core.reil.container`)

For emulating multi-instruction code with control flow:

- `ReilSequence()` — an ordered block of REIL instructions for one native
  instruction. `append(reil_instr)` adds one; `.address` is the block's start
  REIL address (read); `.next_sequence_address` is settable to chain to the next
  block's address (used for fall-through).
- `ReilContainer()` — `add(sequence)` registers a sequence; the container maps
  REIL addresses to instructions for the emulator.

## Translators (`barf.arch.x86.translator`)

`X86Translator(arch_mode)`; `translate(asm_instr)` returns the list of REIL
instructions implementing that native instruction's semantics (registers, memory
and CPU flags). The lifted REIL, when emulated, must reproduce the architecture's
behaviour, including: register arithmetic (`add`, `sub`, `imul`, `inc`, `dec`),
bitwise/shift ops (`and`, `or`, `xor`, `shl`, `shr`), partial-register writes
(`al`/`ah` updating only their byte lanes of `eax`), data movement (`mov` with
immediates and memory operands), comparisons and conditional jumps (`cmp`/`jne`),
and integer division (which must raise on divide-by-zero — see the emulator).

An **ARM translator** provides the same service for ARM-32 (used implicitly via
the `BARF` facade): it must lift ordinary compiled ARM-32 code — data-processing,
load/store and branch forms — and the lifted REIL, when emulated, must reproduce
ARM register, memory and flag/condition-code behaviour (no per-binary literals
are specified — the results follow from correct emulation).

## REIL emulator (`barf.core.reil.emulator`)

`ReilEmulator(arch_info)` executes REIL and models registers and memory as
fixed-width bit-vectors.

- `execute_lite(reil_instrs, context=None)` — execute a flat list of REIL
  instructions straight-line. `context` is a dict of initial register values
  (`{name: int}`). Returns `(registers_out, memory_out)` where `registers_out`
  maps register name → integer value. Unspecified registers default to 0.
- `execute(container, start=None, registers=None)` — execute a `ReilContainer`,
  following `jcc` branches and `next_sequence_address` links until control leaves
  the code. `start` is a REIL address (`native << 8`). Returns the same
  `(registers_out, memory_out)` pair.
- Integer division by zero raises `ReilCpuZeroDivisionError`
  (`barf.core.reil.emulator`).

## High-level facade (`barf.BARF`)

`BARF(filename)` opens a binary and wires up all components for its architecture
(disassembler, translator, REIL emulator, and — when `z3` is available — an SMT
solver, SMT translator and `code_analyzer`). Methods used:

- `translate(start=None, end=None)` — generator yielding
  `(address, asm_instr, reil_instrs)` for each native instruction in the range.
- `emulate(start=None, end=None)` — emulate the binary's own code over the address
  range and return the final context as
  `{"registers": {name: int, ...}, "memory": {...}}`.
- `recover_cfg_all(entries, symbols=None)` — recover a CFG per function starting
  from each address in `entries` (following discovered calls), returning a list
  of `ControlFlowGraph`. `symbols` is a symbol table as returned by
  `load_symbols` and names the recovered functions.
- `code_analyzer` — a `CodeAnalyzer` (see below) bound to this binary's SMT
  solver/translator (present when `z3` is available).

## Symbols (`barf.core.symbols`)

`load_symbols(filename)` returns a dict mapping each function's start address to
its symbol info (a tuple beginning with the function `name` and its `size`). Used
to enumerate function entry points and to name recovered functions.

## Control-flow graph (`barf.analysis.graphs`)

Recovery uses a pluggable strategy:

- `RecursiveDescent(disassembler, text_bytes, translator, arch_info)` — recovery
  strategy; `text_bytes` is the binary's text section.
- `CFGRecoverer(strategy)` — `build(start, end, symbols=None)` returns
  `(basic_blocks, call_targets)`. A `call` does not end a basic block: the block
  continues with the instruction that follows the call, and the callee's address
  is reported only through `call_targets`.
- `ControlFlowGraph(basic_blocks, name=None)` — exposes:
  - `basic_blocks` — list of blocks.
  - `start_address`, `end_address` — the address range the graph spans.
    `start_address` is the lowest instruction address in the graph (the first
    block's start); `end_address` is the address of the **last byte** of the
    last instruction (i.e. last instruction's address + its size − 1), so for a
    single linear block recovered over a range it equals that range's inclusive
    upper bound.
  - `find_basic_block(address)` — the block starting at `address`.

Each basic block exposes branch information:

- `branches` — list of outgoing edges (each an `(address, kind)` pair); its
  length is the out-degree.
- `taken_branch` / `not_taken_branch` — successor addresses of a conditional
  branch (the taken and fall-through targets), else `None`.
- `direct_branch` — successor address of an unconditional branch/fall-through,
  else `None`.

## Call graph (`barf.analysis.graphs.callgraph`)

`CallGraph(cfgs)` builds a call graph from a list of `ControlFlowGraph` (detecting
calls between functions). Methods:

- `find_function_by_name(name)` — the CFG of the named function, or `None`.
- `simple_paths_by_address(start_address, end_address)` — iterate the simple call
  paths (as sequences of CFGs) from one function to another.

## SMT layer

### `Z3Solver` (`barf.core.smt.smtsolver`)

`Z3Solver()` wraps the `z3` executable. Methods:

- `declare_fun(name, symbol)` — declare a variable.
- `add(constraint)` — assert a boolean constraint.
- `check()` — return `"sat"`, `"unsat"`, or `"unknown"`.
- `get_value(expr)` — after a `"sat"` check, return the model's integer value for
  `expr`.
- `reset()` — clear all declarations and assertions.

### `BitVec` (`barf.core.smt.smtsymbol`)

`BitVec(size, name)` is a symbolic bit-vector of `size` bits. It supports the
Python arithmetic/bitwise operators (`+`, `-`, `*`, `&`, `|`, `^`, …) and
comparison operators (`==`, `!=`, `<`, `<=`, `>`, `>=`) to build constraints, plus
unsigned-comparison methods `uge`, `ule`, `ugt`, `ult`. Operations on bit-vectors
return bit-vectors; comparisons return boolean constraints.

### `SmtTranslator` (`barf.core.smt.smttranslator`)

`SmtTranslator(solver, address_size)` translates REIL into SMT expressions over
`solver`. Configure it with `set_arch_alias_mapper(arch_info.alias_mapper)` and
`set_arch_registers_size(arch_info.registers_size)` before use.

## Code analyzer (`barf.analysis.codeanalyzer`)

`CodeAnalyzer(smt_solver, smt_translator, arch_info)` is a high-level interface
for reasoning about a stretch of code with the SMT solver. Workflow:

- `add_instruction(reil_instr)` — add a REIL instruction to the analysis (in
  program order). The analyzer tracks pre- and post-execution machine state.
- `get_register_expr(name, mode="pre"|"post")` — a bit-vector expression for a
  register's value before/after the added code.
- `get_memory_expr(address_expr, size, mode="pre"|"post")` — a bit-vector for the
  `size`-byte memory value at `address_expr` before/after. `address_expr` may be
  built from register expressions (e.g. `ebp - 0x8`).
- `add_constraint(constraint)` — assert a constraint over these expressions.
- `check()` — `"sat"` / `"unsat"`.
- `get_expr_value(expr)` — concrete value of an expression in the satisfying
  model.

## Symbolic execution (`barf.analysis.symbolic.emulator`)

Concolic execution over REIL, used to recover inputs that drive a function down a
chosen path (e.g. crackme serials).

- `ReilContainerBuilder(binary)` (`barf.utils.reil`) — `build(functions)` lifts
  the named functions to a REIL container ready for symbolic execution.
  `functions` is a list of `(name, start_address, end_address)` tuples.
- `State(arch_info, mode="initial"|"final")` — a (partly symbolic) machine state:
  - `write_register(name, value)`, `write_memory(address, size, value)` — seed
    concrete values.
  - `query_memory(address, size)` — a symbolic expression for a memory range
    (supporting `uge`/`ule`, etc.), used to constrain unknown inputs.
  - `add_constraint(constraint)` — restrict the symbolic inputs.
- `ReilSymbolicEmulator(arch_info)`:
  - `find_address(container, start, end, find, avoid, initial_state)` — explore
    from `start` to `end`, returning the list of feasible paths that reach the
    `find` address without passing through any address in `avoid`.
  - `find_state(container, start, end, initial_state, final_state)` — return the
    list of feasible paths from `initial_state` that end in a state consistent
    with the (partly specified) `final_state`.
  - For both entry points `start`, `end`, `find` and the entries of `avoid` are
    **native** addresses — the same address space as the tuples given to
    `ReilContainerBuilder.build` — which the engine maps onto REIL addresses
    itself.
- `SymExecResult(arch_info, initial_state, path, final_state)` — solves one
  returned path; `query_memory(address, size)` returns the concrete integer the
  solver assigns to that memory range, recovering the required input.

## ROP gadgets (`barf.analysis.gadgets`)

A three-stage pipeline over raw machine code (a `bytearray`):

- `GadgetFinder(disassembler, code_bytes, translator, architecture, architecture_mode)`
  — `find(start, end)` returns the list of raw gadgets (instruction sequences
  ending in a `ret`/`jmp`/`call`) found in the byte range. A range may yield
  several overlapping candidates depending on where decoding begins.
- `GadgetClassifier(ir_emulator, arch_info)` — `classify(raw_gadget)` returns a
  list of typed gadgets, assigning each a semantic type by emulating it. A single
  raw gadget may yield several typed gadgets (e.g. `xchg`-based register swaps
  classify as a move in **both** directions). Each typed gadget exposes:
  - `type` — a `GadgetType` value.
  - `sources` — list of source operands (`ReilRegisterOperand` /
    `ReilImmediateOperand`).
  - `destination` — list of destination operands.
  - `modified_registers` — registers clobbered besides the destination.
- `GadgetVerifier(code_analyzer, arch_info)` — `verify(typed_gadget)` returns
  `True` iff the gadget's assigned semantics provably hold (checked with the SMT
  solver).

### `GadgetType` (`barf.analysis.gadgets.gadget`)

An enumeration of gadget semantics. The full taxonomy is: `NoOperation`, `Jump`,
`MoveRegister` (`dst_reg <- src_reg`), `LoadConstant` (`dst_reg <- immediate`),
`Arithmetic`, `LoadMemory`, `StoreMemory`, `ArithmeticLoad`, `ArithmeticStore`,
`Undefined`. Classification must distinguish at least these categories.

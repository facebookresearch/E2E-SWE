"""Hidden grading suite for the BARF binary-analysis framework task.

Every test exercises BARF through its public Python API the way a real user
would: open a binary, disassemble/lift it to REIL, emulate code, recover a CFG,
reason about it with an SMT solver, recover crackme serials via symbolic
execution, and find/classify/verify ROP gadgets.

Fixture binaries live under ``/tests/data`` at grading time. The SMT-backed
tests require the ``z3`` solver executable to be on PATH (installed by
``test.sh``); BARF shells out to ``z3 -smt2 -in``.
"""

from __future__ import absolute_import

import os

import pytest

from barf.arch import ARCH_ARM
from barf.arch import ARCH_ARM_MODE_THUMB
from barf.arch import ARCH_X86
from barf.arch import ARCH_X86_MODE_32
from barf.arch import ARCH_X86_MODE_64
from barf.arch.arm.parser import ArmParser
from barf.arch.x86 import X86ArchitectureInformation
from barf.arch.x86.disassembler import X86Disassembler
from barf.arch.x86.parser import X86Parser
from barf.arch.x86.translator import X86Translator
from barf.core.binary import BinaryFile
from barf.core.reil.container import ReilContainer
from barf.core.reil.container import ReilSequence
from barf.core.reil.emulator import ReilCpuZeroDivisionError
from barf.core.reil.emulator import ReilEmulator
from barf.core.reil.parser import ReilParser


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def data_path(name):
    return os.path.join(DATA_DIR, name)


def build_reil_container(translator, asm_instrs):
    """Lift a list of (already addressed/sized) asm instructions into a
    ReilContainer with the sequence chaining the emulator's execute() needs."""
    container = ReilContainer()

    instr_seq_prev = None
    for asm_instr in asm_instrs:
        instr_seq = ReilSequence()
        for reil_instr in translator.translate(asm_instr):
            instr_seq.append(reil_instr)

        if instr_seq_prev:
            instr_seq_prev.next_sequence_address = instr_seq.address

        container.add(instr_seq)
        instr_seq_prev = instr_seq

    return container


# ===========================================================================
# Binary loading
# ===========================================================================
def test_binary_loading_detects_architecture_and_mode():
    """Opening ELF binaries exposes their architecture, mode and a readable
    .text section for x86-32, x86-64 and ARM targets."""
    bin_x86_32 = BinaryFile(data_path("x86_sample_1"))
    assert bin_x86_32.architecture == ARCH_X86
    assert bin_x86_32.architecture_mode == ARCH_X86_MODE_32

    bin_x86_64 = BinaryFile(data_path("example1.x86_64"))
    assert bin_x86_64.architecture == ARCH_X86
    assert bin_x86_64.architecture_mode == ARCH_X86_MODE_64

    bin_arm = BinaryFile(data_path("loop2.arm"))
    assert bin_arm.architecture == ARCH_ARM

    # The .text section is addressable byte-by-byte over its range.
    first_byte = bin_x86_32.text_section[bin_x86_32.ea_start]
    assert 0 <= first_byte <= 0xFF
    assert bin_x86_32.ea_end > bin_x86_32.ea_start


# ===========================================================================
# x86 assembly parser
# ===========================================================================
def test_x86_assembly_parser_roundtrip():
    """The x86 parser turns assembly text into instruction objects whose string
    form preserves operands, addressing modes and immediate signedness."""
    parser32 = X86Parser(ARCH_X86_MODE_32)

    assert str(parser32.parse("add eax, ebx")) == "add eax, ebx"
    assert str(parser32.parse("add eax, 0x12345678")) == "add eax, 0x12345678"
    assert str(parser32.parse("add eax, [ebx + edx * 4 + 0x10]")) == "add eax, [ebx+edx*4+0x10]"
    assert str(parser32.parse("inc dword ptr [ebx+edx*4+0x10]")) == "inc dword ptr [ebx+edx*4+0x10]"
    assert str(parser32.parse("nop")) == "nop"
    # Negative displacements keep their signed form.
    assert (
        str(parser32.parse("mov dword ptr [-0x21524111], ecx"))
        == "mov dword ptr [-0x21524111], ecx"
    )

    parser64 = X86Parser(ARCH_X86_MODE_64)
    assert str(parser64.parse("add rax, r8")) == "add rax, r8"
    assert str(parser64.parse("add rax, [rbx + r15 * 4 + 0x10]")) == "add rax, [rbx+r15*4+0x10]"


def test_arm_assembly_parser_roundtrip():
    """The ARM parser handles data-processing instructions, immediates, shifted
    operands and load/store addressing, preserving them on string round-trip."""
    parser = ArmParser(ARCH_ARM_MODE_THUMB)

    assert str(parser.parse("mov r0, #0")) == "mov r0, #0"
    assert str(parser.parse("add r3, r3, #1")) == "add r3, r3, #1"
    assert str(parser.parse("cmp r7, r8")) == "cmp r7, r8"
    assert str(parser.parse("sub r10, r9, r8, lsr #4")) == "sub r10, r9, r8, lsr #4"
    assert str(parser.parse("ldr r2, [r3, #4]")) == "ldr r2, [r3, #4]"


# ===========================================================================
# REIL parser
# ===========================================================================
def test_reil_parser_structure_and_operand_sizes():
    """The REIL parser produces instruction objects with a canonical string
    form and resolves explicit/implicit operand sizes."""
    parser = ReilParser()

    parsed = parser.parse(
        [
            "str [eax, EMPTY, t0]",
            "add [t0, t1, t2]",
        ]
    )
    assert str(parsed[0]) == "str   [UNK eax, EMPTY, UNK t0]"
    assert str(parsed[1]) == "add   [UNK t0, UNK t1, UNK t2]"

    sized = parser.parse(
        [
            "str [DWORD eax, EMPTY, DWORD t0]",
            "str [eax, EMPTY, t0]",
        ]
    )
    # DWORD -> 32 bits, EMPTY operand -> 0, unspecified -> None.
    assert sized[0].operands[0].size == 32
    assert sized[0].operands[1].size == 0
    assert sized[0].operands[2].size == 32
    assert sized[1].operands[0].size is None
    assert sized[1].operands[2].size is None


# ===========================================================================
# REIL translation + emulation
# ===========================================================================
def test_translate_and_emulate_register_arithmetic():
    """Lifting `add eax, ebx` to REIL and emulating it adds the operands and
    leaves the source register untouched."""
    parser = X86Parser(ARCH_X86_MODE_32)
    translator = X86Translator(ARCH_X86_MODE_32)
    emulator = ReilEmulator(X86ArchitectureInformation(ARCH_X86_MODE_32))

    asm = parser.parse("add eax, ebx")
    asm.address = 0xDEADBEEF
    reil_instrs = translator.translate(asm)

    regs_out, _ = emulator.execute_lite(reil_instrs, context={"eax": 0x1, "ebx": 0x2})

    assert regs_out["eax"] == 0x3
    assert regs_out["ebx"] == 0x2


def test_translate_and_emulate_partial_register_writes():
    """Writing the 8-bit sub-registers al/ah updates only the corresponding
    byte lanes of the 32-bit register."""
    parser = X86Parser(ARCH_X86_MODE_32)
    translator = X86Translator(ARCH_X86_MODE_32)
    emulator = ReilEmulator(X86ArchitectureInformation(ARCH_X86_MODE_32))

    asm_instrs = [parser.parse(s) for s in ["mov eax, 0xdeadbeef", "mov al, 0x12", "mov ah, 0x34"]]
    for i, asm in enumerate(asm_instrs):
        asm.address = 0xDEADBEEF + i

    reil_instrs = []
    for asm in asm_instrs:
        reil_instrs += translator.translate(asm)

    regs_out, _ = emulator.execute_lite(reil_instrs, context={"eax": 0xFFFFFFFF})

    assert regs_out["eax"] == 0xDEAD3412


def _emulate_x86_sequence(asm_strings, context):
    """Translate a straight-line x86 snippet and emulate it, returning the final
    register dict."""
    parser = X86Parser(ARCH_X86_MODE_32)
    translator = X86Translator(ARCH_X86_MODE_32)
    emulator = ReilEmulator(X86ArchitectureInformation(ARCH_X86_MODE_32))

    reil_instrs = []
    for i, asm_str in enumerate(asm_strings):
        asm = parser.parse(asm_str)
        asm.address = 0x1000 + i
        reil_instrs += translator.translate(asm)

    regs_out, _ = emulator.execute_lite(reil_instrs, context=context)
    return regs_out


def test_translate_and_emulate_bitwise_logical_ops():
    """Lifting and emulating the bitwise/shift instruction family (and, or, xor,
    shl, shr) produces the correct masked/shifted result."""
    regs_out = _emulate_x86_sequence(
        [
            "mov eax, 0xf0",
            "and eax, 0x3c",  # 0x30
            "or eax, 0xf",  # 0x3f
            "xor eax, 0xff",  # 0xc0
            "shl eax, 0x1",  # 0x180
            "shr eax, 0x4",  # 0x18
        ],
        context={},
    )

    assert regs_out["eax"] == 0x18


def test_translate_and_emulate_arithmetic_ops():
    """Lifting and emulating the arithmetic instruction family (imul, inc, dec)
    produces the correct signed-multiply and increment/decrement results."""
    regs_out = _emulate_x86_sequence(
        [
            "mov eax, 0x6",
            "mov ebx, 0x7",
            "imul eax, ebx",  # 0x2a
            "inc eax",  # 0x2b
            "dec eax",  # 0x2a
        ],
        context={},
    )

    assert regs_out["eax"] == 0x2A


def test_emulate_reil_with_loop_control_flow():
    """Emulating a counted loop through the REIL container honours the JCC
    back-edge until the counter reaches zero."""
    parser = X86Parser(ARCH_X86_MODE_32)
    translator = X86Translator(ARCH_X86_MODE_32)
    emulator = ReilEmulator(X86ArchitectureInformation(ARCH_X86_MODE_32))

    program = [
        (0x08048060, "mov eax,0x0", 5),
        (0x08048065, "mov ebx,0xa", 5),
        (0x0804806A, "add eax,0x1", 3),
        (0x0804806D, "sub ebx,0x1", 3),
        (0x08048070, "cmp ebx,0x0", 3),
        (0x08048073, "jne 0x0804806a", 2),
    ]

    asm_instrs = []
    for addr, asm_str, size in program:
        asm = parser.parse(asm_str)
        asm.address = addr
        asm.size = size
        asm_instrs.append(asm)

    container = build_reil_container(translator, asm_instrs)

    regs_out, _ = emulator.execute(container, start=0x08048060 << 8)

    assert regs_out["eax"] == 0xA
    assert regs_out["ebx"] == 0x0


def test_emulate_division_by_zero_raises():
    """Emulating an integer division by zero raises the dedicated REIL CPU
    error rather than producing a bogus result."""
    parser = X86Parser(ARCH_X86_MODE_32)
    translator = X86Translator(ARCH_X86_MODE_32)
    emulator = ReilEmulator(X86ArchitectureInformation(ARCH_X86_MODE_32))

    asm = parser.parse("div ebx")
    asm.address = 0xDEADBEEF
    reil_instrs = translator.translate(asm)

    with pytest.raises(ReilCpuZeroDivisionError):
        emulator.execute_lite(reil_instrs, context={"eax": 0x2, "edx": 0x2, "ebx": 0x0})


# ===========================================================================
# High-level binary emulation (BARF facade)
# ===========================================================================
def test_emulate_binary_computes_loop_result_x86():
    """Emulating the x86 loop binary end-to-end through the BARF facade returns
    the final processor context with the loop counter result in eax."""
    from barf import BARF

    barf = BARF(data_path("loop2.x86"))
    context_out = barf.emulate(start=0x080483EC, end=0x08048414)

    assert context_out["registers"]["eax"] == 0xA


def test_emulate_binary_computes_loop_result_arm():
    """The same loop compiled for ARM emulates through the architecture-agnostic
    REIL pipeline and yields the result in r3."""
    from barf import BARF

    barf = BARF(data_path("loop2.arm"))
    context_out = barf.emulate(start=0x8390, end=0x83E0)

    assert context_out["registers"]["r3"] == 0xA


# ===========================================================================
# CFG recovery
# ===========================================================================
def test_recover_control_flow_graph_structure():
    """Recursive-descent CFG recovery yields the right basic-block decomposition
    and branch edges for a linear function and a branching one."""
    from barf.analysis.graphs import CFGRecoverer, ControlFlowGraph, RecursiveDescent

    arch_info = X86ArchitectureInformation(ARCH_X86_MODE_32)
    disassembler = X86Disassembler(ARCH_X86_MODE_32)
    translator = X86Translator(ARCH_X86_MODE_32)

    # Linear function -> single basic block.
    binary1 = BinaryFile(data_path("x86_sample_1"))
    recoverer1 = CFGRecoverer(
        RecursiveDescent(disassembler, binary1.text_section, translator, arch_info)
    )
    bbs1, _ = recoverer1.build(0x0804840B, 0x08048438)
    cfg1 = ControlFlowGraph(bbs1, name="main")
    assert len(cfg1.basic_blocks) == 1
    assert cfg1.start_address == 0x0804840B
    assert cfg1.end_address == 0x08048438

    # Branching function -> four basic blocks with an if/else diamond.
    binary2 = BinaryFile(data_path("x86_sample_2"))
    recoverer2 = CFGRecoverer(
        RecursiveDescent(disassembler, binary2.text_section, translator, arch_info)
    )
    bbs2, _ = recoverer2.build(0x0804846D, 0x080484A3)
    cfg2 = ControlFlowGraph(bbs2, name="main")
    assert len(cfg2.basic_blocks) == 4

    bb_entry = cfg2.find_basic_block(0x0804846D)
    assert len(bb_entry.branches) == 2
    assert bb_entry.taken_branch == 0x08048491
    assert bb_entry.not_taken_branch == 0x0804848A

    bb_taken = cfg2.find_basic_block(0x08048491)
    assert bb_taken.direct_branch == 0x08048496
    bb_not_taken = cfg2.find_basic_block(0x0804848A)
    assert bb_not_taken.direct_branch == 0x08048496


def test_recover_call_graph_from_symbols():
    """Recovering every function from the symbol table and building a call graph
    exposes the caller/callee relationships: main reaches function_of_interest."""
    from barf.analysis.graphs.callgraph import CallGraph
    from barf import BARF
    from barf.core.symbols import load_symbols

    filename = data_path("example1.x86_64")
    barf = BARF(filename)
    symbols = load_symbols(filename)
    entries = [addr for addr in sorted(symbols.keys())]

    cfgs = barf.recover_cfg_all(entries, symbols=symbols)
    cfgs = [cfg for cfg in cfgs if len(cfg.basic_blocks) > 0]
    cg = CallGraph(cfgs)

    main = cg.find_function_by_name("main")
    target = cg.find_function_by_name("function_of_interest")
    assert main is not None
    assert target is not None

    # main transitively calls function_of_interest (main -> some_function -> ...).
    paths = list(cg.simple_paths_by_address(main.start_address, target.start_address))
    assert len(paths) >= 1


# ===========================================================================
# SMT solver
# ===========================================================================
def test_smt_solver_satisfiable_and_unsatisfiable():
    """The Z3-backed solver finds models for satisfiable bit-vector constraints
    and reports unsatisfiable for contradictory ones."""
    from barf.core.smt.smtsolver import Z3Solver
    from barf.core.smt.smtsymbol import BitVec

    solver = Z3Solver()
    x = BitVec(32, "x")
    y = BitVec(32, "y")
    z = BitVec(32, "z")
    for name, sym in [("x", x), ("y", y), ("z", z)]:
        solver.declare_fun(name, sym)

    solver.add(x + y == z)
    solver.add(x > 1)
    solver.add(y > 1)
    solver.add(x != y)

    assert solver.check() == "sat"
    x_val = solver.get_value(x)
    y_val = solver.get_value(y)
    z_val = solver.get_value(z)
    assert (x_val + y_val) & 0xFFFFFFFF == z_val

    solver.reset()
    w = BitVec(32, "w")
    solver.declare_fun("w", w)
    solver.add(w == 0)
    solver.add(w > 0)
    assert solver.check() == "unsat"


def test_code_analyzer_pre_post_conditions():
    """The code analyzer reasons over the pre/post state of lifted instructions:
    forcing eax to 42 after `add eax, ebx` is satisfiable with eax != 42 before."""
    from barf.analysis.codeanalyzer import CodeAnalyzer
    from barf.core.smt.smtsolver import Z3Solver
    from barf.core.smt.smttranslator import SmtTranslator

    arch_info = X86ArchitectureInformation(ARCH_X86_MODE_32)
    solver = Z3Solver()
    smt_translator = SmtTranslator(solver, arch_info.address_size)
    smt_translator.set_arch_alias_mapper(arch_info.alias_mapper)
    smt_translator.set_arch_registers_size(arch_info.registers_size)

    parser = X86Parser(ARCH_X86_MODE_32)
    translator = X86Translator(ARCH_X86_MODE_32)
    analyzer = CodeAnalyzer(solver, smt_translator, arch_info)

    asm = parser.parse("add eax, ebx")
    asm.address = 0x0
    for reil_instr in translator.translate(asm):
        analyzer.add_instruction(reil_instr)

    eax_pre = analyzer.get_register_expr("eax", mode="pre")
    eax_post = analyzer.get_register_expr("eax", mode="post")
    analyzer.add_constraint(eax_pre != 42)
    analyzer.add_constraint(eax_post == 42)

    assert analyzer.check() == "sat"
    assert analyzer.get_expr_value(eax_post) == 42
    assert analyzer.get_expr_value(eax_pre) != 42


def test_solve_constraints_on_binary():
    """Reproducing the README keygen scenario: lift a stretch of constraint1.x86,
    constrain the two inputs and the result, and solve for inputs satisfying
    c == a + b + 5."""
    from barf import BARF

    barf = BARF(data_path("constraint1.x86"))

    for _addr, _asm, reil_instrs in barf.translate(start=0x80483ED, end=0x8048401):
        for reil_instr in reil_instrs:
            barf.code_analyzer.add_instruction(reil_instr)

    ebp = barf.code_analyzer.get_register_expr("ebp", mode="post")
    a = barf.code_analyzer.get_memory_expr(ebp - 0x8, 4, mode="pre")
    b = barf.code_analyzer.get_memory_expr(ebp - 0xC, 4, mode="pre")
    for constr in [a >= 2, a <= 100, b >= 2, b <= 100]:
        barf.code_analyzer.add_constraint(constr)

    c = barf.code_analyzer.get_memory_expr(ebp - 0x4, 4, mode="post")
    for constr in [c >= 26, c <= 28]:
        barf.code_analyzer.add_constraint(constr)

    assert barf.code_analyzer.check() == "sat"
    a_val = barf.code_analyzer.get_expr_value(a)
    b_val = barf.code_analyzer.get_expr_value(b)
    c_val = barf.code_analyzer.get_expr_value(c)
    assert a_val + b_val + 5 == c_val
    assert 2 <= a_val <= 100
    assert 26 <= c_val <= 28


# ===========================================================================
# Symbolic execution (crackme recovery)
# ===========================================================================
def test_symbolic_execution_recovers_serial():
    """Concolic execution of check_serial_1 recovers the unique 6-byte password
    that drives execution to the success branch."""
    from barf.analysis.symbolic.emulator import ReilSymbolicEmulator, State, SymExecResult
    from barf.utils.reil import ReilContainerBuilder

    binary = BinaryFile(data_path("check_serial_1"))
    arch_info = X86ArchitectureInformation(binary.architecture_mode)
    container = ReilContainerBuilder(binary).build([("check_serial", 0x0804841D, 0x08048452)])

    state = State(arch_info, mode="initial")
    esp = 0xFFFFCEEC
    state.write_register("esp", esp)
    pw_addr, pw_len = 0xDEADBEEF, 0x6
    state.write_memory(esp + 0x4, 4, pw_addr)
    state.write_memory(esp + 0x0, 4, 0x41414141)
    for i in range(pw_len):
        value = state.query_memory(pw_addr + i, 1)
        state.add_constraint(value.uge(0x21))
        state.add_constraint(value.ule(0x7E))

    sym_exec = ReilSymbolicEmulator(arch_info)
    paths = sym_exec.find_address(
        container,
        start=0x0804841D,
        end=0x08048452,
        find=0x08048451,
        avoid=[0x0804843B],
        initial_state=state,
    )
    assert len(paths) == 1

    result = SymExecResult(arch_info, state, paths[0], State(arch_info, mode="final"))
    recovered = bytearray(result.query_memory(pw_addr + i, 1) for i in range(pw_len))
    assert recovered == bytearray(b"AAAAAA")


def test_symbolic_execution_recovers_xor_serial():
    """check_serial_2 compares the input against an in-memory key XORed with a
    constant; symbolic execution recovers the serial 'serial'."""
    from barf.analysis.symbolic.emulator import ReilSymbolicEmulator, State, SymExecResult
    from barf.utils.reil import ReilContainerBuilder

    binary = BinaryFile(data_path("check_serial_2"))
    arch_info = X86ArchitectureInformation(binary.architecture_mode)
    container = ReilContainerBuilder(binary).build([("check_serial", 0x0804841D, 0x08048467)])

    state = State(arch_info, mode="initial")
    esp = 0xFFFFCEEC
    state.write_register("esp", esp)
    pw_addr, pw_len = 0xDEADBEEF, 0x6
    state.write_memory(esp + 0x8, 4, pw_len)
    state.write_memory(esp + 0x4, 4, pw_addr)
    state.write_memory(esp + 0x0, 4, 0x41414141)
    for i in range(pw_len):
        value = state.query_memory(pw_addr + i, 1)
        state.add_constraint(value.uge(0x21))
        state.add_constraint(value.ule(0x7E))

    ref_key = bytearray(b"\x31\x27\x30\x2b\x23\x2e")
    state.write_memory(0x0804A020, 4, 0xCAFECAFE)
    for i, byte in enumerate(ref_key):
        state.write_memory(0xCAFECAFE + i, 1, byte)

    sym_exec = ReilSymbolicEmulator(arch_info)
    paths = sym_exec.find_address(
        container,
        start=0x0804841D,
        end=0x08048467,
        find=0x08048466,
        avoid=[0x0804844E],
        initial_state=state,
    )
    assert len(paths) == 1

    result = SymExecResult(arch_info, state, paths[0], State(arch_info, mode="final"))
    recovered = bytearray(result.query_memory(pw_addr + i, 1) for i in range(pw_len))
    assert recovered == bytearray(b"serial")


def test_symbolic_execution_find_state_transform():
    """find_state drives the 'expand' transform of check_serial_6 to a desired
    output buffer, proving the symbolic engine matches a target memory state."""
    from barf.analysis.symbolic.emulator import ReilSymbolicEmulator, State, SymExecResult
    from barf.utils.reil import ReilContainerBuilder

    binary = BinaryFile(data_path("check_serial_6"))
    arch_info = X86ArchitectureInformation(binary.architecture_mode)
    container = ReilContainerBuilder(binary).build([("expand", 0x0804849B, 0x080484DD)])

    esp = 0xFFFFCEEC
    out_addr = 0xDEADBEEF
    in_addr = 0xDEADBEEF + 0x5

    initial = State(arch_info, mode="initial")
    initial.write_register("esp", esp)
    initial.write_memory(esp + 0x04, 4, out_addr)
    initial.write_memory(esp + 0x08, 4, in_addr)
    initial.write_memory(esp + 0x0C, 4, 0xAAAAAAAA)
    initial.write_memory(esp + 0x10, 4, 0xBBBBBBBB)
    for i, byte in enumerate(bytearray(b"\x02\x03\x05\x07")):
        initial.write_memory(in_addr + i, 1, byte)

    final = State(arch_info, mode="final")
    for i, byte in enumerate(bytearray(b"\xfc\xfb\xf5\xf7")):
        final.write_memory(out_addr + i, 1, byte)

    sym_exec = ReilSymbolicEmulator(arch_info)
    paths = sym_exec.find_state(
        container, start=0x0804849B, end=0x080484DD, initial_state=initial, final_state=final
    )
    assert len(paths) == 1

    result = SymExecResult(arch_info, initial, paths[0], final)
    assert result.query_memory(esp + 0x4, 4) == 0xDEADBEEF
    assert result.query_memory(esp + 0x8, 4) == 0xDEADBEF4


# ===========================================================================
# ROP gadgets (find / classify / verify)
# ===========================================================================
def test_find_and_classify_rop_gadgets():
    """The gadget finder locates ret-ended gadgets in raw code and the
    classifier assigns the correct semantic type (move-register, load-constant)
    with the right source/destination operands."""
    from barf.analysis.gadgets.classifier import GadgetClassifier
    from barf.analysis.gadgets.finder import GadgetFinder
    from barf.analysis.gadgets.gadget import GadgetType
    from barf.core.reil import ReilImmediateOperand, ReilRegisterOperand

    arch_info = X86ArchitectureInformation(ARCH_X86_MODE_32)
    classifier = GadgetClassifier(ReilEmulator(arch_info), arch_info)

    # mov eax, ebx ; ret
    finder = GadgetFinder(
        X86Disassembler(ARCH_X86_MODE_32),
        bytearray(b"\x89\xd8\xc3"),
        X86Translator(ARCH_X86_MODE_32),
        ARCH_X86,
        ARCH_X86_MODE_32,
    )
    candidates = finder.find(0x00000000, 0x00000002)
    assert len(candidates) >= 1

    classified_all = []
    for cand in candidates:
        classified_all.extend(classifier.classify(cand))

    move_regs = [g for g in classified_all if g.type == GadgetType.MoveRegister]
    assert any(
        g.sources == [ReilRegisterOperand("ebx", 32)]
        and g.destination == [ReilRegisterOperand("eax", 32)]
        for g in move_regs
    )

    # mov eax, 0x0 ; ret
    finder = GadgetFinder(
        X86Disassembler(ARCH_X86_MODE_32),
        bytearray(b"\xb8\x00\x00\x00\x00\xc3"),
        X86Translator(ARCH_X86_MODE_32),
        ARCH_X86,
        ARCH_X86_MODE_32,
    )
    candidates = finder.find(0x00000000, 0x00000005)
    assert len(candidates) >= 1

    classified_all = []
    for cand in candidates:
        classified_all.extend(classifier.classify(cand))

    assert any(g.type == GadgetType.LoadConstant for g in classified_all)
    load_const = next(g for g in classified_all if g.type == GadgetType.LoadConstant)
    assert load_const.sources == [ReilImmediateOperand(0x0, 32)]
    assert load_const.destination == [ReilRegisterOperand("eax", 32)]


def test_classify_xchg_yields_two_move_gadgets():
    """`xchg ebx, eax` is a corner case: it must classify as two move-register
    gadgets (each direction) because either register can be the destination."""
    from barf.analysis.gadgets.classifier import GadgetClassifier
    from barf.analysis.gadgets.finder import GadgetFinder
    from barf.analysis.gadgets.gadget import GadgetType
    from barf.core.reil import ReilRegisterOperand

    arch_info = X86ArchitectureInformation(ARCH_X86_MODE_32)
    classifier = GadgetClassifier(ReilEmulator(arch_info), arch_info)

    finder = GadgetFinder(
        X86Disassembler(ARCH_X86_MODE_32),
        bytearray(b"\x93\xc3"),
        X86Translator(ARCH_X86_MODE_32),
        ARCH_X86,
        ARCH_X86_MODE_32,
    )
    candidates = finder.find(0x00000000, 0x00000001)
    assert len(candidates) >= 1

    classified = []
    for cand in candidates:
        classified.extend(classifier.classify(cand))

    # xchg ebx, eax classifies as a move in both directions.
    assert any(
        g.type == GadgetType.MoveRegister
        and g.sources == [ReilRegisterOperand("eax", 32)]
        and g.destination == [ReilRegisterOperand("ebx", 32)]
        for g in classified
    )
    assert any(
        g.type == GadgetType.MoveRegister
        and g.sources == [ReilRegisterOperand("ebx", 32)]
        and g.destination == [ReilRegisterOperand("eax", 32)]
        for g in classified
    )


def test_verify_rop_gadget_semantics():
    """The SMT-backed verifier confirms a classified move-register gadget really
    implements its assigned semantics."""
    from barf.analysis.codeanalyzer import CodeAnalyzer
    from barf.analysis.gadgets.classifier import GadgetClassifier
    from barf.analysis.gadgets.finder import GadgetFinder
    from barf.analysis.gadgets.gadget import GadgetType
    from barf.analysis.gadgets.verifier import GadgetVerifier
    from barf.core.smt.smtsolver import Z3Solver
    from barf.core.smt.smttranslator import SmtTranslator

    arch_info = X86ArchitectureInformation(ARCH_X86_MODE_32)
    solver = Z3Solver()
    smt_translator = SmtTranslator(solver, arch_info.address_size)
    smt_translator.set_arch_alias_mapper(arch_info.alias_mapper)
    smt_translator.set_arch_registers_size(arch_info.registers_size)
    code_analyzer = CodeAnalyzer(solver, smt_translator, arch_info)

    classifier = GadgetClassifier(ReilEmulator(arch_info), arch_info)
    verifier = GadgetVerifier(code_analyzer, arch_info)

    finder = GadgetFinder(
        X86Disassembler(ARCH_X86_MODE_32),
        bytearray(b"\x89\xd8\xc3"),
        X86Translator(ARCH_X86_MODE_32),
        ARCH_X86,
        ARCH_X86_MODE_32,
    )
    candidates = finder.find(0x00000000, 0x00000002)
    assert len(candidates) >= 1

    classified = []
    for cand in candidates:
        classified.extend(classifier.classify(cand))
    assert any(g.type == GadgetType.MoveRegister for g in classified)
    move = next(g for g in classified if g.type == GadgetType.MoveRegister)
    assert verifier.verify(move) is True

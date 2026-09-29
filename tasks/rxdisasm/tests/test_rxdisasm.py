"""
Exact-output tests for the rxdisasm x86-64 (long mode) disassembler CLI.

The binary at /app/rxdisasm reads hex bytes (one instruction per line) from stdin and prints,
for each line, the single decoded instruction in the reference tool's textual syntax (or a line
starting with "ERR: " when the bytes are not a legal encoding / are truncated).

Each test feeds ONE instruction's hex on stdin and asserts the exact output line. Values were
captured from the reference decoder. No parametrize: one test function == one graded case.
"""
import subprocess

BIN = "/app/rxdisasm"


def disasm(hexstr):
    p = subprocess.run([BIN], input=hexstr + "\n", capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, f"nonzero exit {p.returncode}: {p.stderr!r}"
    lines = [l for l in p.stdout.split("\n") if l != ""]
    assert len(lines) == 1, f"expected 1 output line, got {lines!r}"
    return lines[0]


def test_000_33c0():
    assert disasm('33c0') == 'xor eax, eax'


def test_001_4801d8():
    assert disasm('4801d8') == 'add rax, rbx'


def test_002_89d8():
    assert disasm('89d8') == 'mov eax, ebx'


def test_003_8b4c2404():
    assert disasm('8b4c2404') == 'mov ecx, dword [rsp + 0x4]'


def test_004_8b0c25f0ffff():
    assert disasm('8b0c25f0ffffff') == 'mov ecx, dword [0xfffffff0]'


def test_005_488b4310():
    assert disasm('488b4310') == 'mov rax, qword [rbx + 0x10]'


def test_006_488b83200100():
    assert disasm('488b8320010000') == 'mov rax, qword [rbx + 0x120]'


def test_007_488d15f4ffff():
    assert disasm('488d15f4ffffff') == 'lea rdx, qword [rip - 0xc]'


def test_008_4c8d0d070000():
    assert disasm('4c8d0d07000000') == 'lea r9, qword [rip + 0x7]'


def test_009_8d0c48():
    assert disasm('8d0c48') == 'lea ecx, dword [rax + rcx * 2]'


def test_010_b8ffffffff():
    assert disasm('b8ffffffff') == 'mov eax, -0x1'


def test_011_48b8efbeadde():
    assert disasm('48b8efbeaddeefbeadde') == 'mov rax, -0x2152411021524111'


def test_012_c70102000000():
    assert disasm('c70102000000') == 'mov dword [rcx], 0x2'


def test_013_0fbec0():
    assert disasm('0fbec0') == 'movsx eax, al'


def test_014_0fb7c8():
    assert disasm('0fb7c8') == 'movzx ecx, ax'


def test_015_4863c1():
    assert disasm('4863c1') == 'movsxd rax, ecx'


def test_016_480fbec0():
    assert disasm('480fbec0') == 'movsx rax, al'


def test_017_660fbec0():
    assert disasm('660fbec0') == 'movsx ax, al'


def test_018_7405():
    assert disasm('7405') == 'jz $+0x5'


def test_019_7f0a():
    assert disasm('7f0a') == 'jg $+0xa'


def test_020_eb10():
    assert disasm('eb10') == 'jmp $+0x10'


def test_021_e900010000():
    assert disasm('e900010000') == 'jmp $+0x100'


def test_022_e800000000():
    assert disasm('e800000000') == 'call $+0x0'


def test_023_ff5008():
    assert disasm('ff5008') == 'call qword [rax + 0x8]'


def test_024_ffd0():
    assert disasm('ffd0') == 'call rax'


def test_025_ff10():
    assert disasm('ff10') == 'call qword [rax]'


def test_026_6a7f():
    assert disasm('6a7f') == 'push 0x7f'


def test_027_68efbeadde():
    assert disasm('68efbeadde') == 'push -0x21524111'


def test_028_d3f8():
    assert disasm('d3f8') == 'sar eax, cl'


def test_029_c1e004():
    assert disasm('c1e004') == 'shl eax, 0x4'


def test_030_f7d8():
    assert disasm('f7d8') == 'neg eax'


def test_031_f7d108():
    assert disasm('f7d108') == 'not ecx'


def test_032_d1f8():
    assert disasm('d1f8') == 'sar eax, 0x1'


def test_033_0fbb07():
    assert disasm('0fbb07') == 'btc dword [rdi], eax'


def test_034_0fab07():
    assert disasm('0fab07') == 'bts dword [rdi], eax'


def test_035_480fbae807():
    assert disasm('480fbae807') == 'bts rax, 0x7'


def test_036_0fa5c8():
    assert disasm('0fa5c8') == 'shld eax, ecx, cl'


def test_037_480fa4c108():
    assert disasm('480fa4c108') == 'shld rcx, rax, 0x8'


def test_038_0facc820():
    assert disasm('0facc820') == 'shrd eax, ecx, 0x20'


def test_039_0fc0c8():
    assert disasm('0fc0c8') == 'xadd al, cl'


def test_040_0fb1c8():
    assert disasm('0fb1c8') == 'cmpxchg eax, ecx'


def test_041_480fc708():
    assert disasm('480fc708') == 'cmpxchg16b xmmword [rax]'


def test_042_f0480fc10c25():
    assert disasm('f0480fc10c25f0ffffff') == 'lock xadd qword [0xfffffff0], rcx'


def test_043_480faf0c25f0():
    assert disasm('480faf0c25f0ffffff') == 'imul rcx, qword [0xfffffff0]'


def test_044_69c1efbeadde():
    assert disasm('69c1efbeadde') == 'imul eax, ecx, -0x21524111'


def test_045_f3480fbcc1():
    assert disasm('f3480fbcc1') == 'tzcnt rax, rcx'


def test_046_f3480fbdc1():
    assert disasm('f3480fbdc1') == 'lzcnt rax, rcx'


def test_047_f30fb8c1():
    assert disasm('f30fb8c1') == 'popcnt eax, ecx'


def test_048_f20fbdc1():
    assert disasm('f20fbdc1') == 'bsr eax, ecx'


def test_049_0fc7f0():
    assert disasm('0fc7f0') == 'rdrand eax'


def test_050_0f45c1():
    assert disasm('0f45c1') == 'cmovnz eax, ecx'


def test_051_0f4fc1():
    assert disasm('0f4fc1') == 'cmovg eax, ecx'


def test_052_0f9cc0():
    assert disasm('0f9cc0') == 'setl al'


def test_053_0f90c3():
    assert disasm('0f90c3') == 'seto bl'


def test_054_9c():
    assert disasm('9c') == 'pushf'


def test_055_0f05():
    assert disasm('0f05') == 'syscall'


def test_056_cc():
    assert disasm('cc') == 'int 0x3'


def test_057_c3():
    assert disasm('c3') == 'ret'


def test_058_5d():
    assert disasm('5d') == 'pop rbp'


def test_059_415c():
    assert disasm('415c') == 'pop r12'


def test_060_a801():
    assert disasm('a801') == 'test al, 0x1'


def test_061_660f70c14e():
    assert disasm('660f70c14e') == 'pshufd xmm0, xmm1, 0x4e'


def test_062_0f70c14e():
    assert disasm('0f70c14e') == 'pshufw mm0, mm1, 0x4e'


def test_063_f20f70c14e():
    assert disasm('f20f70c14e') == 'pshuflw xmm0, xmm1, 0x4e'


def test_064_f30f70c14e():
    assert disasm('f30f70c14e') == 'pshufhw xmm0, xmm1, 0x4e'


def test_065_660f3a0fc105():
    assert disasm('660f3a0fc105') == 'palignr xmm0, xmm1, 0x5'


def test_066_660fc5c103():
    assert disasm('660fc5c103') == 'pextrw eax, xmm1, 0x3'


def test_067_0f12c1():
    assert disasm('0f12c1') == 'movhlps xmm0, xmm1'


def test_068_f20f12c1():
    assert disasm('f20f12c1') == 'movddup xmm0, xmm1'


def test_069_660fefc1():
    assert disasm('660fefc1') == 'pxor xmm0, xmm1'


def test_070_0f28c1():
    assert disasm('0f28c1') == 'movaps xmm0, xmm1'


def test_071_660f3810c1():
    assert disasm('660f3810c1') == 'pblendvb xmm0, xmm1'


def test_072_660f38dcc1():
    assert disasm('660f38dcc1') == 'aesenc xmm0, xmm1'


def test_073_f30f38f6c1():
    assert disasm('f30f38f6c1') == 'adox eax, ecx'


def test_074_f3a4():
    assert disasm('f3a4') == 'rep movs byte es:[rdi], byte ds:[rsi]'


def test_075_f348a5():
    assert disasm('f348a5') == 'rep movs qword es:[rdi], qword ds:[rsi]'


def test_076_aa():
    assert disasm('aa') == 'stos byte es:[rdi], al'


def test_077_ac():
    assert disasm('ac') == 'lods al, byte [rsi]'


def test_078_48af():
    assert disasm('48af') == 'scas qword es:[rdi], rax'


def test_079_6766488b00():
    assert disasm('6766488b00') == 'mov rax, qword [eax]'


def test_080_0f1804251000():
    assert disasm('0f18042510000000') == 'prefetchnta zmmword [0x10]'


def test_081_0f0d0c25f0ff():
    assert disasm('0f0d0c25f0ffffff') == 'prefetchw zmmword [0xfffffff0]'


def test_082_0fae3c25f0ff():
    assert disasm('0fae3c25f0ffffff') == 'clflush zmmword [0xfffffff0]'


def test_083_0faee8():
    assert disasm('0faee8') == 'lfence'


def test_084_0fae10():
    assert disasm('0fae10') == 'ldmxcsr dword [rax]'


def test_085_0f0138():
    assert disasm('0f0138') == 'invlpg byte [rax]'


def test_086_0f01d0():
    assert disasm('0f01d0') == 'xgetbv'


def test_087_0f01c1():
    assert disasm('0f01c1') == 'vmcall'


def test_088_d9e8():
    assert disasm('d9e8') == 'fld1'


def test_089_d9ee():
    assert disasm('d9ee') == 'fldz'


def test_090_dbf1():
    assert disasm('dbf1') == 'fcomi st(0), st(1)'


def test_091_dde0():
    assert disasm('dde0') == 'fucom st(0), st(0)'


def test_092_dfe9():
    assert disasm('dfe9') == 'fucomip st(0), st(1)'


def test_093_dae9():
    assert disasm('dae9') == 'fucompp'


def test_094_dc4008():
    assert disasm('dc4008') == 'fadd st(0), qword [rax + 0x8]'


def test_095_dd5808():
    assert disasm('dd5808') == 'fstp qword [rax + 0x8], st(0)'


def test_096_db2c24():
    assert disasm('db2c24') == 'fld st(0), mword [rsp]'


def test_097_db0424():
    assert disasm('db0424') == 'fild st(0), dword [rsp]'


def test_098_de0c24():
    assert disasm('de0c24') == 'fimul st(0), word [rsp]'


def test_099_df2c24():
    assert disasm('df2c24') == 'fild st(0), qword [rsp]'


def test_100_dfe0():
    assert disasm('dfe0') == 'fnstsw ax'


def test_101_dbe3():
    assert disasm('dbe3') == 'fninit'


def test_102_d9fb():
    assert disasm('d9fb') == 'fsincos'


def test_103_def1c1():
    assert disasm('def1c1') == 'fdivrp st(1), st(0)'


def test_104_d97424f0():
    assert disasm('d97424f0') == 'fnstenv ptr [rsp - 0x10]'


def test_105_62f17c485840():
    assert disasm('62f17c48584002') == 'vaddps zmm0, zmm0, zmmword [rax + 0x80]'


def test_106_62f17c085840():
    assert disasm('62f17c0858407f') == 'vaddps xmm0, xmm0, xmmword [rax + 0x7f0]'


def test_107_62f17c285840():
    assert disasm('62f17c2858407f') == 'vaddps ymm0, ymm0, ymmword [rax + 0xfe0]'


def test_108_62f17c485840_neg():
    # negative EVEX compressed disp8: signed disp8 0x80 (-128) * N=64 (zmm full-vector) -> -0x2000
    assert disasm('62f17c48584080') == 'vaddps zmm0, zmm0, zmmword [rax - 0x2000]'


def test_109_62f17c48114a():
    assert disasm('62f17c48114a01') == 'vmovups zmmword [rdx + 0x40], zmm1'


def test_110_62f1fd481148():
    assert disasm('62f1fd4811480f') == 'vmovupd zmmword [rax + 0x3c0], zmm1'


def test_111_62f14c185810():
    assert disasm('62f14c18581001') == 'vaddps xmm2, xmm6, dword [rax]{1to4}'


def test_112_62f2fd483880():
    assert disasm('62f2fd48388001000000') == 'vpminsb zmm0, zmm0, zmmword [rax + 0x1]'


def test_113_62f2fd48388c():
    assert disasm('62f2fd48388c0000010000') == 'vpminsb zmm1, zmm0, zmmword [rax + rax * 1 + 0x100]'


def test_114_62f17c1858c1():
    assert disasm('62f17c1858c1') == 'vaddps zmm0{rn-sae}, zmm0, zmm1'


def test_115_62f14e5b58c1():
    assert disasm('62f14e5b58c1') == 'vaddss xmm0{k3}{ru-sae}, xmm6, xmm1'


def test_116_62f1ff0f10c1():
    assert disasm('62f1ff0f10c1') == 'vmovsd xmm0{k7}, xmm0, xmm1'


def test_117_62f27dcf4dc1():
    assert disasm('62f27dcf4dc1') == 'vrcp14ss xmm0{k7}{z}, xmm0, xmm1'


def test_118_62f37d482504():
    assert disasm('62f37d48250401ab') == 'vpternlogd zmm0, zmm0, zmmword [rcx + rax * 1], 0xab'


def test_119_62f34d4025c1():
    assert disasm('62f34d4025c10555') == 'vpternlogd zmm0, zmm22, zmm1, 0x5'


def test_120_62f37d485404():
    assert disasm('62f37d48540401ab') == 'vfixupimmps zmm0, zmm0, zmmword [rcx + rax * 1], 0xab'


def test_121_62f37d0803c1():
    assert disasm('62f37d0803c105') == 'valignd xmm0, xmm0, xmm1, 0x5'


def test_122_62f17c4d100a():
    assert disasm('62f17c4d100a') == 'vmovups zmm1{k5}, zmmword [rdx]'


def test_123_62f2fd48b6c1():
    assert disasm('62f2fd48b6c1') == 'vfmaddsub231pd zmm0, zmm0, zmm1'


def test_124_62f24d489ec1():
    assert disasm('62f24d489ec1') == 'vfnmsub132ps zmm0, zmm6, zmm1'


def test_125_62f2fd48adc1():
    assert disasm('62f2fd48adc1') == 'vfnmadd213sd xmm0, xmm0, xmm1'


def test_126_62f2fd487cc1():
    assert disasm('62f2fd487cc1') == 'vpbroadcastq zmm0, rcx'


def test_127_62f27d48c4c1():
    assert disasm('62f27d48c4c105') == 'vpconflictd zmm0, zmm1'


def test_128_62f37d481902():
    assert disasm('62f37d481902017f') == 'vextractf32x4 xmmword [rdx], zmm0, 0x1'


def test_129_62f37d483904():
    assert disasm('62f37d48390401ff') == 'vextracti32x4 xmmword [rcx + rax * 1], zmm0, 0xff'


def test_130_62f1fd48c60c():
    assert disasm('62f1fd48c60c2500010000ff') == 'vshufpd zmm1, zmm0, zmmword [0x100], 0xff'


def test_131_c4020508c1():
    assert disasm('c4020508c1') == 'vpsignb ymm8, ymm15, ymm9'


def test_132_c4c2f938c1():
    assert disasm('c4c2f938c1') == 'vpminsb xmm0, xmm0, xmm9'


def test_133_c5fb2ac1():
    assert disasm('c5fb2ac1') == 'vcvtsi2sd xmm0, xmm0, ecx'


def test_134_c4e2ed98c1():
    assert disasm('c4e2ed98c1') == 'vfmadd132pd ymm0, ymm2, ymm1'


def test_135_c4e37d46c131():
    assert disasm('c4e37d46c131') == 'vperm2i128 ymm0, ymm0, ymm1, 0x31'


def test_136_62f17d48587f():
    # 62f17d48587f01: not a legal encoding -> ERR line
    assert disasm('62f17d48587f01').startswith("ERR:")


def test_137_62f2fd487ac1():
    # 62f2fd487ac1: not a legal encoding -> ERR line
    assert disasm('62f2fd487ac1').startswith("ERR:")


def test_138_c4e26550c1():
    # c4e26550c1: not a legal encoding -> ERR line
    assert disasm('c4e26550c1').startswith("ERR:")


def test_139_62f14d485fc1():
    # 62f14d485fc1: not a legal encoding -> ERR line
    assert disasm('62f14d485fc1').startswith("ERR:")


def test_140_62f17cc858c1():
    # 62f17cc858c1: not a legal encoding -> ERR line
    assert disasm('62f17cc858c1').startswith("ERR:")


def test_141_0f38f8c1():
    # 0f38f8c1: not a legal encoding -> ERR line
    assert disasm('0f38f8c1').startswith("ERR:")


def test_142_c4e37cc1():
    # c4e37cc1: not a legal encoding -> ERR line
    assert disasm('c4e37cc1').startswith("ERR:")


def test_143_62b17d0958c1():
    # 62b17d0958c1: not a legal encoding -> ERR line
    assert disasm('62b17d0958c1').startswith("ERR:")

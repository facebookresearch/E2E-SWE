/* Group: asm_inst — builder instruction variants (jump, pop/pick/roll/select,
 * bytes, null, layout, cc, call_indirect, panic_if, aggregate_member,
 * array_element, value/value_stack_index, fiber_suspend, fiber_transfer).
 *
 * Each test builds a small function that exercises the instruction, executes
 * it via the VM, and asserts on observable output. The builder's internal
 * encoding is not part of the public API, so the assertion is always on
 * post-execution program state, never on the emitted bytes.
 */
#include "harness.h"
#include <lauf/asm/builder.h>
#include <lauf/asm/module.h>
#include <lauf/asm/program.h>
#include <lauf/asm/type.h>
#include <lauf/lib/fiber.h>
#include <lauf/lib/int.h>
#include <lauf/runtime/builtin.h>
#include <lauf/runtime/process.h>
#include <lauf/runtime/value.h>
#include <lauf/vm.h>

/* --- inst_jump: unconditional jump from entry to a second block. ---
 * Build: entry pushes 7, jumps to `end`, which returns. Verify vm returns 7. */
static void test_inst_jump(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("j");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "j", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b   = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_block* end   = lauf_asm_declare_block(b, 1);
        lauf_asm_inst_uint(b, 7);
        lauf_asm_inst_jump(b, end);

        lauf_asm_build_block(b, end);
        lauf_asm_inst_return(b);

        CHECK(lauf_asm_build_finish(b), "build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 7, "expected 7, got %llu", (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_pop / inst_pick / inst_roll: workflow test. ---
 * Stack ops: push (10, 20, 30), pop the middle (index 1) -> (10, 30). Then
 * pick 0 -> (10, 30, 30). Then roll 2 -> (30, 30, 10). Return top = 10. */
static void test_inst_pop_pick_roll(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("shuf");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "s", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 10);
        lauf_asm_inst_uint(b, 20);
        lauf_asm_inst_uint(b, 30);
        /* Stack: [10, 20, 30] (top=30). pop(1) removes the value at depth 1
         * (which is 20). New stack: [10, 30]. */
        lauf_asm_inst_pop(b, 1);
        /* pick(0) duplicates the top (30). Stack: [10, 30, 30]. */
        lauf_asm_inst_pick(b, 0);
        /* roll(2) moves the value at depth 2 (10) to the top. Stack: [30, 30, 10]. */
        lauf_asm_inst_roll(b, 2);
        /* Now drop the extras and leave just the top. */
        lauf_asm_inst_pop(b, 1);
        lauf_asm_inst_pop(b, 1);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "build_finish false");
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 10, "expected 10 after shuffles, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_select: multiplexer picks candidate at top index. ---
 * Build: push (100, 200, 300, 1). select(3) pops the top-idx=1 plus the 3
 * candidates and pushes the chosen one. Documented signature: x_N-1 ... x_0 idx
 * => x_idx. With candidates (300, 200, 100) from top-down and idx=1, x_1=200. */
static void test_inst_select(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("sel");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "s", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_uint(b, 100); /* x_2 (bottom-most) */
        lauf_asm_inst_uint(b, 200); /* x_1 */
        lauf_asm_inst_uint(b, 300); /* x_0 (top-most) */
        lauf_asm_inst_uint(b, 1);   /* idx */
        lauf_asm_inst_select(b, 3);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "build_finish false");
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 200, "select(idx=1) expected 200, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_bytes + inst_null: raw byte push, null push. ---
 * inst_bytes copies sizeof(lauf_uint) bytes from a pointer into a stack uint.
 * We pack the literal 0xC0FFEE_ULL and verify the reader sees the same value.
 * Then verify inst_null pushes an address whose fields match lauf_runtime_address_null. */
static void test_inst_bytes_and_null(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("bn");
    /* First a bytes-push function. */
    lauf_asm_function* fnb = lauf_asm_add_function(mod, "bytes", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fnb);
        lauf_uint payload = 0xC0FFEEULL;
        lauf_asm_inst_bytes(b, &payload);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "bytes build_finish false");
        lauf_asm_destroy_builder(b);
    }
    /* Then a null-push function returning the null address. */
    lauf_asm_function* fnn = lauf_asm_add_function(mod, "null", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fnn);
        lauf_asm_inst_null(b);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "null build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    lauf_asm_program prog_b = lauf_asm_create_program(mod, fnb);
    CHECK(lauf_vm_execute_oneshot(vm, prog_b, NULL, &out), "execute bytes returned false");
    CHECK(out.as_uint == 0xC0FFEEULL, "expected 0xC0FFEE, got 0x%llx",
          (unsigned long long)out.as_uint);

    lauf_asm_program prog_n = lauf_asm_create_program(mod, fnn);
    CHECK(lauf_vm_execute_oneshot(vm, prog_n, NULL, &out), "execute null returned false");
    /* The null address has the sentinel allocation/generation/offset triple. */
    CHECK(out.as_address.allocation == lauf_runtime_address_null.allocation,
          "null address.allocation mismatch");
    CHECK(out.as_address.generation == lauf_runtime_address_null.generation,
          "null address.generation mismatch");
    CHECK(out.as_address.offset == lauf_runtime_address_null.offset,
          "null address.offset mismatch");

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_layout: push (alignment, size) as two uints. ---
 * Documented signature: `_ => alignment:uint size:uint`. Push a layout of
 * (size=16, alignment=8) and verify the two top values on the stack are the
 * alignment and size in the documented order. */
static void test_inst_layout_push(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("lay");
    /* Return the top two values as (align, size). */
    lauf_asm_function* fn = lauf_asm_add_function(mod, "l", (lauf_asm_signature){0, 2});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_inst_layout(b, (lauf_asm_layout){16, 8});
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "build_finish false");
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out[2];
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, out), "execute returned false");
    /* out[0] = bottom-most, out[1] = top-most. Documented signature is
     * "alignment size" pushed in that order, so alignment=out[0]=8, size=out[1]=16. */
    CHECK(out[0].as_uint == 8, "expected alignment 8 at out[0], got %llu",
          (unsigned long long)out[0].as_uint);
    CHECK(out[1].as_uint == 16, "expected size 16 at out[1], got %llu",
          (unsigned long long)out[1].as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_condition_code: verify LT/LE/GT/GE/EQ/NE on a 3-way scmp result. ---
 * Build 6 functions each named after the code; call scmp(a, b) and cc(CODE);
 * verify each returns 1 or 0 as expected. Because scmp(3, 7) = -1 (3<7):
 *   CC_LT -> 1, CC_LE -> 1, CC_GT -> 0, CC_GE -> 0, CC_EQ -> 0, CC_NE -> 1. */
static void test_inst_condition_codes(void)
{
    struct
    {
        const char*                  name;
        lauf_asm_inst_condition_code cc;
        lauf_uint                    expected;
    } cases[] = {
        {"lt", LAUF_ASM_INST_CC_LT, 1},
        {"le", LAUF_ASM_INST_CC_LE, 1},
        {"gt", LAUF_ASM_INST_CC_GT, 0},
        {"ge", LAUF_ASM_INST_CC_GE, 0},
        {"eq", LAUF_ASM_INST_CC_EQ, 0},
        {"ne", LAUF_ASM_INST_CC_NE, 1},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i)
    {
        lauf_asm_module*   mod = lauf_asm_create_module(cases[i].name);
        lauf_asm_function* fn
            = lauf_asm_add_function(mod, cases[i].name, (lauf_asm_signature){0, 1});
        {
            lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
            lauf_asm_build(b, mod, fn);
            lauf_asm_inst_sint(b, 3);
            lauf_asm_inst_sint(b, 7);
            lauf_asm_inst_call_builtin(b, lauf_lib_int_scmp);
            lauf_asm_inst_cc(b, cases[i].cc);
            lauf_asm_inst_return(b);
            CHECK(lauf_asm_build_finish(b), "cc %s build_finish false", cases[i].name);
            lauf_asm_destroy_builder(b);
        }
        lauf_asm_program prog = lauf_asm_create_program(mod, fn);
        lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
        lauf_runtime_value out;
        CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "cc %s execute returned false",
              cases[i].name);
        CHECK(out.as_uint == cases[i].expected, "cc %s: expected %llu got %llu",
              cases[i].name, (unsigned long long)cases[i].expected,
              (unsigned long long)out.as_uint);
        lauf_destroy_vm(vm);
        lauf_asm_destroy_module(mod);
    }
}

/* --- inst_call_indirect: pop function-address, call it. ---
 * Build helper `add1(x) => x+1`. Build caller: push_fn_addr(add1), push 41,
 * call_indirect(1 => 1). Documented signature: `in_N ... in_0 f => out_M ...`.
 * That means the fn address must be on TOP of stack, arguments below it —
 * so we push arguments FIRST, then the function address LAST. */
static void test_inst_call_indirect(void)
{
    lauf_asm_module*   mod  = lauf_asm_create_module("ci");
    lauf_asm_function* add1 = lauf_asm_add_function(mod, "add1", (lauf_asm_signature){1, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, add1);
        lauf_asm_inst_uint(b, 1);
        lauf_asm_inst_call_builtin(b, lauf_lib_int_uadd(LAUF_LIB_INT_OVERFLOW_WRAP));
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "add1 build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_function* caller
        = lauf_asm_add_function(mod, "caller", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, caller);
        /* Signature says fn addr goes on top: push arg first, then fn. */
        lauf_asm_inst_uint(b, 41);
        lauf_asm_inst_function_addr(b, add1);
        lauf_asm_inst_call_indirect(b, (lauf_asm_signature){1, 1});
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "caller build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program prog = lauf_asm_create_program(mod, caller);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 42, "expected add1(41)=42, got %llu", (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_panic_if: conditional panic. ---
 * Build panic_if(cond, msg): if cond is 0, does not panic; if non-zero, panics.
 * We do two calls with the same function via input arg: cond=0 → execute
 * returns true; cond=1 → execute returns false and panic handler fires. */
static int g_panic_if_called;
static void panic_if_handler(void* u, lauf_runtime_process* p, const char* msg)
{
    (void)u;
    (void)p;
    (void)msg;
    g_panic_if_called = 1;
}

static void test_inst_panic_if(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("pif");
    /* signature (cond, ) -> () */
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "pif", (lauf_asm_signature){1, 0});
    lauf_asm_global*   msg = NULL;
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* Stack in: [cond]. Push a message address, then reorder to
         * (cond, msg) — signature is `cond msg => _`, so cond is bottom. */
        msg = lauf_asm_build_string_literal(b, "boom");
        lauf_asm_inst_global_addr(b, msg);
        lauf_asm_inst_panic_if(b);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "build_finish false");
        lauf_asm_destroy_builder(b);
    }
    CHECK(msg != NULL, "build_string_literal returned NULL");

    lauf_vm*             vm = lauf_create_vm(lauf_default_vm_options);
    lauf_vm_panic_handler h = {NULL, panic_if_handler};
    lauf_vm_set_panic_handler(vm, h);

    /* cond = 0: no panic, execute returns true. */
    g_panic_if_called = 0;
    lauf_asm_program prog0   = lauf_asm_create_program(mod, fn);
    lauf_runtime_value in    = {.as_uint = 0};
    int              ok0     = lauf_vm_execute_oneshot(vm, prog0, &in, NULL);
    CHECK(ok0, "expected panic_if(cond=0) to NOT panic, got execute=false");
    CHECK(g_panic_if_called == 0, "panic handler should NOT be called on cond=0");

    /* cond = non-zero: panic, execute returns false. */
    g_panic_if_called = 0;
    lauf_asm_program prog1 = lauf_asm_create_program(mod, fn);
    in.as_uint             = 1;
    int              ok1   = lauf_vm_execute_oneshot(vm, prog1, &in, NULL);
    CHECK(!ok1, "expected panic_if(cond=1) to panic, got execute=true");
    CHECK(g_panic_if_called == 1, "panic handler should be called on cond=1");

    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_aggregate_member: compute address of a struct field. ---
 * Build aggregate {u64, u64, u64}, ptr to local, aggregate_member(index=2,
 * layouts, 3). Store 0xAAAA at that member, load it back, return. */
static void test_inst_aggregate_member(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("agg");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "a", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_layout members[3]
            = {{8, 8}, {8, 8}, {8, 8}};
        lauf_asm_layout agg_layout = lauf_asm_aggregate_layout(members, 3);
        lauf_asm_local* loc        = lauf_asm_build_local(b, agg_layout);

        /* Write 0xAAAA into member 2 (top field). */
        lauf_asm_inst_uint(b, 0xAAAA);
        lauf_asm_inst_local_addr(b, loc);
        lauf_asm_inst_aggregate_member(b, 2, members, 3);
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);

        /* Read back from same member. */
        lauf_asm_inst_local_addr(b, loc);
        lauf_asm_inst_aggregate_member(b, 2, members, 3);
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0);

        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "build_finish false");
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 0xAAAA, "expected 0xAAAA, got 0x%llx",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_array_element: compute address of the i-th element of an array. ---
 * Build array[4] of u64, ptr to local. array_element(idx=2) then store 0xBBBB
 * there, load it back, return. */
static void test_inst_array_element(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("arr");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "a", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        lauf_asm_layout element   = {8, 8};
        lauf_asm_layout arr_layout = lauf_asm_array_layout(element, 4);
        lauf_asm_local* loc        = lauf_asm_build_local(b, arr_layout);

        /* Store 0xBBBB into arr[2]. array_element consumes (ptr, index), so
         * push ptr then push index. */
        lauf_asm_inst_uint(b, 0xBBBB);        /* value */
        lauf_asm_inst_local_addr(b, loc);     /* ptr */
        lauf_asm_inst_sint(b, 2);             /* index */
        lauf_asm_inst_array_element(b, element);
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);

        /* Read back arr[2]. */
        lauf_asm_inst_local_addr(b, loc);
        lauf_asm_inst_sint(b, 2);
        lauf_asm_inst_array_element(b, element);
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "build_finish false");
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 0xBBBB, "expected 0xBBBB, got 0x%llx",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_value + inst_value_stack_index: stable value id. ---
 * Get a stable id for a value at the current position, then push another
 * value on top; verify inst_value_stack_index returns the correct new index
 * (should be 1, since we pushed one new element on top). */
static void test_inst_value_stable_id(void)
{
    lauf_asm_module*   mod = lauf_asm_create_module("vi");
    lauf_asm_function* fn  = lauf_asm_add_function(mod, "v", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, fn);
        /* Push 100, get its stable id. */
        lauf_asm_inst_uint(b, 100);
        lauf_asm_value id100 = lauf_asm_inst_value(b, 0);

        /* Push 200 on top. Stack: [100, 200]. 100 is now at index 1. */
        lauf_asm_inst_uint(b, 200);
        uint16_t idx_of_100 = lauf_asm_inst_value_stack_index(b, id100);
        CHECK(idx_of_100 == 1,
              "expected inst_value_stack_index to report 100 at depth=1, got %u",
              (unsigned)idx_of_100);

        /* Roll the id100 to top by (idx_of_100). Stack ends: [200, 100]. */
        lauf_asm_inst_roll(b, idx_of_100);
        /* Drop the 200 below, leave 100. */
        lauf_asm_inst_pop(b, 1);
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "build_finish false");
        lauf_asm_destroy_builder(b);
    }
    lauf_asm_program prog = lauf_asm_create_program(mod, fn);
    lauf_vm*           vm = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out), "execute returned false");
    CHECK(out.as_uint == 100, "expected top=100 after value-id-driven roll, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

/* --- inst_fiber_suspend + inst_fiber_transfer. ---
 * fiber_suspend's stack effect is build-checked here (its runtime dispatch is
 * exercised by the lib_fiber suite); fiber_transfer's runtime effect is driven
 * end-to-end via the canonical two-fiber transfer-and-back idiom and observed
 * at the resume point. */
static void test_inst_fiber_suspend_and_transfer(void)
{
    /* fiber_suspend build-acceptance: a (0 => 0) function that pushes 33 and
     * suspends (1 => 0) (passing 33 to the resumer, expecting nothing back)
     * must build and be defined. */
    {
        lauf_asm_module*   mod = lauf_asm_create_module("f");
        lauf_asm_function* sus = lauf_asm_add_function(mod, "sus", (lauf_asm_signature){0, 0});
        lauf_asm_builder*  b   = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, sus);
        lauf_asm_inst_uint(b, 33);
        lauf_asm_inst_fiber_suspend(b, (lauf_asm_signature){1, 0});
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "sus build_finish false");
        lauf_asm_destroy_builder(b);
        CHECK(lauf_asm_function_has_definition(sus),
              "sus function should be defined after build_finish");
        lauf_asm_destroy_module(mod);
    }

    /* fiber_transfer runtime effect: `main` stores its own fiber handle in a
     * global, creates a generator fiber, and transfers control to it expecting
     * one value back. The generator loads main's handle and transfers the value
     * 77 back to main; main resumes with 77 on its stack and returns it. */
    lauf_asm_module* mod = lauf_asm_create_module("xf");

    lauf_asm_global* handle_g = lauf_asm_add_global(mod, LAUF_ASM_GLOBAL_READ_WRITE);
    lauf_asm_define_data_global(mod, handle_g, (lauf_asm_layout){8, 8}, NULL);

    lauf_asm_function* gen = lauf_asm_add_function(mod, "gen", (lauf_asm_signature){0, 0});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, gen);
        lauf_asm_inst_global_addr(b, handle_g);
        lauf_asm_inst_load_field(b, lauf_asm_type_value, 0); /* [main_handle] */
        lauf_asm_inst_uint(b, 77);                           /* [main_handle, 77] */
        lauf_asm_inst_fiber_transfer(b, (lauf_asm_signature){1, 0});
        lauf_asm_inst_return(b); /* unreachable: control transfers away above */
        CHECK(lauf_asm_build_finish(b), "gen build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_function* mainfn = lauf_asm_add_function(mod, "main", (lauf_asm_signature){0, 1});
    {
        lauf_asm_builder* b = lauf_asm_create_builder(lauf_asm_default_build_options);
        lauf_asm_build(b, mod, mainfn);
        /* Store the current (main) fiber handle so the generator can find it. */
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_current); /* [main_handle] */
        lauf_asm_inst_global_addr(b, handle_g);                /* [main_handle, gaddr] */
        lauf_asm_inst_store_field(b, lauf_asm_type_value, 0);  /* [] */
        /* Create the generator and transfer to it, expecting one value back. */
        lauf_asm_inst_function_addr(b, gen);                  /* [gen_fnaddr] */
        lauf_asm_inst_call_builtin(b, lauf_lib_fiber_create); /* [gen_handle] */
        lauf_asm_inst_fiber_transfer(b, (lauf_asm_signature){0, 1}); /* [77] */
        lauf_asm_inst_return(b);
        CHECK(lauf_asm_build_finish(b), "main build_finish false");
        lauf_asm_destroy_builder(b);
    }

    lauf_asm_program   prog = lauf_asm_create_program(mod, mainfn);
    lauf_vm*           vm   = lauf_create_vm(lauf_default_vm_options);
    lauf_runtime_value out;
    CHECK(lauf_vm_execute_oneshot(vm, prog, NULL, &out),
          "execute of fiber_transfer scenario returned false");
    CHECK(out.as_uint == 77, "expected transferred value 77 observed at resume, got %llu",
          (unsigned long long)out.as_uint);
    lauf_destroy_vm(vm);
    lauf_asm_destroy_module(mod);
}

static const TestEntry TESTS[] = {
    {"test_inst_jump", test_inst_jump},
    {"test_inst_pop_pick_roll", test_inst_pop_pick_roll},
    {"test_inst_select", test_inst_select},
    {"test_inst_bytes_and_null", test_inst_bytes_and_null},
    {"test_inst_layout_push", test_inst_layout_push},
    {"test_inst_condition_codes", test_inst_condition_codes},
    {"test_inst_call_indirect", test_inst_call_indirect},
    {"test_inst_panic_if", test_inst_panic_if},
    {"test_inst_aggregate_member", test_inst_aggregate_member},
    {"test_inst_array_element", test_inst_array_element},
    {"test_inst_value_stable_id", test_inst_value_stable_id},
    {"test_inst_fiber_suspend_and_transfer", test_inst_fiber_suspend_and_transfer},
};

int main(int argc, char** argv)
{
    lauf_harness_touch();
    const char* out = argc > 1 ? argv[1] : "/tmp/frag_asm_inst.json";
    return lauf_run_group(TESTS, (int)(sizeof(TESTS) / sizeof(*TESTS)), out) >= 0 ? 0 : 1;
}

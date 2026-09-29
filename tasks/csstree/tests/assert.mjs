// Minimal assertion helpers for stylesheet-tree capability drivers. Kept dependency-free so the
// harness needs nothing beyond Node. A failing assertion throws; the runner records the throw as a
// failed CTRF case.

export function assert(cond, msg) {
    if (!cond) {
        throw new Error(msg || 'assertion failed');
    }
}

export function assertEqual(actual, expected, msg) {
    if (actual !== expected) {
        throw new Error(
            `${msg ? msg + ': ' : ''}expected ${JSON.stringify(expected)} but got ${JSON.stringify(actual)}`,
        );
    }
}

// Deep structural equality with stable, order-sensitive object-key comparison and clear diffs.
export function assertDeepEqual(actual, expected, msg) {
    const a = stable(actual);
    const e = stable(expected);
    if (a !== e) {
        throw new Error(`${msg ? msg + ': ' : ''}deep-equal mismatch\n  expected: ${e}\n  actual:   ${a}`);
    }
}

export function assertThrows(fn, msg) {
    let threw = false;
    let err;
    try {
        fn();
    } catch (e) {
        threw = true;
        err = e;
    }
    if (!threw) {
        throw new Error(msg || 'expected function to throw, but it did not');
    }
    return err;
}

// JSON with sorted keys so object property order never causes a spurious mismatch.
function stable(v) {
    return JSON.stringify(sortKeys(v));
}

function sortKeys(v) {
    if (Array.isArray(v)) {
        return v.map(sortKeys);
    }
    if (v && typeof v === 'object') {
        const out = {};
        for (const k of Object.keys(v).sort()) {
            out[k] = sortKeys(v[k]);
        }
        return out;
    }
    return v;
}

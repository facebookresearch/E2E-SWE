/* eslint-env jest */
// Degenerate geometry and floating-point robustness. These are the cases where a naive
// implementation diverges: near-vertical segment splits, consistent rounding of a near-vertical
// intersection, and a very-small-but-non-degenerate polygon surviving the rounder. Each is driven
// via a multi-argument or single-argument public call (a code path the single-MultiPolygon fixtures
// do not exercise); coordinates and results are taken verbatim from the reference so the rounding
// contract is pinned exactly.

import polygonClipping from "planar-boolean"
import "./canonical.js"

describe("degenerate geometry and numerical robustness", () => {
  test("splitting a near-vertical segment produces the exact rounded intersection point", () => {
    // Two triangles sharing the origin; one has a near-vertical left edge whose x differs only in
    // the last floating-point digits. The split point on that edge must be computed at the exact
    // documented coordinate rather than drifting.
    const a = [
      [
        [-10.000000000000002, 2],
        [-9.999999999999996, -3],
        [0, 0],
        [-10.000000000000002, 2],
      ],
    ]
    const b = [
      [
        [-11, 2],
        [0, 0],
        [-10, 10],
        [-11, 2],
      ],
    ]
    expect(polygonClipping.union(a, b)).toEqualMultiPolygon([
      [
        [
          [-11, 2],
          [-10.000000000000002, 1.8181818181818183],
          [-9.999999999999996, -3],
          [0, 0],
          [-10.000000000000002, 10],
          [-11, 2],
        ],
      ],
    ])
  })

  test("a near-vertical intersection is rounded consistently to avoid a spurious sliver", () => {
    const a = [
      [
        [-0.1, 49],
        [0.1, 49],
        [-0.1, 50],
        [-0.1, 49],
      ],
    ]
    const b = [
      [
        [-1.1741342, 50.6250111],
        [0.0001, 49.32584697546245],
        [0.0001, 50.6251],
        [-1.1741342, 50.6250111],
      ],
    ]
    expect(polygonClipping.union(a, b)).toEqualMultiPolygon([
      [
        [
          [-1.1741342, 50.6250111],
          [-0.1, 49.43659688282012],
          [-0.1, 49],
          [0.1, 49],
          [0.0001, 49.4995],
          [0.0001, 50.6251],
          [-1.1741342, 50.6250111],
        ],
      ],
    ])
  })

  test("a very small but non-degenerate polygon survives rounding intact", () => {
    // A sub-micro-degree triangle (real-world lat/long). Its area is tiny but non-zero, so the
    // rounder must not collapse it. Output equals the (self-closed) input triangle.
    const tiny = [
      [
        [-122.3793225342952, 37.708405012714316],
        [-122.3793225, 37.708405],
        [-122.37932240498668, 37.70840501108731],
        [-122.3793225342952, 37.708405012714316],
      ],
    ]
    expect(polygonClipping.union(tiny)).toEqualMultiPolygon([
      [
        [
          [-122.3793225342952, 37.708405012714316],
          [-122.3793225, 37.708405],
          [-122.37932240498668, 37.70840501108731],
          [-122.3793225342952, 37.708405012714316],
        ],
      ],
    ])
  })
})

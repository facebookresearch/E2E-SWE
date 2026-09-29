/* eslint-env jest */
// Advanced topology: the non-zero winding rule for a self-crossing ring. This stresses the winding
// bookkeeping and ring-assembly corners that a naive even-odd engine gets wrong.

import polygonClipping from "planar-boolean"
import "./canonical.js"

describe("advanced topology", () => {
  test("a self-crossing ring is interpreted by the non-zero rule", () => {
    // A single ring shaped like a four-pointed star that crosses itself at the center. Under the
    // non-zero rule the four petals are solid and meet only at the center point, giving four
    // triangles (not an even-odd hole in the middle).
    const star = [
      [
        [0, 1],
        [2, 2],
        [1, 0],
        [3, 0],
        [2, 2],
        [4, 1],
        [4, 3],
        [2, 2],
        [3, 4],
        [1, 4],
        [2, 2],
        [0, 3],
        [0, 1],
      ],
    ]
    expect(polygonClipping.union(star)).toEqualMultiPolygon([
      [
        [
          [0, 1],
          [2, 2],
          [0, 3],
          [0, 1],
        ],
      ],
      [
        [
          [1, 0],
          [3, 0],
          [2, 2],
          [1, 0],
        ],
      ],
      [
        [
          [1, 4],
          [2, 2],
          [3, 4],
          [1, 4],
        ],
      ],
      [
        [
          [2, 2],
          [4, 1],
          [4, 3],
          [2, 2],
        ],
      ],
    ])
  })
})

/* eslint-env jest */
// Input normalization: the engine accepts loosely-specified GeoJSON and normalizes it. Each test
// pins one documented input tolerance and asserts the cleaned output it produces.

import polygonClipping from "planar-boolean"
import "./canonical.js"

describe("input normalization", () => {
  test("portions of interior rings outside their exterior ring are dropped", () => {
    // Three inner rings, each partly or wholly outside the 7x7 outer ring. Only the in-bounds parts
    // survive, cut into the exterior boundary; the fully-outside ring vanishes entirely.
    const poly = [
      [
        [0, 0],
        [7, 0],
        [7, 7],
        [0, 7],
        [0, 0],
      ],
      [
        [6, 1],
        [6, 2],
        [8, 2],
        [8, 1],
        [6, 1],
      ],
      [
        [6, 3],
        [6, 4],
        [7, 4],
        [7, 3],
        [6, 3],
      ],
      [
        [7, 5],
        [7, 6],
        [8, 6],
        [8, 5],
        [7, 5],
      ],
    ]
    expect(polygonClipping.union(poly)).toEqualMultiPolygon([
      [
        [
          [0, 0],
          [7, 0],
          [7, 1],
          [6, 1],
          [6, 2],
          [7, 2],
          [7, 3],
          [6, 3],
          [6, 4],
          [7, 4],
          [7, 7],
          [0, 7],
          [0, 0],
        ],
      ],
    ])
  })
})

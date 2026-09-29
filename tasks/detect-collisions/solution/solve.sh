#!/bin/bash
set -e

# Ground-truth assembly for the geom2d WRG task. The reference implementation is
# Prozi/detect-collisions (npm "check2d"). Cloning it is the ONLY network operation in the GT
# flow (GT keeps internet on in Container A for this; the grading container is offline).
# git is pre-baked in the per-task image.
git clone https://github.com/Prozi/detect-collisions.git /tmp/repo
cd /tmp/repo
git checkout 51a0b7b7

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# Overwrite the repo's own src/index.ts with a thin adapter facade that re-exports the reference
# classes/functions under the neutral geom2d public API the hidden tests import. Subclass the
# collision world so the renamed methods (addDisc, overlaps, resolveAll, castRay, ...) forward to
# the reference methods; passing `undefined` through preserves the reference's default parameters.
# The tests import ONLY from /app/src/index.ts, exactly like the agent's deliverable.
cat > /app/src/index.ts <<'FACADE'
// geom2d public API (ground-truth adapter over the reference implementation).
import { System } from './system'
import { Circle } from './bodies/circle'
import { Box } from './bodies/box'
import { Polygon } from './bodies/polygon'
import { Ellipse } from './bodies/ellipse'
import { Line } from './bodies/line'
import { Point } from './bodies/point'
import { deg2rad, rad2deg, groupBits, canInteract } from './utils'
import {
  intersectLineLine,
  intersectLineCircle,
  intersectCircleCircle,
  intersectPolygonPolygon,
  circleInPolygon,
  circleOutsidePolygon,
  pointInPolygon,
  polygonInPolygon,
  circleInCircle
} from './intersect'

// body colliders
export {
  Circle as Disc,
  Box as Rect,
  Polygon as Poly,
  Ellipse as Oval,
  Line as Segment,
  Point as Dot
}

// math + collision-filtering helpers
export { deg2rad, rad2deg, groupBits, canInteract }

// intersection-geometry helpers
export {
  intersectLineLine as intersectSegments,
  intersectLineCircle as intersectSegmentDisc,
  intersectCircleCircle as intersectDiscDisc,
  intersectPolygonPolygon as intersectPolys,
  circleInPolygon as discInPoly,
  circleOutsidePolygon as discOutsidePoly,
  pointInPolygon as dotInPoly,
  polygonInPolygon as polyInPoly,
  circleInCircle as discInDisc
}

// collision world
export class CollisionWorld extends System {
  addDisc(position: any, radius: any, options?: any) {
    return this.createCircle(position, radius, options)
  }
  addRect(position: any, width: any, height: any, options?: any) {
    return this.createBox(position, width, height, options)
  }
  addPoly(position: any, points: any, options?: any) {
    return this.createPolygon(position, points, options)
  }
  addOval(position: any, radiusX: any, radiusY?: any, step?: any, options?: any) {
    return this.createEllipse(position, radiusX, radiusY, step, options)
  }
  addSegment(start: any, end: any, options?: any) {
    return this.createLine(start, end, options)
  }
  addDot(position: any, options?: any) {
    return this.createPoint(position, options)
  }
  overlaps(bodyA: any, bodyB: any, response?: any) {
    return this.checkCollision(bodyA, bodyB, response)
  }
  resolveAll(callback?: any, response?: any) {
    return this.checkAll(callback, response)
  }
  resolveOne(body: any, callback?: any, response?: any) {
    return this.checkOne(body, callback, response)
  }
  resolveArea(area: any, callback?: any, response?: any) {
    return this.checkArea(area, callback, response)
  }
  contactPoints(a: any, b: any) {
    return this.getCollisionPoints(a, b)
  }
  castRay(start: any, end: any, allow?: any) {
    return this.raycast(start, end, allow)
  }
  pushApart(callback?: any, response?: any) {
    return this.separate(callback, response)
  }
}
FACADE

# setup.sh is SOURCED (offline) by the grading harness before the tests run, so it must not call
# `exit`. There is no build step: the tests import /app/src/index.ts directly under tsx. The
# runtime deps (sat, poly-decomp-es) are pre-baked at the image's root /node_modules, which
# Node/esbuild module resolution reaches by walking up from /app/src, so setup.sh is a no-op.
cat > /app/setup.sh <<'EOF'
#!/bin/bash
# No build step: the tests import /app/src/index.ts directly under tsx; runtime deps resolve
# from the image's /node_modules. Nothing to install (offline).
:
EOF
chmod +x /app/setup.sh

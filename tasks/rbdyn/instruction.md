# RBDyn (narrow slice)

Implement a set of `.cpp` files inside a partially-scaffolded C++17 build of
the **RBDyn** rigid-body dynamics library.

RBDyn is a Featherstone-style articulated rigid-body kinematics/dynamics
library. It represents robots as a kinematic tree of `Body`s connected by
`Joint`s and computes forward/inverse kinematics and dynamics on that tree.

Most of the library (the base kinematics/dynamics: `FK`/`FV`/`FA`/`ID`/`FD`/
`CoM`/`Momentum`/`VisServo`/`ZMP`/`MultiBody`/etc.) is **already built** and
installed as a static library on the system — you link against it. Your job
is to implement a specific subset of algorithms that sit on top of that
base: a small non-textbook cluster (inverse-dynamics identification,
Bjerkeng-Pettersen Coriolis) and two core kinematic building blocks (the
geometric-Jacobian class and `MultiBodyConfig` numerical integration).

## Domain glossary

If any of these terms are unfamiliar, this short primer keeps everything
self-contained:

- **Rigid body** — an idealized solid with mass, a center-of-mass position,
  and an inertia tensor about that center. Represented by `sva::RBInertiad`
  (mass, momentum `m·h`, 3×3 inertia matrix `I`).
- **Kinematic tree** — a tree of bodies connected by joints. The root is a
  distinguished body (fixed to the world, or free-floating). Each non-root
  body has exactly one parent joint that specifies how it can move relative
  to its parent.
- **Joint** — a mechanical connection with a fixed motion subspace. Common
  types: revolute (1-DOF rotational), prismatic (1-DOF translational),
  spherical (3-DOF ball), free (6-DOF unconstrained), fixed (0-DOF weld).
- **Spatial (6D) vector algebra** — combines linear and angular quantities
  into a single 6-vector. RBDyn uses the `SpaceVecAlg` library:
    - `sva::MotionVecd` = `[angular; linear]` velocity or acceleration
    - `sva::ForceVecd`  = `[couple; force]`
    - `sva::PTransformd` = rigid body transform (rotation + translation)
    - `sva::RBInertiad`  = rigid body spatial inertia (mass, momentum, 3x3 inertia)
- **DOF / nrDof / nrParams** — a `MultiBody` reports its total degrees of
  freedom (`nrDof()`) and its total configuration-parameter count
  (`nrParams()`). For a spherical joint parametrized by quaternion, `dof =
  3` but `params = 4`; for a revolute joint both equal 1.

### `sva::PTransformd(E, r)` convention

Following Featherstone / Plücker: `E` is the 3×3 rotation from the OLD
frame to the NEW frame (i.e. `E * v_old = v_new` for a plain 3-vector),
and `r` is the translation vector stored in the OLD frame's coordinates.
For a motion vector `mv = (w, v)`:
  `X * mv = MotionVecd(E * w, E * (v - r × w))`.
Concretely for `mbc.bodyPosW[i] = PTransformd(E_i, r_i)`:
  - `E_i` = rotation from world (old) to body_i (new),
  - `r_i` = position of body_i's origin, expressed in world coordinates
    (= `mbc.bodyPosW[i].translation()`).
Inverse: `X.inv() = PTransformd(E^T, -E * r)`.
The transpose `X.transMul(fv)` applies the force-side dual transform;
`X.dualMul(fv)` applies the force-side transform with the same rotation
but sign-adjusted translation piece — see `SpaceVecAlg/PTransform.h`
for the exact algebra.

## Scope (files you implement)

You implement exactly these four `.cpp` files under `/app/src/RBDyn/`.
Do **not** create or modify any other `.cpp` file in `src/RBDyn/`.

| File | Adds |
|---|---|
| `IDIM.cpp`                 | Inverse-Dynamics Identification Model — `IMPhi`, `inertiaToVector`, `vectorToInertia`, `sVectorToInertia`, `multiBodyToInertialVector`, and the `IDIM` class. |
| `Coriolis.cpp`             | Coriolis matrix (Bjerkeng-Pettersen factorization) — the `Coriolis` class. |
| `Jacobian.cpp`             | Per-body geometric Jacobian — the `rbd::Jacobian` class (world + body Jacobian, JDot, translate, sub-multi-body extraction, vector-point Jacobian, compact-path expand). Plus the `Jacobian::compactPath`, `Jacobian::expand`, `Jacobian::expandAdd` members. |
| `NumericalIntegration.cpp` | Numerical integration of `MultiBodyConfig` — `rbd::integration(mb, mbc, step)` (Euler for revolute/prismatic/planar/cylindrical, exponential-map / quaternion normalization for spherical + free flyer). |

The headers for all of these (`RBDyn/IDIM.h`, `RBDyn/Coriolis.h`,
`RBDyn/Jacobian.h`, `RBDyn/NumericalIntegration.h`) are **already
installed** at `/usr/local/include/RBDyn/`. Do not create or edit them.

## Fixture library (already provided)

All the base kinematics/dynamics classes and functions the four narrow
RBDyn `.cpp` files depend on are prebuilt into a static archive at:

```
/opt/rbdyn_fixture/lib/libRBDyn_core.a
```

That archive supplies definitions for every symbol in the following headers
(available at `/usr/local/include/RBDyn/`):

- `MultiBody.h`, `MultiBodyConfig.h`, `MultiBodyGraph.h`, `Body.h`, `Joint.h`
- `FK.h`, `FV.h`, `FA.h`  (forward kinematics / velocity / acceleration)
- `ID.h`, `FD.h`, `IK.h`, `IS.h`  (inverse & forward dynamics, inverse kinematics, inverse statics)
- `CoM.h`  (center-of-mass Jacobian)
- `Momentum.h`  (centroidal momentum + `CentroidalMomentumMatrix`)
- `VisServo.h`  (image Jacobians for visual servoing)
- `ZMP.h`  (Zero Moment Point)
- `util.hh`, `util.hxx`  (small template helpers e.g. `vectorToParam`, `paramToVector`, `vectorToCrossMatrix`, `checkMatch*`)

You freely `#include` any of those and call any of their public functions
from your own `.cpp` files. Every `sva::` type is available through
`#include <SpaceVecAlg/SpaceVecAlg>` (installed at `/usr/local/include/`).

The `rbdyn/config.hh` header (installed at `/usr/local/include/rbdyn/`) is
where the `RBDYN_DLLAPI` and related visibility macros are defined; you do
not need to touch it.

## Install / build contract

`setup.sh` (which you author at `/app/setup.sh`) must produce four object
files, one per source file, at these exact paths:

```
/app/build/rbdyn_narrow/IDIM.o
/app/build/rbdyn_narrow/Coriolis.o
/app/build/rbdyn_narrow/Jacobian.o
/app/build/rbdyn_narrow/NumericalIntegration.o
```

Each object must be compiled with `g++ -std=c++17 --coverage -fPIC` (or
equivalent — `--coverage` is required, `-fPIC` is required because the
downstream link uses PIE by default). A minimal `setup.sh` template that
compiles each file independently:

```bash
#!/bin/bash
set -e
mkdir -p /app/build/rbdyn_narrow
FLAGS="-std=c++17 -O0 -g --coverage -fPIC -I/usr/local/include -I/usr/include/eigen3"
for src in /app/src/RBDyn/{IDIM,Coriolis,Jacobian,NumericalIntegration}.cpp; do
    obj=/app/build/rbdyn_narrow/$(basename "${src%.cpp}").o
    g++ $FLAGS -Drbdyn_EXPORTS -c "$src" -o "$obj"
done
```

Do **not** try to link the objects into a shared or static library and do
not create additional `.o` files anywhere else. Downstream code
compiles+links the objects listed above against the fixture archive plus
system libraries (`-lboost_*`).

Runtime dependencies pre-installed on the system (you do not `apt-get`):

- Eigen 3 (headers at `/usr/include/eigen3/`)
- Boost — variant, Test (`unit_test_framework`), Filesystem
- SpaceVecAlg (headers and shared lib installed under `/usr/local/`)

## Namespaces + header layout

Everything you write lives in `namespace rbd`. Match the headers exactly.

Standard include layout for a narrow-RBDyn `.cpp`:

```cpp
#include "RBDyn/IDIM.h"           // associated header, first
#include "RBDyn/MultiBody.h"      // any fixture headers you use
#include "RBDyn/MultiBodyConfig.h"
// ...
```

---

# RBDyn narrow-scope files

## `IDIM.cpp` — inverse-dynamics identification

The inverse-dynamics identification model (IDIM) linearizes the equation of
motion in the **inertial parameters** of each body. Every rigid body has a
10-dimensional inertial parameter vector

```
phi_i = [ m , m·h_x , m·h_y , m·h_z , I_xx , I_xy , I_xz , I_yy , I_yz , I_zz ]
```

where `m` is the mass, `m·h` is the linear momentum contribution (mass times
center-of-mass offset), and the six `I_**` are the upper triangle of the
3×3 inertia matrix expressed at the body origin. The joint-space torque
vector `tau` can be written as `tau = Y(q, qd, qdd) · Phi`, where `Phi` is
the concatenation `[phi_0; phi_1; …; phi_{N-1}]` of the per-body inertial
parameter vectors and `Y` is a `nrDof × 10·nrBodies` matrix that depends
only on the motion (position `q`, velocity `qd`, acceleration `qdd`) and
the tree topology. This is the standard base for inertial-parameter
identification (see Mikami et al., "Study on Dynamics Identification of the
Foot Viscoelasticity of a Humanoid Robot").

### Free functions

```cpp
Eigen::Matrix<double, 6, 10>
IMPhi(const sva::MotionVecd & mv);
```

Returns the 6×10 matrix such that for any spatial inertia `I` (as an
`sva::RBInertiad` whose 10-vector representation is `phi`), and any spatial
motion `m` (as `sva::MotionVecd`):

```
I * m  ==  IMPhi(m) * phi
```

i.e. `IMPhi(m)` is the "reshape" that turns the inertia-times-motion
product into a linear function of the 10-vector `phi`.

```cpp
Eigen::Matrix<double, 10, 1>
inertiaToVector(const sva::RBInertiad & rbi);

sva::RBInertiad
vectorToInertia(const Eigen::Matrix<double, 10, 1> & vec);

sva::RBInertiad
sVectorToInertia(const Eigen::VectorXd & vec);
```

`inertiaToVector` packs `(mass, momentum, inertia)` into the 10-vector layout
above. `vectorToInertia` is its inverse. `sVectorToInertia` is the
size-checked variant of `vectorToInertia`; it throws `std::out_of_range`
if `vec.rows() != 10` (message content is not pinned — just the exception
type and that it fires on wrong size).

```cpp
Eigen::VectorXd multiBodyToInertialVector(const rbd::MultiBody & mb);
```

Concatenates `inertiaToVector(body.inertia())` for every body of `mb` into
a `10·nrBodies()`-long vector `Phi = [phi_0; phi_1; …]`.

### `class IDIM`

```cpp
class IDIM {
public:
  IDIM();                              // default; Y() empty until computeY runs
  IDIM(const rbd::MultiBody & mb);     // allocate Y_ as (nrDof x 10*nrBodies)

  void computeY(const rbd::MultiBody & mb, const rbd::MultiBodyConfig & mbc);
  void sComputeY(const rbd::MultiBody & mb, const rbd::MultiBodyConfig & mbc);

  const Eigen::MatrixXd & Y() const;   // read-only accessor
};
```

`computeY` fills the internal `Y_` matrix so that
`Y() * multiBodyToInertialVector(mb)` equals the joint torque that
`InverseDynamics::inverseDynamics(mb, mbc)` would compute for the same
kinematic state. `sComputeY` is the safe wrapper that runs the standard
`checkMatchParentToSon`, `checkMatchBodyVel`, `checkMatchMotionSubspace`,
`checkMatchBodyAcc` (from `RBDyn/util.hh`) before delegating to `computeY`.

`computeY` expects `mbc.bodyVelB`, `mbc.bodyAccB` (both in body-fixed
frame; body acceleration already includes the gravity term),
`mbc.parentToSon`, and `mbc.motionSubspace` to be current, i.e. the caller
has run `forwardKinematics`, `forwardVelocity`, and one of the
`InverseDynamics::inverseDynamics` variants (or equivalents that populate
those fields).

Usage:

```cpp
rbd::MultiBody mb = /* ... */;
rbd::MultiBodyConfig mbc(mb);
mbc.gravity = Eigen::Vector3d(0, 0, 9.81);
/* set mbc.q, mbc.alpha, mbc.alphaD */
rbd::forwardKinematics(mb, mbc);
rbd::forwardVelocity(mb, mbc);
rbd::InverseDynamics id(mb);
id.inverseDynamics(mb, mbc);   // populates bodyAccB, ...

rbd::IDIM idim(mb);
idim.computeY(mb, mbc);
Eigen::VectorXd Phi = rbd::multiBodyToInertialVector(mb);
Eigen::VectorXd tau_recovered = idim.Y() * Phi;      // == the torque id produced
```

## `Coriolis.cpp` — Coriolis matrix (Bjerkeng-Pettersen factorization)

The Coriolis matrix `C(q, qd)` in the manipulator equation
`M(q) qdd + C(q, qd) qd + g(q) = tau` is not unique — many `C`s satisfy
`C · qd == n(q, qd)` for the same generalized velocity-dependent forces
`n`. This file implements the **Bjerkeng-Pettersen** factorization
("A new Coriolis matrix factorization", 2012), which is a specific choice
that also satisfies the passivity property `M˙ - 2C` is skew-symmetric.

### `class Coriolis`

```cpp
class Coriolis {
public:
  Coriolis(const rbd::MultiBody & mb);

  const Eigen::MatrixXd & coriolis(const rbd::MultiBody & mb,
                                   const rbd::MultiBodyConfig & mbc);
};
```

The constructor precomputes per-body `rbd::Jacobian` instances anchored at
each body's local center of mass (from `body.inertia().momentum() /
body.inertia().mass()`; the CoM defaults to zero if `mass == 0`) and
their `compactPath`s. It also pre-allocates a scratch `res_` matrix at least
as large as the widest per-body Jacobian.

`coriolis(mb, mbc)` fills the internal `nrDof × nrDof` matrix and returns a
reference to it. It expects `mbc.bodyPosW`, `mbc.bodyVelW`, and everything
needed by `Jacobian::jacobian` / `Jacobian::jacobianDot` to be current
(so callers run `forwardKinematics(mb, mbc)` and `forwardVelocity(mb, mbc)`
first).

The Bjerkeng-Pettersen expression is (per body `i`, then summed):

```
C_i = m_i · J_{v,i}^T · Jdot_{v,i}
    + J_{w,i}^T · R_i · I_i · R_i^T · Jdot_{w,i}
    + J_{w,i}^T · Rdot_i · I_i · R_i^T · J_{w,i}
```

where `J_{v,i}` (bottom-3-rows of `Jacobian::jacobian(mb, mbc)`) is the
linear Jacobian of body `i`'s CoM, `J_{w,i}` (top-3-rows) is the angular
Jacobian, `R_i = mbc.bodyPosW[i].rotation().transpose()`, `Rdot_i =
skew(mbc.bodyVelW[i].angular()) · R_i`, and `I_i` is the *body*-frame
inertia of body `i` translated to `body.inertia().momentum() /
body.inertia().mass()`:

```
I_i = body.inertia().inertia()
    - skew(m_i · CoM_local) · skew(CoM_local)^T
```

Each per-body `C_i` block is expanded into the full `nrDof × nrDof` matrix
via `Jacobian::expandAdd(compactPaths_[i], per_body_block, coriolis_)`.

Reference:
> M. Bjerkeng and K. Pettersen, "A new Coriolis matrix factorization",
> ICRA 2012.

## `Jacobian.cpp` — per-body geometric Jacobian

For a chosen "end body" `b` in a `MultiBody`, the Jacobian `J(q)` maps the
joint-velocity vector `alpha` of the joints along the root→`b` path to the
6-D spatial velocity of a point fixed to `b`:

```
V_body_point  =  J(q) * alpha_sub
```

where `alpha_sub` is the concatenation of `alpha[i]` for every `i` in
`jointsPath()`. The Jacobian is stored *reduced*: it has 6 rows and
`sum(dof(j) for j in jointsPath())` columns — one column per DoF *along
the path*, not per DoF of the whole tree. Callers project the reduced
Jacobian into the full `6 × nrDof(mb)` matrix via `fullJacobian` or the
compact-path `addFullJacobian` variant.

### `struct Block` + `using Blocks`

```cpp
struct Block {
  Block() = default;
  Block(Eigen::DenseIndex startDof, Eigen::DenseIndex startJac, Eigen::DenseIndex length);
  Eigen::DenseIndex startDof;   // start of the block in the full-DoF vector
  Eigen::DenseIndex startJac;   // start of the block in the reduced-DoF Jacobian
  Eigen::DenseIndex length;     // length in DoF
};
using Blocks = std::vector<Block>;
```

A `Blocks` sequence describes the contiguous DoF ranges covered by a
Jacobian's `jointsPath` when projected back into the full-DoF layout.
`compactPath(mb)` computes this sequence once so that `expandAdd(compactPath, …)`
can amortize the mapping across many calls.

### `class Jacobian` — constructors and configuration

```cpp
class Jacobian {
public:
  Jacobian();

  Jacobian(const MultiBody & mb, const std::string & bodyName,
           const Eigen::Vector3d & point = Eigen::Vector3d::Zero());

  Jacobian(const MultiBody & mb, const std::string & bodyName,
           const std::string & refBodyName,
           const Eigen::Vector3d & point = Eigen::Vector3d::Zero());
  // throws std::out_of_range if bodyName / refBodyName not in mb

  const std::vector<int> & jointsPath() const;     // root→body joint indices
  // For the two-body ctor, jointsPath traces refBody → LCA → body; joints
  // on the refBody-side of the LCA are traversed child-to-parent and
  // contribute with a flipped sign in the reduced Jacobian.
  int dof() const;                                  // = jacobian().cols()
  const Eigen::Vector3d & point() const;            // static offset in body frame
  void point(const Eigen::Vector3d & point);        // update the offset
  MultiBody subMultiBody(const MultiBody & mb) const; // sub-tree along jointsPath
};
```

The single-body constructor computes the Jacobian of a point rigidly
attached to `bodyName` at `point` (in body coordinates); the two-body
constructor produces a relative Jacobian expressed at `bodyName` with
respect to `refBodyName`.

The relative Jacobian's ROWS are expressed in a frame that shares the ref
body's rotational basis. Concretely, after the reduced Jacobian is
assembled column-by-column in the world frame (as for the single-body ctor,
but with refBody-side joint columns sign-flipped), when `refBodyName` is
not the tree root, both the angular (rows 0-2) and linear (rows 3-5)
blocks are pre-multiplied by
`mbc.bodyPosW[refBodyIndex].rotation()`
(i.e. E_{refBody ← world}, which rotates world-frame quantities into the
ref body's rotational basis). The `jacobian(mb, mbc, X_0_p)` overload
follows the same rule; `bodyJacobian` does not — its rows stay in the end
body's own frame exactly as for the single-body ctor, with only the
refBody-side sign flips applied.

`subMultiBody(mb)` returns a `MultiBody` of exactly `jointsPath().size()`
bodies and `jointsPath().size()` joints. For each `i` in
`0 .. jointsPath().size()-1`:
  - `bodies[i] = mb.body(jointsPath()[i])`
  - `joints[i] = mb.joint(jointsPath()[i])` (see below for the two-body
    ctor's sign-flip case), with `succ[i] = i` and
    `pred[i] = parent[i] = i - 1` (root has `pred = parent = -1`) — i.e. the
    `predecessors()` array equals the `parents()` array, not the identity
  - `Xt[i] = mb.transform(jointsPath()[i])`
The first joint is typically the auto-generated
`Joint(Joint::Fixed, true, "Root")` from `MultiBodyGraph::makeMultiBody(..,
isFixed=true)`; it is passed through unchanged (do not prepend an
additional Root body/joint).

For the two-body ctor, each refBody-side joint (sign -1) additionally
gets `joint.forward(!joint.forward())`, and the `Xt[k]` of every path
entry is chosen from the sign of that entry and of its predecessor on the
path (`prev = jointsPath()[k-1]`, `cur = jointsPath()[k]`) instead of
always using the `mb.transform(cur)` rule above:
  - `k == 0` — this entry is the reversed sub-chain's root. If it is a
    refBody-side joint (sign -1, the deepest refBody-side body) it takes
    the identity root transform, `Xt[0] = PTransformd::Identity()`;
    otherwise (sign +1, i.e. `refBody` is an ancestor of `body`, so there
    are no refBody-side joints) `Xt[0] = mb.transform(cur)`.
  - `k > 0` and the preceding entry `prev` is refBody-side (sign -1): if
    `cur` is also refBody-side, `Xt[k] = mb.transform(prev).inv()`; if
    `cur` is the first body-side joint past the LCA (sign +1),
    `Xt[k] = mb.transform(prev).inv() * mb.transform(cur)`.
  - `k > 0` and the preceding entry `prev` is body-side (sign +1):
    `Xt[k] = mb.transform(cur)` (the general rule).

### Jacobian computation and derivatives

```cpp
const Eigen::MatrixXd & jacobian(const MultiBody & mb, const MultiBodyConfig & mbc);
const Eigen::MatrixXd & jacobian(const MultiBody & mb, const MultiBodyConfig & mbc,
                                 const sva::PTransformd & X_0_p);
const Eigen::MatrixXd & bodyJacobian(const MultiBody & mb, const MultiBodyConfig & mbc);

const Eigen::MatrixXd & vectorJacobian(const MultiBody & mb, const MultiBodyConfig & mbc,
                                       const Eigen::Vector3d & vector);
const Eigen::MatrixXd & vectorBodyJacobian(const MultiBody & mb, const MultiBodyConfig & mbc,
                                           const Eigen::Vector3d & vector);

const Eigen::MatrixXd & jacobianDot(const MultiBody & mb, const MultiBodyConfig & mbc);
const Eigen::MatrixXd & bodyJacobianDot(const MultiBody & mb, const MultiBodyConfig & mbc);
```

The two-argument `jacobian` returns the Jacobian in world frame (rows are
`[omega_world; v_world]`), referenced at the constructor's static point.
`bodyJacobian` returns the same information expressed in the end body's
frame. The three-argument `jacobian(mb, mbc, X_0_p)` expresses its output
rows in the frame `X_0_p`: `X_0_p.rotation()` sets the output orientation
and `X_0_p.translation()` sets the reference point. The rows are NOT
re-projected back to world when `X_0_p` carries a non-identity rotation.

`vectorJacobian` and `vectorBodyJacobian` compute the translation-only
Jacobian (rows 3-5) of the DIFFERENCE between the Jacobian at
`point() + vector` and the Jacobian at `point()` alone — i.e., the
change in translation Jacobian caused by a body-frame offset `vector`.
Rows 0-2 (angular) are unchanged from the previously computed Jacobian
and are NOT written by these methods. Concretely for each joint `i`
in `jointsPath`:
  ```
  jac.col(k).tail<3>() = E_i_out
      * (diff × motionSubspace.col(k).head<3>())
  ```
where `diff = X_i_N.translation() - X_i_Nv.translation()`, and
`E_i_out` is `E_i^{world→0}` (for `vectorJacobian`) or `E_i^{body→N}`
(for `vectorBodyJacobian`).

`jacobianDot` returns `d/dt jacobian(mb, mbc)` — the callers must have
run `forwardKinematics` and `forwardVelocity` on `mbc`. Same for
`bodyJacobianDot`.

The world-frame `jacobianDot` column for joint `i`'s DoF `j` is
  ```
  E_VN × (E_N_0 · X_{i→Np} · S_ij) + E_N_0 · X_VNp_{i→Np} × (X_{i→Np} · S_ij)
  ```
where `X_{i→Np} = X_0_Np · X_0_i^{-1}` (Np is the point on body N),
`X_VNp = point * bodyVelB[N]` (body-N velocity at point, in body frame),
`X_VNp_{i→Np} = X_{i→Np} · bodyVelB[i] − X_VNp`, and
`E_VN = MotionVecd(bodyVelW[N].angular(), Zero())`. `bodyJacobianDot`
drops the first term (no world-frame rotation change contribution).

### End-body velocity and normal acceleration helpers

```cpp
sva::MotionVecd velocity(const MultiBody & mb, const MultiBodyConfig & mbc) const;
sva::MotionVecd velocity(const MultiBody & mb, const MultiBodyConfig & mbc,
                         const sva::PTransformd & X_b_p) const;
sva::MotionVecd bodyVelocity(const MultiBody & mb, const MultiBodyConfig & mbc) const;

sva::MotionVecd normalAcceleration(const MultiBody & mb, const MultiBodyConfig & mbc) const;
sva::MotionVecd normalAcceleration(const MultiBody & mb, const MultiBodyConfig & mbc,
                                   const sva::PTransformd & X_b_p,
                                   const sva::MotionVecd & V_b_p) const;
sva::MotionVecd normalAcceleration(const MultiBody & mb, const MultiBodyConfig & mbc,
                                   const std::vector<sva::MotionVecd> & normalAccB) const;
sva::MotionVecd normalAcceleration(const MultiBody & mb, const MultiBodyConfig & mbc,
                                   const std::vector<sva::MotionVecd> & normalAccB,
                                   const sva::PTransformd & X_b_p,
                                   const sva::MotionVecd & V_b_p) const;

sva::MotionVecd bodyNormalAcceleration(const MultiBody & mb, const MultiBodyConfig & mbc) const;
sva::MotionVecd bodyNormalAcceleration(const MultiBody & mb, const MultiBodyConfig & mbc,
                                       const std::vector<sva::MotionVecd> & normalAccB) const;
```

`velocity(mb, mbc)` returns `J(q) * alpha_sub` as a spatial velocity in
world frame (equivalent to computing `jacobian(mb, mbc) * alpha_sub`
directly). `bodyVelocity` is the same in the body frame. Both
obtain that velocity from the end body's already-computed spatial velocity
`mbc.bodyVelB[endBody]` directly (for `velocity`, rotated into the world
frame via `mbc.bodyPosW[endBody]`) rather than re-forming the Jacobian
product. The `X_b_p` overload applies `X_b_p` to that same body-frame
velocity as the outermost transform, so its result is expressed in the
frame `X_b_p` maps into and is NOT re-projected back to world (the
convention already stated for `jacobian(mb, mbc, X_0_p)`); the
`normalAcceleration(..., X_b_p, V_b_p)` overloads use the same convention.
Following the "checkMatch for fields read" rule below,
`sBodyVelocity` therefore validates only `mbc.bodyVelB`
(`checkMatchBodyVel`), while `sVelocity` validates both `mbc.bodyPosW`
and `mbc.bodyVelB`.

The `normalAcceleration` family returns `JDot * alpha_sub` (the
velocity-dependent term of `V_dot`). The overloads accepting `normalAccB`
use the caller-supplied normal-acceleration vector for each body of the
tree (index by full-body index) instead of recomputing it from
`mbc.bodyVelB` / `mbc.parentToSon`.

### Translation and full-DoF projection

```cpp
void translateJacobian(const Eigen::Ref<const Eigen::MatrixXd> & jac,
                       const MultiBodyConfig & mbc,
                       const Eigen::Vector3d & point,
                       Eigen::MatrixXd & res);
void translateBodyJacobian(const Eigen::Ref<const Eigen::MatrixXd> & jac,
                           const MultiBodyConfig & mbc,
                           const Eigen::Vector3d & point,
                           Eigen::MatrixXd & res);

void fullJacobian(const MultiBody & mb,
                  const Eigen::Ref<const Eigen::MatrixXd> & jac,
                  Eigen::MatrixXd & res) const;
void addFullJacobian(const Blocks & compactPath,
                     const Eigen::Ref<const Eigen::MatrixXd> & jac,
                     Eigen::MatrixXd & res) const;
```

`translateJacobian(jac, mbc, point, res)` produces a reduced Jacobian
equivalent to what one would obtain by constructing a new `Jacobian`
with `point` as the body offset — but without redoing the traversal.
More precisely, `point` is applied *relative to* the point that the
supplied `jac` already represents: applied to a `Jacobian` built with a
non-zero constructor offset `point()`, the result is the Jacobian at
`point() + point` (so it adds `point` to the existing offset). The plain
"`point` as the body offset" equivalence therefore holds specifically when
`jac` is the point-0 / body-origin Jacobian.
`translateBodyJacobian` is the body-frame counterpart. Both accept the
Jacobian's own output as `jac` and write into a caller-allocated `res`
of the same shape.

`fullJacobian` copies the columns of a reduced Jacobian into the full
`6 × nrDof(mb)` layout (overwriting `res`); `addFullJacobian` accumulates
instead. `addFullJacobian` uses a precomputed `compactPath(mb)` to skip
re-scanning `jointsPath`.

### Expand-add (Coriolis-style symmetric product projection)

```cpp
Eigen::MatrixXd expand(const rbd::MultiBody & mb,
                       const Eigen::Ref<const Eigen::MatrixXd> & jac) const;
void expandAdd(const rbd::MultiBody & mb,
               const Eigen::Ref<const Eigen::MatrixXd> & jac,
               Eigen::MatrixXd & res) const;
void expandAdd(const Blocks & compactPath,
               const Eigen::Ref<const Eigen::MatrixXd> & jac,
               Eigen::MatrixXd & res) const;
Blocks compactPath(const rbd::MultiBody & mb) const;
```

`expand(mb, product)` takes a `dof() × dof()` matrix (typically
`J.transpose() * J`) and returns the corresponding `nrDof(mb) × nrDof(mb)`
matrix with each `(i, j)` block placed at the DoF indices reached by
`jointsPath()`. `expandAdd` accumulates instead of overwriting.

`compactPath(mb)` computes a `Blocks` sequence describing the contiguous
DoF ranges the Jacobian projects into; passing it to the `Blocks`
overloads of `expandAdd` / `addFullJacobian` amortizes the traversal.

### Safe variants

Every mutating / computing method above has an `sXxxx` prefix twin
(`sJacobian`, `sBodyJacobian`, `sJacobianDot`, `sSubMultiBody`,
`sFullJacobian`, `sTranslateJacobian`, `sVelocity`, `sBodyVelocity`,
`sNormalAcceleration`, `sBodyNormalAcceleration`, `sVectorJacobian`,
`sVectorBodyJacobian`) that throws `std::domain_error` before delegating
to the unchecked version. The required checks are:
  - All `sXxxx`: `max(jointsPath_) < mb.nrJoints()` (the jointsPath is
    within the passed MultiBody).
  - All `sXxxx` that read mbc fields: the corresponding
    `checkMatchBodyPos` / `checkMatchBodyVel` / `checkMatchMotionSubspace`
    / `checkMatchJointConf` / `checkMatchParentToSon` from
    `RBDyn/MultiBodyConfig.h`.
  - `sFullJacobian`: additionally, `jac.rows() == 6 && jac.cols() ==
    dof()` and `res.rows() == 6 && res.cols() == mb.nrDof()`.
  - `sTranslateJacobian`: `jac.rows() == res.rows() == 6` and
    `jac.cols() == res.cols() == dof()`.
Any missing bounds check will trigger an Eigen `assert(...)` on the
next block/col access, aborting the whole test binary — the throw
IS the guard.

## `NumericalIntegration.cpp` — integration helpers

```cpp
std::pair<Eigen::Quaterniond, bool>
SO3Integration(const Eigen::Quaterniond & qi,
               const Eigen::Vector3d & wi,
               const Eigen::Vector3d & wD,
               double step,
               double relEps = 1e-12,
               double absEps = std::numeric_limits<double>::epsilon(),
               bool breakOnWarning = false);
```

Integrates a rotation with initial orientation `qi`, initial angular
velocity `wi`, and constant angular acceleration `wD` over a duration
`step`. Uses a Magnus-series expansion internally; returns the
integrated quaternion and a `bool` flag which is `true` on convergence
(false if the series was cut short by `relEps` / `absEps` /
`breakOnWarning`). For zero angular acceleration (`wD == 0`, i.e. constant
angular velocity) the Magnus series reduces to its single first term, so the
function short-circuits to that exact result and returns the flag as `false`
(the iterative refinement loop never runs — here `false` means "loop not run",
not "diverged").

```cpp
void jointIntegration(Joint::Type type,
                      const std::vector<double> & alpha,
                      const std::vector<double> & alphaD,
                      double step,
                      std::vector<double> & q,
                      double prec = 1e-10);
```

Integrates a *single* joint's configuration `q` in place, given velocity
`alpha` and constant acceleration `alphaD`, over `step`. The
representation is joint-type-specific:

- `Joint::Rev`, `Joint::Prism` — scalar Euler update
  (`q[0] += alpha[0] * step + 0.5 * alphaD[0] * step * step`).
- `Joint::Cylindrical` — 2 scalar Euler updates.
- `Joint::Planar` — Planar-joint closed-form update.
  With `tw = alpha[0] * step` (rotation angle) and `sc = sinc(tw)`,
  `cc = (1 - cos(tw)) / tw` (with Taylor fallback near zero). The two
  translation DoFs `q[1]`, `q[2]` update **simultaneously** — both
  right-hand sides read the *pre-update* values, so capture
  `p1 = q[1]`, `p2 = q[2]` first (equivalently, apply the 2×2 rotation
  to the old pair) and do not feed the new `q[1]` into `q[2]`:
  ```
  q[0] += tw
  q[1]  = cos(tw) * p1 + sin(tw) * p2 + step * (sc * alpha[1] + cc * alpha[2])
  q[2]  = -sin(tw) * p1 + cos(tw) * p2 + step * (-cc * alpha[1] + sc * alpha[2])
  ```
  The closed form above is the constant-velocity (`alphaD == 0`) case; as for
  the other joint types, a non-zero `alphaD` must be integrated as well.
- `Joint::Spherical` — quaternion in `q[0..3]` (w, x, y, z); use
  `SO3Integration` on the current orientation with the given angular
  velocity / acceleration.
- `Joint::Free` — free flyer: quaternion in `q[0..3]`, translation in
  `q[4..6]`. Orientation via `SO3Integration` on `(alpha[0..2], alphaD[0..2])`.
  Translation via the Rodrigues integral of `R(t) * v(t)` in the world
  frame, where `R(t) = qi * exp(t·hat(w))`. For constant velocity
  (`alphaD == 0`), the closed form is
    ```
    n  = ||w||;   tn = step * n;
    a  = (tn > 1e-4) ? (1 - cos(tn)) / (n*n)          : (tn*tn) / 2;
    b  = step * (1 - sinc(tn)) / (n*n);
    dx = step * v + a * (w × v) + b * (w × (w × v));
    q[4..6] += qi * dx;
    ```
  where `w = alpha[0..2]`, `v = alpha[3..5]` (both body frame). For
  non-zero `alphaD`, add the standard second-order acceleration terms
  (an adaptive Simpson quadrature over `R(t)*v(t)` with `prec` matches
  the test's `1e-9` tolerance).

```cpp
void integration(const MultiBody & mb, MultiBodyConfig & mbc,
                 double step, double prec = 1e-10);

void sIntegration(const MultiBody & mb, MultiBodyConfig & mbc,
                  double step, double prec = 1e-10);
```

`integration(mb, mbc, step)` advances every joint of `mbc.q` by `step`
using the corresponding `mbc.alpha` and `mbc.alphaD`, then updates
`mbc.alpha` in place: `alpha += alphaD * step`. The safe wrapper
`sIntegration` runs the standard `checkMatch*` guards first and throws
`std::domain_error` on mismatch.

Consistency contract: integrating `step` in one call and integrating
`step/N` `N` times (with `forwardKinematics` in between when needed)
must agree to the joint-type integrator's precision. Integrating a
constant velocity for `step` must match the joint-type-specific
closed-form update above.

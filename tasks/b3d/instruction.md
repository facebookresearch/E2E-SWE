# A minimal software 3D renderer (`b3d`)

Build a small library in **C** that rasterizes 3D triangles to a
user-supplied pixel buffer without any GPU, OpenGL, or windowing dependency
— a pure-software 3D pipeline (transform → cull → clip → project →
rasterize with depth test) plus the small utilities needed to feed it:
fast trig, a Wavefront `.obj` loader, and a mesh voxelizer.

The library is used by allocating caller-owned pixel and depth buffers,
calling `b3d_init(pixels, depth, w, h, fov)`, setting a camera via
`b3d_set_camera`, and rendering triangles via `b3d_triangle` (with
`b3d_clear` between frames). Everything runs in-process, in software,
with no dynamic allocation on the render path.

## Build contract

The library ships four public headers and one static library binary. Your
`setup.sh` must build offline (no network, no `apt-get`, no `pip install`
at that point — a standard C toolchain with `gcc`, `ar`, `install`, and
`ldconfig` is available) and install:

| file                          | destination                          |
|-------------------------------|--------------------------------------|
| `b3d.h`       — main API      | `/usr/local/include/b3d.h`           |
| `b3d-math.h`  — math utils    | `/usr/local/include/b3d-math.h`      |
| `b3d-obj.h`   — obj loader    | `/usr/local/include/b3d-obj.h`       |
| `b3d-voxel.h` — voxelizer     | `/usr/local/include/b3d-voxel.h`     |
| `libb3d.{a,so}`               | `/usr/local/lib/libb3d.{a,so}`       |

After install, a downstream program compiles and links with

```
gcc -std=c11 -O2 driver.c -lb3d -lm -o driver
```

with no `-I` / `-L` flags — the standard system include and lib paths must
resolve everything. Run `ldconfig` at the end of `setup.sh` if you ship a
shared library.

C11 is fine. The library targets Linux; it should not require any external
libraries beyond libc and libm (`-lm` is expected because the math header
uses standard `<math.h>` functions in floating-point mode).

## Compile-time configuration

Callers set the following macro before including any b3d header (as a
`-D` flag on their own compile line) to opt into the alternative math
mode:

| macro             | meaning                                                     |
|-------------------|-------------------------------------------------------------|
| `B3D_FLOAT_POINT` | Use `float` for math internals and the depth buffer element |

`b3d-math.h` and `b3d-obj.h` are header-only. `b3d-voxel.h` declares
functions that live in the compiled `libb3d`.

## Coordinate system

| property          | value                                        |
|-------------------|----------------------------------------------|
| handedness        | Right-handed                                 |
| up axis           | `+Y`                                         |
| forward axis      | `+Z` (into the screen)                       |
| screen origin     | top-left `(0, 0)`; `+x` right, `+y` down     |
| winding for front | Counter-clockwise in the right-handed world frame, viewed from the camera position (see **Rendering**) |
| near plane        | `0.1` (view-space z, hard-coded)             |
| far  plane        | `100.0` (view-space z, hard-coded)           |

## Matrix conventions

`b3d` uses **row-major** 4×4 matrices with **row vectors** on the left.

| aspect                | b3d                                       |
|-----------------------|-------------------------------------------|
| storage layout        | Row-major, `m[row][col]`                  |
| vector shape          | Row vector — treated as `1×4`             |
| vector×matrix         | `v' = v * M` (vector on the left)         |
| API composition order | Post-multiply: `M := M * T` for each op   |
| effect order          | Transforms apply **in call order**        |
| translation storage   | Row 3: elements `m[3][0..2]` (= indices 12/13/14 in the flat 16-float array) |

Layout of a translation matrix by `(tx, ty, tz)`:

```
[ 1  0  0  0 ]        flat: [1, 0, 0, 0,
[ 0  1  0  0 ]                0, 1, 0, 0,
[ 0  0  1  0 ]                0, 0, 1, 0,
[ tx ty tz 1 ]                tx, ty, tz, 1]
```

Rotation matrix around Y by angle `a`:

```
[  cos(a)  0  sin(a)  0 ]
[    0     1    0     0 ]
[ -sin(a)  0  cos(a)  0 ]
[    0     0    0     1 ]
```

All three rotations share the **same sign convention** as the `Ry` matrix
written out above (row-vector `v' = v * M`): a positive angle rotates
`+X → +Z` for `rotate_y`, `+Y → +Z` for `rotate_x`, and `+X → +Y` for
`rotate_z`. This is the sense that determines the on-screen direction a
rotated triangle moves; do not substitute the textbook right-hand-rule
rotation matrices, which carry the opposite off-diagonal signs for X and Z.

In both math modes the renderer builds its matrices from trigonometry at
least as accurate as the `b3d-math.h` default mode documented below, so
the cells reported by `b3d_get_model_matrix`, `b3d_get_view_matrix` and
`b3d_get_proj_matrix` track the values formed from the exact `sin` / `cos`
of the requested angles to within that error (times whatever scale the
composed transform applies).

## Color format

Colors are `uint32_t` in `0xAARRGGBB` layout; the alpha byte is ignored on
output.

The **upper byte** of the color parameter carries per-face control flags,
not color data:

| macro                  | bit  | meaning                                              |
|------------------------|------|------------------------------------------------------|
| `B3D_DRAW_BACKFACE`    | 31   | Disable back-face culling for this one triangle.     |

Usage: `b3d_triangle(&tri, 0xff0000 | B3D_DRAW_BACKFACE);`. The
low 24 bits are the RGB used to shade the surface; the flag bits are
consumed before rasterization.

---

# `b3d.h` — renderer core

## Types

```c
typedef struct { float x, y, z; }                      b3d_point_t;
typedef struct { b3d_point_t v[3]; }                   b3d_tri_t;
typedef struct { float x, y, z, yaw, pitch, roll; }    b3d_camera_t;
```

`b3d_depth_t` is the per-pixel depth-buffer element `typedef`, selected at
compile time: a 32-bit fixed-point value by default, or `float` when
`B3D_FLOAT_POINT` is set. Callers use it as an opaque type (no test or
downstream code inspects its representation).

`#define B3D_MATRIX_STACK_SIZE 16` — the fixed capacity of the model
matrix stack.

## Initialization and framebuffer

```c
bool  b3d_init(uint32_t   *pixel_buffer,
               b3d_depth_t *depth_buffer,
               int w, int h, float fov_deg);
void  b3d_clear(void);
size_t b3d_buffer_size(int w, int h, size_t elem_size);
```

`b3d_init` binds the caller-owned pixel and depth buffers (each must have
capacity `w * h` elements), sets the initial perspective FOV (**degrees**),
and initializes the model matrix to identity and the camera to the origin
looking down `+Z`. Returns `true` on success. Returns `false` — leaving
the renderer in an uninitialized state — when any of these hold:

- `pixel_buffer` or `depth_buffer` is `NULL`
- `w <= 0` or `h <= 0`
- `fov_deg <= 0`
- computing the byte sizes for `w * h` elements would overflow `size_t`

`b3d_clear` clears the pixel buffer to zero (`0x00000000`) and the depth
buffer to the far-plane value, and resets the clip-drop counter (see
`b3d_get_clip_drop_count`). It is a no-op if the renderer is not
initialized.

`b3d_buffer_size` computes `w * h * elem_size` with overflow detection;
returns `0` if any argument is `<= 0` or if the multiplication would
overflow `size_t`. Callers use it to size their pixel and depth buffers
safely.

## Model matrix and transforms

Angles are in **radians** here (only `b3d_init`'s FOV and `b3d_set_fov`
are in degrees).

```c
void b3d_reset    (void);
void b3d_translate(float x, float y, float z);
void b3d_rotate_x (float angle);
void b3d_rotate_y (float angle);
void b3d_rotate_z (float angle);
void b3d_scale    (float x, float y, float z);
```

`b3d_reset` sets the model matrix to identity. Each of the other four
post-multiplies the current model matrix by the corresponding
translation/rotation/scale.

```c
bool b3d_push_matrix(void);   /* false when stack is full          */
bool b3d_pop_matrix (void);   /* false when stack is empty         */
```

Stack capacity is `B3D_MATRIX_STACK_SIZE`. Push saves the current model
matrix; pop restores it. `b3d_init` (and `b3d_reset` implicitly) clears
the stack to empty.

```c
void b3d_get_model_matrix(float out[16]);
void b3d_set_model_matrix(const float m[16]);
```

Both use the row-major flat layout described in **Matrix conventions**:
`out[0..3]` is row 0, `out[4..7]` is row 1, and so on; `out[12/13/14]`
carry translation. Passing `NULL` is a no-op for both.

## Camera, view and projection

```c
void  b3d_set_camera(const b3d_camera_t *cam);
void  b3d_get_camera(b3d_camera_t *out);
void  b3d_look_at   (float x, float y, float z);
void  b3d_set_fov   (float fov_deg);
float b3d_get_fov   (void);
void  b3d_get_view_matrix(float out[16]);
void  b3d_get_proj_matrix(float out[16]);
```

`b3d_set_camera` stores position `(x, y, z)` and orientation
`(yaw, pitch, roll)` (radians) and recomputes the internal view matrix.
`b3d_get_camera` returns the last values stored — set/get round-trip
exactly. `NULL` arguments are ignored on either side.

`b3d_look_at(tx, ty, tz)` rebuilds the view matrix so the camera (kept
at its current position) faces the given target. This bypasses the
`yaw/pitch/roll` state — subsequent `b3d_get_camera` returns the stored
Euler angles, which are stale after `look_at`; callers who need the
actual orientation use `b3d_get_view_matrix`.

`b3d_set_fov(deg)` recomputes the perspective projection matrix. If the
renderer is currently in orthographic mode, this switches it back to
perspective.

`b3d_get_view_matrix` and `b3d_get_proj_matrix` write the current view
and projection matrices in the row-major flat layout described above.

## Orthographic projection

```c
void b3d_ortho(float left, float right,
               float bottom, float top,
               float near,  float far);
bool b3d_is_ortho(void);
```

`b3d_ortho(l, r, b, t, n, f)` switches the renderer to orthographic
projection with the given view volume — parallel lines stay parallel, no
foreshortening. `b3d_is_ortho` returns whether the projection is
currently orthographic. Calling `b3d_set_fov` after `b3d_ortho` switches
back to perspective. `b3d_ortho` rejects non-finite arguments and
volumes with zero extent (e.g. `left == right`) — in either case it
leaves the current projection unchanged.

## Lighting

```c
void  b3d_set_light_direction(float x, float y, float z);
void  b3d_get_light_direction(float *x, float *y, float *z);
void  b3d_set_ambient        (float ambient);
float b3d_get_ambient        (void);
```

`b3d_set_light_direction` normalizes the given vector and stores it as
the current light direction. Zero-length or non-finite (NaN/Inf) inputs
are rejected and leave the previous direction unchanged. Default: the
unit `+Z` vector `(0, 0, 1)`.

`b3d_get_light_direction` writes the current normalized direction; any
of the three pointers may be `NULL`.

`b3d_set_ambient` clamps the argument to `[0, 1]`; non-finite inputs
are rejected. Default: `0.2` (20% ambient).

The lighting model used by `b3d_triangle_lit` (see next section) is
two-sided diffuse: `intensity = ambient + (1 - ambient) * |dot(N, L)|`
where `N` is the surface normal (normalized) and `L` is the current
light direction. Because `|dot|` is used, back faces are shaded the
same as front faces. Lighting is computed in **model space**, so the
shading is fixed relative to the object and rotates with it.

## Rendering

```c
bool b3d_triangle    (const b3d_tri_t *tri, uint32_t color);
bool b3d_triangle_lit(const b3d_tri_t *tri,
                      float nx, float ny, float nz,
                      uint32_t base_color);
```

`b3d_triangle` transforms the triangle by the model matrix, performs
back-face culling in world space, transforms by the view matrix, clips
against the near and far planes, projects to screen space, clips
against the four screen edges, and rasterizes with per-pixel depth
testing (closer fragment wins).

Return value is `true` if any pixel was written and `false` when the
triangle was rejected (invalid input, degenerate, fully culled, or
fully outside the frustum). Specifically:

- Returns `false` if `tri` is `NULL` or the renderer is uninitialized.
- Returns `false` if any of the nine vertex components is NaN or
  infinite.
- Returns `false` if the triangle is a back-face (world-space normal
  points away from the camera) — **unless** the color's flag bits
  include `B3D_DRAW_BACKFACE`, in which case the culling step is
  skipped for this call. Face orientation is fixed by vertex order:
  the world-space normal is the ordinary right-hand-rule cross product
  `N = (v[1] - v[0]) × (v[2] - v[0])`, and the triangle is a front
  face when `N` points toward the camera position.
- Returns `false` if the triangle is fully behind the near plane
  (`z < 0.1` for all vertices) or fully beyond the far plane
  (`z > 100.0` for all vertices). A triangle that straddles a plane
  is clipped and the visible portion is rendered — near-plane
  clipping can split one input triangle into up to two output
  triangles; if the internal clip buffer overflows, the surplus is
  silently discarded and the drop count (see `b3d_get_clip_drop_count`)
  is incremented for each dropped triangle.

The low 24 bits of `color` are the RGB shade written to any pixel this
triangle covers whose current depth is greater (further) than the
triangle's depth at that pixel; the upper 8 bits carry per-face flags
(`B3D_DRAW_BACKFACE`) and are not written to the pixel buffer.

`b3d_triangle_lit` computes the shading intensity from the supplied
surface normal `(nx, ny, nz)` and the current light-direction / ambient
state (two-sided diffuse per **Lighting** above), scales the RGB
channels of `base_color` by that intensity, preserves the flag bits from
`base_color`, and forwards to `b3d_triangle`. The normal is normalized
internally. Non-finite inputs (any of `nx`/`ny`/`nz`, or any vertex
component) cause it to return `false` without drawing.

## Utility

```c
bool   b3d_to_screen(float x, float y, float z, int *sx, int *sy);
size_t b3d_get_clip_drop_count(void);
```

`b3d_to_screen` projects the world-space point `(x, y, z)` through the
current model, view, and projection matrices to screen coordinates. On
success, `*sx` and `*sy` receive the integer pixel position (with the
half-pixel offset added before truncation, so the reported pixel is the
nearest neighbor to the projected sub-pixel position). Returns `false`
— without touching the outputs — if either output pointer is `NULL` or
if the point is behind the camera (post-projection `w` component below
an epsilon).

`b3d_get_clip_drop_count` returns the number of triangles that have
been silently dropped during clipping since the last `b3d_clear` (or
since `b3d_init`, if never cleared). The count is reset by
`b3d_clear` and by `b3d_init`.

## State queries

```c
bool b3d_is_initialized(void);
int  b3d_get_width (void);
int  b3d_get_height(void);
```

`b3d_is_initialized` returns `true` when `b3d_init` has completed
successfully and has not been superseded by a failing `b3d_init` call.
`b3d_get_width` and `b3d_get_height` return the framebuffer dimensions
passed to the most recent successful `b3d_init` (or `0` if
uninitialized).

---

# `b3d-math.h` — math utilities

Header-only. Provides `b3d_`-prefixed wrappers for the trig / sqrt / abs
functions the renderer and its callers need, plus a combined sin+cos
helper. Two implementation modes selected at compile time:

- **Default**. Accuracy: max absolute error on the order of `1e-4` over
  `[-2π, 2π]`.
- **`B3D_FLOAT_POINT`**. Wrappers forward to the standard `<math.h>`
  functions.

In both modes the public signatures are identical:

```c
static inline float b3d_sinf (float x);
static inline float b3d_cosf (float x);
static inline float b3d_tanf (float x);
static inline float b3d_sqrtf(float x);
static inline float b3d_fabsf(float x);
static inline void  b3d_sincosf(float x, float *sinp, float *cosp);
```

Contracts:

- `b3d_sinf` and `b3d_cosf` match the standard `sinf` / `cosf` up to the
  documented accuracy of the selected mode, for any finite `x` in the
  range `[-2π, 2π]`.
- `b3d_tanf(x)` returns `b3d_sinf(x) / b3d_cosf(x)`; when
  `|b3d_cosf(x)|` is below a small epsilon (`~1e-7`), it returns `0`
  rather than diverging (so callers get a finite value near
  singularities).
- `b3d_sqrtf(x)` returns `0` for `x <= 0`; otherwise the non-negative
  square root of `x`.
- `b3d_fabsf(x)` returns `x` if `x >= 0` and `-x` otherwise.
- `b3d_sincosf(x, &s, &c)` writes `b3d_sinf(x)` and `b3d_cosf(x)` to
  `*s` and `*c` respectively.

---

# `b3d-obj.h` — Wavefront OBJ loader

Header-only. A small self-contained parser for a subset of the `.obj`
file format sufficient to extract triangle data — the b3d rasterizer's
input shape.

## Types

```c
typedef struct {
    float *triangles;    /* 9 floats per triangle: ax,ay,az, bx,by,bz, cx,cy,cz */
    int    triangle_count;
    int    vertex_count; /* == triangle_count * 9 */
} b3d_mesh_t;
```

The `triangles` buffer is a flat array where each triangle contributes 9
consecutive floats in the order `ax ay az bx by bz cx cy cz`.
`triangle_count` is the number of triangles; `vertex_count` is the total
float count, i.e. `triangle_count * 9`.

## API

```c
int  b3d_load_obj  (const char *path, b3d_mesh_t *mesh);
void b3d_free_mesh (b3d_mesh_t *mesh);
void b3d_mesh_bounds(const b3d_mesh_t *mesh,
                     float *min_y, float *max_y, float *max_xz);
```

### `b3d_load_obj(path, mesh)`

Opens the file at `path`, parses it, and fills `mesh` with the extracted
triangle data. On success, `mesh->triangles` points to a newly allocated
buffer that the caller must eventually pass to `b3d_free_mesh`.

Return values:

| return | meaning                                                         |
|--------|-----------------------------------------------------------------|
| `0`    | success                                                         |
| `1`    | file open failure (missing path, unreadable, or `path`/`mesh` NULL) |
| `2`    | memory allocation failure                                       |
| `3`    | invalid vertex index in a face record                           |

On any non-zero return, `mesh->triangles` is `NULL` and both count
fields are `0`.

Supported syntax:

- `v x y z` — vertex position. Coordinates are floats and may use
  scientific notation (`1.5e-3`, `-1e+02`).
- `f v1 v2 v3 ...` — face. Each `v` is `idx`, `idx/tex`,
  `idx/tex/norm`, or `idx//norm`. Texture/normal indices are parsed
  but ignored. Vertex indices are 1-based; a negative index is
  interpreted relative to the current vertex count (`-1` is the last
  vertex read so far, `-2` the one before that, etc.). Zero is
  treated as the first vertex (equivalent to index 1).
- Faces with more than three vertices are triangulated by a **fan** at
  vertex 0: `(0,1,2), (0,2,3), (0,3,4), ...`. Faces with more than
  64 vertices are truncated at that limit.
- Faces with fewer than 3 vertices produce no triangles (they are
  silently skipped).
- Blank lines, lines starting with `#`, and lines whose leading
  keyword is neither `v` nor `f` are ignored.

An invalid face index (out of range after normalization) causes the
loader to abort with return `3`; any partially-parsed triangles are
freed before returning.

### `b3d_free_mesh(mesh)`

Frees `mesh->triangles` and resets both count fields to zero. Passing
`NULL` is a no-op. A mesh whose `triangles` is already `NULL` is left
untouched (still safe to call).

### `b3d_mesh_bounds(mesh, &min_y, &max_y, &max_xz)`

Computes vertical bounds and the largest absolute horizontal
distance-from-origin across the mesh. Each output pointer may be
`NULL` (skipped). If `mesh` is `NULL`, or if `mesh->triangles` is
`NULL`, or if `mesh->vertex_count < 3`, all three outputs are written
as `0.0f`. Otherwise:

- `*min_y` — minimum `y` across all vertices.
- `*max_y` — maximum `y` across all vertices.
- `*max_xz` — maximum of `|x|` and `|z|` across all vertices.

---

# `b3d-voxel.h` — mesh voxelizer

Converts a triangle mesh into an axis-aligned voxel grid — the discrete
cubes whose interior overlaps any input triangle. Also provides two
rendering helpers that emit the resulting voxels through the b3d
rasterizer, and an AABB computer for the input mesh.

The grid is origin-aligned: the cube with integer index `k` along an axis
spans `[k * voxel_size, (k + 1) * voxel_size)`.

## Types

```c
typedef struct { float x, y, z; }                    b3d_voxel_pos_t;
typedef struct { b3d_voxel_pos_t pos; uint32_t color; } b3d_voxel_t;
typedef struct { b3d_voxel_pos_t min, max; }         b3d_aabb_t;
```

`b3d_voxel_pos_t.x/y/z` for a returned voxel is the **center** of that
voxel cube in world space (not a corner).

## API

```c
size_t b3d_voxelize(const float *triangles,
                    size_t tri_count,
                    float  voxel_size,
                    uint32_t color,
                    b3d_voxel_t *out_voxels,
                    size_t max_voxels);
void b3d_voxel_render     (const b3d_voxel_t *voxels, size_t count, float voxel_size);
void b3d_voxel_render_flat(const b3d_voxel_t *voxels, size_t count, float voxel_size);
void b3d_voxel_mesh_aabb  (const float *triangles, size_t tri_count, b3d_aabb_t *aabb);
```

### `b3d_voxelize`

`triangles` is the same flat 9-floats-per-triangle layout `b3d_mesh_t`
uses. `voxel_size` is the edge length of one voxel cube (must be `> 0`).
`color` is the RGB (or with flag bits) written to every produced
voxel's `color` field.

Two modes selected by whether `out_voxels` is `NULL`:

- `out_voxels != NULL`, `max_voxels > 0` — **produce** mode. Overlapping
  voxels are deduplicated so each output entry corresponds to a distinct
  grid cell. Return value:
  - The **unique voxel count** written, when everything fit.
  - `max_voxels + 1` when the output buffer filled up before all
    triangles were processed (truncation indicator). The first
    `max_voxels` entries of `out_voxels` are still valid.
- `out_voxels == NULL` — **estimation** mode. Returns an **upper
  bound** on the unique voxel count for the mesh (each triangle-voxel
  overlap is counted, without deduplication). Useful for sizing an
  output buffer before the second call; allocating 1.5×–2× the
  estimate is a safe cushion.

Returns `0` for invalid input: `triangles == NULL`, `tri_count == 0`, or
`voxel_size <= 0`.

### `b3d_voxel_render(voxels, count, voxel_size)`

Renders each voxel as an axis-aligned cube (six faces, two triangles per
face — twelve triangles per voxel) via `b3d_triangle_lit`. Each face
uses its outward-facing axis-aligned normal for lighting. `voxel_size`
must be `> 0`; the function silently returns if any argument is invalid
(`voxels` NULL, `count == 0`, non-positive `voxel_size`).

### `b3d_voxel_render_flat(voxels, count, voxel_size)`

Same as `b3d_voxel_render` but emits triangles via `b3d_triangle`
(unlit), so the voxel's `color` is used verbatim (still subject to
depth test and culling).

### `b3d_voxel_mesh_aabb(triangles, tri_count, aabb)`

Computes the axis-aligned bounding box of the input triangle set and
writes it to `*aabb`. `aabb->min` and `aabb->max` receive the
component-wise min and max of all vertex positions. A `NULL`
`triangles` or `aabb`, or `tri_count == 0`, is a no-op (the caller's
existing `aabb` is untouched).

---

# Notes on determinism and thread safety

The library uses global state (renderer setup, camera, matrix stack,
lighting, clip-drop counter). It is not thread-safe — do not call any
b3d function from more than one thread concurrently on the same
process.

Given the same sequence of API calls with the same input, the produced
pixel buffer and returned values are deterministic across runs (subject
to floating-point rounding but not to any hidden randomness).

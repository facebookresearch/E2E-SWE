# RKO-LIO Core

Build the C++ **core** of RKO-LIO, a robust LiDAR-Inertial Odometry (LIO) system. The core
estimates the 6-DoF trajectory of a moving platform by fusing a high-rate IMU stream with LiDAR
point-cloud scans: it integrates IMU measurements to predict motion, deskews and downsamples each
scan, and aligns the scan to a running local map with a point-to-plane ICP, maintaining the map as
the platform moves. This task is the sensor-agnostic algorithmic core only — no ROS, no Python, no
file/sensor I/O.

## Dependencies

These libraries are already installed in the environment (offline; do not install anything):

- **Eigen3** (3.4) — linear algebra (`Eigen::Vector3d`, `Eigen::Matrix3d`, …).
- **Sophus** — Lie groups; use `Sophus::SE3d` / `Sophus::SO3d` for rigid transforms.
- **TBB** — threading building blocks (for parallelizing data association).
- **tsl-robin-map** — `tsl::robin_map`, the hash map backing the voxel grid.

The project must be **buildable offline** by a `setup.sh` you provide at the repo root. Use CMake
(C++20) and resolve the dependencies above with `find_package(... CONFIG)` (they are discoverable
via the default CMake prefix; no `FetchContent`/network). `setup.sh` should configure and build the
core library, e.g.:

```bash
#!/bin/bash
set -e
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release <any options your build needs>
cmake --build build -j
```

## Package Structure

All code lives in namespace `rko_lio::core`. Expose the public API through these headers (consumers
and the grader include them by these exact paths, relative to the repo root):

- `rko_lio/core/util.hpp`
- `rko_lio/core/voxel_down_sample.hpp`
- `rko_lio/core/voxel_hash_map.hpp`
- `rko_lio/core/process_timestamps.hpp`
- `rko_lio/core/preprocess_scan.hpp`
- `rko_lio/core/lio.hpp`

Headers may include one another. Implementation `.cpp` files live alongside the headers under
`rko_lio/core/`. Keep the public type names, struct fields, and function signatures below **exactly**
as given — they are the contract.

## API Reference

### `util.hpp` — shared types and helpers

Type aliases and small helpers:

- `using Vector3dVector = std::vector<Eigen::Vector3d>;`
- `using Nsec = std::chrono::nanoseconds;`
- `using TimestampVector = std::vector<Nsec>;`
- `constexpr double square(double x);` — `x*x`.
- `constexpr double GRAVITY_MAG = 9.8107;`
- `inline Eigen::Vector3d gravity();` — returns `{0, 0, -GRAVITY_MAG}`.
- `inline double to_seconds(Nsec d);` — duration in seconds as a `double`.

State / measurement structs (plain aggregates; defaults as shown):

```cpp
struct State {
  Nsec time{0};
  Sophus::SE3d pose;                                          // identity by default
  Eigen::Vector3d velocity = Eigen::Vector3d::Zero();
  Eigen::Vector3d angular_velocity = Eigen::Vector3d::Zero();
  Eigen::Vector3d linear_acceleration = Eigen::Vector3d::Zero();
};
struct ImuBias {
  Eigen::Vector3d accelerometer = Eigen::Vector3d::Zero();
  Eigen::Vector3d gyroscope = Eigen::Vector3d::Zero();
};
struct ImuControl {
  Nsec time{0};
  Eigen::Vector3d acceleration = Eigen::Vector3d::Zero();
  Eigen::Vector3d angular_velocity = Eigen::Vector3d::Zero();
};
```

**`IntervalStats`** — accumulates IMU statistics over the interval between two consecutive LiDAR
scans. Public fields (read directly by consumers):

- `int imu_count = 0;`
- `Eigen::Vector3d angular_velocity_sum;` — running sum of the *unbiased angular velocity* samples.
- `Eigen::Vector3d body_acceleration_sum;` — running sum of the *gravity-compensated* accelerations.
- `Eigen::Vector3d imu_acceleration_sum;` — running sum of the *uncompensated, unbiased* accelerations.
- `double imu_accel_mag_mean = 0;` — online mean of the *magnitude* of the uncompensated unbiased acceleration.
- `double welford_sum_of_squares = 0;` — Welford running sum of squared deviations of that magnitude
  (so the population/sample variance can be derived from it and `imu_count`).

Methods:

- `void update(const Eigen::Vector3d& unbiased_ang_vel, const Eigen::Vector3d& uncompensated_unbiased_accel, const Eigen::Vector3d& compensated_accel);`
  — increment `imu_count`, add to the three running sums, and update `imu_accel_mag_mean` /
  `welford_sum_of_squares` from `uncompensated_unbiased_accel.norm()` using Welford's online
  algorithm.
- `void reset();` — zero every field.

### `voxel_down_sample.hpp`

- `std::vector<Eigen::Vector3d> voxel_down_sample(const std::vector<Eigen::Vector3d>& frame, double voxel_size);`
  — bucket points into cubic voxels of side `voxel_size` and emit **one representative point per
  occupied voxel, keeping its original coordinates** (do not average). Empty input → empty output;
  ordering of the output need not be stable, but the *set* of occupied voxels must be.
- `inline Eigen::Vector3i point_to_voxel(const Eigen::Vector3d& point, double inv_voxel_size);`
  — integer voxel index: component-wise `floor(coord * inv_voxel_size)`.
- `struct VoxelHash { std::size_t operator()(const Eigen::Vector3i& voxel) const; };` — a spatial
  hash of a voxel index suitable for use as the `tsl::robin_map` hash.

### `voxel_hash_map.hpp` — local map

```cpp
using Voxel = Eigen::Vector3i;
using VoxelBlock = std::vector<Eigen::Vector3d>;

struct VoxelHashMap {
  explicit VoxelHashMap(double voxel_size, double clipping_distance, unsigned int max_points_per_voxel);

  void clear();
  bool empty() const;
  void update(const std::vector<Eigen::Vector3d>& points, const Sophus::SE3d& pose);
  void add_points(const std::vector<Eigen::Vector3d>& points);
  void remove_points_far_from_location(const Eigen::Vector3d& origin);
  std::vector<Eigen::Vector3d> pointcloud() const;
  std::tuple<Eigen::Vector3d, double> get_closest_neighbor(const Eigen::Vector3d& query) const;

  double voxel_size_;
  double inv_voxel_size_;
  double clipping_distance_;
  unsigned int max_points_per_voxel_;
  tsl::robin_map<Voxel, VoxelBlock, VoxelHash> map_;
};
```

Behavior: a voxel grid storing up to `max_points_per_voxel` points per voxel (extra points dropped).
`add_points` inserts points (creating voxels as needed, respecting the per-voxel cap).
`update(points, pose)` transforms `points` by `pose`, adds them, then prunes voxels far from the new
location. `remove_points_far_from_location` drops voxels whose center is farther than
`clipping_distance_` from `origin`. `pointcloud` flattens all stored points. `get_closest_neighbor`
returns the nearest stored point to `query` (searching the query voxel and its neighbors) and the
distance to it.

### `process_timestamps.hpp`

```cpp
struct Timestamps { Nsec min; Nsec max; TimestampVector times; };
struct TimestampProcessingConfig {
  double multiplier_to_seconds = 0;   // 0 => auto-detect units
  bool force_absolute = false;
  bool force_relative = false;
};
Timestamps process_timestamps(const std::vector<double>& raw_timestamps,
                              Nsec header_stamp,
                              const TimestampProcessingConfig& config);
```

Normalize per-point scan timestamps to **absolute nanoseconds**. Steps:

1. Throw `std::invalid_argument` if `raw_timestamps` is empty.
2. **Unit detection.** If `multiplier_to_seconds` is effectively zero (auto), decide between seconds
   and nanoseconds from the spread `max-min`: a spread greater than 100 (seconds is implausibly long
   for one scan) means the raw values are already nanoseconds; otherwise they are seconds (multiply
   by 1e9). If `multiplier_to_seconds > 0`, convert with it instead (it maps raw units → seconds).
3. **Absolute vs. relative.** Treat as absolute (use as-is) when `force_absolute`, or the converted
   min is within 1 ms of `header_stamp`, or the converted max is within 10 ms of `header_stamp`.
   Otherwise treat as relative (add `header_stamp` to every time, and to `min`/`max`) when
   `force_relative`, or the converted min is within 1 ms of 0, or the converted max is within 10 ms
   of 0.
4. If neither absolute nor relative applies, throw `std::runtime_error`.

Return the computed absolute `min`, `max`, and the full `times` vector.

### `preprocess_scan.hpp`

```cpp
struct PreprocessingResult {
  Vector3dVector filtered_frame;
  Vector3dVector keypoints;
  Vector3dVector map_frame;   // populated only when config.double_downsample; empty otherwise
};
PreprocessingResult preprocess_scan(const Vector3dVector& frame, const LIO::Config& config);
```

Clip then downsample a raw scan. First keep only points whose range (norm) is strictly inside
`(min_range, max_range)` → `filtered_frame`. Then:

- If `config.double_downsample`: downsample `filtered_frame` at `voxel_size * 0.5` → `map_frame`, and
  downsample `map_frame` at `voxel_size * 1.5` → `keypoints`.
- Else: `keypoints` = downsample of `filtered_frame` at `voxel_size`; `map_frame` is empty.

### `lio.hpp` — the `LIO` class

`class LIO` ties everything together.

`LIO::Config` (defaults shown — these are the documented sensor-agnostic defaults):

```cpp
struct Config {
  bool deskew = true;
  size_t max_iterations = 100;
  double voxel_size = 1.0;
  int max_points_per_voxel = 20;
  double max_range = 100.0;
  double min_range = 1.0;
  double convergence_criterion = 1e-5;
  double max_correspondence_distance = 0.5;
  int max_num_threads = 0;          // 0 = automatic
  bool initialization_phase = false;
  double max_expected_jerk = 3;
  bool double_downsample = true;
  double min_beta = 200;
};
```

Public members (read by consumers):

```cpp
Config config;
VoxelHashMap map;
State lidar_state;                       // current optimized LiDAR pose estimate
ImuBias imu_bias;
Eigen::Vector3d mean_body_acceleration;
Eigen::Matrix3d body_acceleration_covariance;
IntervalStats interval_stats;
std::vector<std::pair<Nsec, Sophus::SE3d>> poses_with_timestamps;  // one entry per registered scan
State imu_state;                         // base-frame state propagated from IMU between scans
explicit LIO(const Config& config_);
```

`mean_body_acceleration` and `body_acceleration_covariance` hold the core's running estimate of the
body acceleration and its dispersion across scan intervals; `initialization_phase`,
`max_expected_jerk` and `min_beta` tune the motion model that maintains that estimate. How the
estimate is formed and used is left to the implementation.

Methods:

- `void add_imu_measurement(const ImuControl& base_imu);` — ingest one IMU sample already expressed
  in the **base** frame. Subtract the current biases, compensate gravity (using the current
  orientation estimate) to obtain body acceleration, integrate to propagate `imu_state` (orientation
  from angular velocity, then velocity/position from acceleration), and feed `interval_stats`. IMU
  samples that arrive before the first LiDAR scan (before initialization) are dropped.
- `void add_imu_measurement(const Sophus::SE3d& extrinsic_imu2base, const ImuControl& raw_imu);` —
  transform a raw IMU sample from the IMU frame into the base frame using `extrinsic_imu2base`
  (rotate angular velocity and acceleration; account for the lever arm as appropriate), then behave
  like the base-frame overload. An identity extrinsic must be equivalent to the base-frame overload.
- `Vector3dVector register_scan(const Vector3dVector& scan, const TimestampVector& timestamps);` —
  register one LiDAR scan (already in the base frame) captured with per-point absolute `timestamps`.
  Throw `std::invalid_argument` if `timestamps` is empty. A scan's **reference time** — the value
  written to `lidar_state.time`, stored as its `poses_with_timestamps` entry's timestamp, and the
  common time the scan is deskewed to — is the **latest (maximum)** per-point timestamp of the scan
  (scan-end convention). On the **first** scan, initialize state at that scan time, seed the map from
  the scan, append the pose to `poses_with_timestamps`, and return the processed cloud. On subsequent scans: form a motion prior from the IMU interval, optionally
  **deskew** the scan to a common time using that prior (when `config.deskew`), preprocess
  (clip + downsample), run **point-to-plane ICP** against `map` (iterating up to `max_iterations`,
  stopping when the update norm falls below `convergence_criterion`, rejecting correspondences beyond
  `max_correspondence_distance`), write the optimized pose into `lidar_state`, re-anchor `imu_state`
  to that optimized pose (the transient `velocity` / `angular_velocity` / `linear_acceleration` cache
  fields carry no separately-specified post-scan value), update `map`, and append `(time, pose)` to
  `poses_with_timestamps`. Returns the deskewed-and-clipped scan.
- `Vector3dVector register_scan(const Sophus::SE3d& extrinsic_lidar2base, const Vector3dVector& scan, const TimestampVector& timestamps);`
  — same, but the scan is in the **lidar** frame and must be brought into the base frame via
  `extrinsic_lidar2base` for registration; the returned cloud is expressed back in the lidar frame.

Registering the same scan twice (identical cloud, no motion) must recover ~identity relative motion;
a pure translation or pure rotation between two scans must be recovered by ICP to within a small
tolerance.

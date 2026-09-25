# Semantic Versioning CLI (from git history)

Build a command-line tool, `gitv`, that computes a Semantic Version (SemVer 2.0) for a git repository from its commit history, tags, branch name, and configuration. Organize the solution however you like; only the CLI's observable behaviour (specified below) is graded.

## Build & invocation

Offline environment: .NET SDK 10 (target `net10.0`), an offline NuGet feed with the packages you need, and the `git` CLI. There is no network at build or run time.

Provide an executable `/app/setup.sh` that builds your solution and produces an executable at `/app/dist/gitv`, runnable as `/app/dist/gitv <args>`. The grader runs `bash ./setup.sh` from `/app` before invoking the CLI.

## Command-line interface

```
gitv [path] [options]
```

- `path` (positional, optional) — the working directory of the target git repository. Defaults to the current directory.
- Options (a `-name` form, case-insensitive):
  - `-config <path>` — read configuration from the YAML file at the given path.
  - `-overrideconfig <key=value>` — override a single configuration value; may be repeated.

The tool prints the computed version as a single JSON object of version variables to stdout.

## Output (JSON object)

The JSON object has these keys, sorted alphabetically.

- `Major`, `Minor`, `Patch` — the numeric version components.
- `MajorMinorPatch` — `"{Major}.{Minor}.{Patch}"`.
- `PreReleaseTag` — the pre-release tag, e.g. `alpha.2`; `label.number`, or just `number` when the label is empty, or just `label` when there is no number (empty when there is no tag).
- `PreReleaseLabel` — the label part only (e.g. `alpha`); empty for stable branches.
- `PreReleaseNumber` — the numeric part of the pre-release tag.
- `WeightedPreReleaseNumber` — `PreReleaseNumber` plus the branch's `pre-release-weight` (defaulting to the global `tag-pre-release-weight` when the branch defines none). When there is no pre-release number because HEAD sits exactly on a stable tag, it is the global `tag-pre-release-weight` (60000) alone, not the branch's own weight. `main`'s weight is 55000 (so `main` with pre-release number N gives 55000+N).
- `SemVer` — `MajorMinorPatch` plus `-PreReleaseTag` when present (no build metadata).
- `FullSemVer` — `SemVer` plus `+BuildMetaData` when build metadata is present.
- `InformationalVersion` — `FullSemVer` plus `+` plus `FullBuildMetaData` (it ends at `.Sha.<Sha>`, with nothing appended after the sha).
- `AssemblySemVer` — assembly version, `"{Major}.{Minor}.{Patch}.0"` under the default scheme.
- `BuildMetaData` — the commit count when it is surfaced as `+build` metadata (e.g. `ManualDeployment`); `null` when no build metadata applies, including on `main` under `ContinuousDelivery` where the count is carried in the pre-release number instead. (The raw count is always in `CommitsSinceVersionSource`.)
- `FullBuildMetaData` — `BuildMetaData` plus `Branch.<BranchName>.Sha.<Sha>` (leading `.` trimmed).
- `BranchName` — the branch the version was computed on. `EscapedBranchName` replaces characters that are invalid in environment-variable names (e.g. `/`) with `-`.
- `Sha` — the full HEAD commit SHA; `ShortSha` — its 7-character prefix.
- `CommitDate` — the HEAD commit date, formatted `yyyy-MM-dd` (UTC) by default.
- `CommitsSinceVersionSource` — the commit count between the version source and HEAD.
- `VersionSourceSemVer` — the SemVer of the resolved base version (before the increment is applied). When the base comes from `next-version` or a branch name rather than a tag, this reports that effective base version (e.g. `2.0.0`), not the underlying tag's version; `VersionSourceSha` — the source commit's SHA, i.e. the commit `CommitsSinceVersionSource` is measured from. It stays anchored to that underlying tag / branch-point commit even when the base version itself is supplied by `next-version`, a branch name, or a merged `release`/`hotfix` version.
- `UncommittedChanges` — count of uncommitted changes in the working tree.

The numeric variables (`Major`, `Minor`,
`Patch`, `BuildMetaData`, `PreReleaseNumber`, `CommitsSinceVersionSource`, `UncommittedChanges`) are JSON numbers (and JSON `null` when empty); `WeightedPreReleaseNumber` is always a number, all other variables are JSON strings.

## Version calculation

The version is `(base version) → (increment) → (deployment-mode formatting)`.

### Base version

The base version is the highest version produced by any of these sources:

- The highest version tag reachable from HEAD (honouring the configured `tag-prefix`, default `[vV]?`, so `v1.2.0` and `1.2.0` both parse). Tags that are not valid versions are ignored. When several version tags are reachable, the highest is used.
- The version embedded in a release/hotfix branch name (e.g. `release/2.0.0`, `hotfix/1.2.1`), or the version of a merged `release`/`hotfix` branch taken from its merge commit message (merging `release/2.0.0` into `main` yields base `2.0.0`).
- The configured `next-version`.
- Otherwise the fallback `0.0.0`.

### Increment

The base version is incremented by one field — the branch's configured increment (see defaults below), which a commit-message directive in the commits since the source can raise but not lower: `+semver: major`/`minor`/`patch` forces that field, and `+semver: none` suppresses a message-driven bump (the branch default still applies). When several commits carry directives, the highest applies.

Only a base taken from a stable version tag (or the `0.0.0` fallback) is incremented this way. A base supplied by `next-version`, by a `release`/`hotfix` branch name, or by a merged `release`/`hotfix` version is a not-yet-released target, so its `MajorMinorPatch` is used verbatim with no branch increment — just like a pre-release tag (e.g. `next-version=3.0.0` gives base `3.0.0`, and merging `release/2.0.0` into `main` gives base `2.0.0`, not `2.0.1`).

### Tag on HEAD

If HEAD is exactly the commit of a stable version tag, that tag's version is emitted verbatim with no increment (e.g. HEAD on `v1.0.0` → `1.0.0`) — but only on branches that produce stable versions (empty label, e.g. `main`/`support`). On a pre-release branch (e.g. `develop`) the branch's increment and pre-release label still apply.

### Pre-release version tags

A tag that is itself a pre-release (e.g. `v1.0.0-beta.1`) marks its `MajorMinorPatch` as not yet released: it becomes the base without applying the branch increment (unlike a stable tag, which bumps).
The version stays on that `MajorMinorPatch`, and — because a pre-release tag is not itself treated as the version source — the pre-release number counts all commits reachable from HEAD (from the base, not from the tag). So the tagged commit itself is number 1 and each further commit increments it. (Contrast a stable tag of the same version, where a later commit increments the patch instead.)

### Detached HEAD

When HEAD is not on a branch, the version is computed using the configuration of the branch that contains the commit (e.g. a detached HEAD at `main`'s tip resolves exactly as `main` would).

### Pre-release label & number

The label comes from the branch configuration (defaults below); the number reflects the commits since the version source — counting merge commits and the commits they bring in (all commits reachable from HEAD since the source). The exact shape depends on the deployment mode of the branch:

- `ContinuousDelivery` — the pre-release number advances with each commit past the source (a unique pre-release per commit), with no `+build` metadata.
- `ContinuousDeployment` — the pre-release tag is stripped; every commit is a stable release.
- `ManualDeployment` — the pre-release number stays at its baseline (`1`) and the commit count is appended as `+build` metadata.

## Default configuration (GitFlow)

The effective configuration is the GitFlow preset (defaults below); individual values can be changed with `-overrideconfig`.

Global defaults include: `mode: ContinuousDelivery`, `tag-prefix: "[vV]?"`, `assembly-versioning-scheme: MajorMinorPatch`, `commit-date-format: yyyy-MM-dd`, `tag-pre-release-weight: 60000`, and the `+semver` regexes above.

Per-branch defaults (branch is matched by regex against the current branch name):

| Branch | regex (summary) | increment | label | mode | pre-release-weight |
|---|---|---|---|---|---|
| main | `^master$\|^main$` | Patch | `` (stable) | ContinuousDelivery | 55000 |
| develop | `^dev(elop)?(ment)?$` | Minor | `alpha` | ContinuousDelivery | 0 |
| release | `^releases?[/-](.+)` | Minor | `beta` | ManualDeployment | 30000 |
| feature | `^features?[/-](.+)` | Inherit | `{BranchName}` | ManualDeployment | 30000 |
| pull-request | `^(pull\|pull-requests\|pr)[/-](?<Number>\d+)` | Inherit | `PullRequest{Number}` | ContinuousDelivery | 30000 |
| hotfix | `^hotfix(es)?[/-](.+)` | Inherit | `beta` | ManualDeployment | 30000 |
| support | `^support[/-](.+)` | Patch | `` (stable) | ContinuousDelivery | 55000 |

`Inherit` takes the increment of the branch the current branch was created from (its source), e.g. a `feature` off `develop` inherits `Minor`, off `main` inherits `Patch`.
When the source is a `release`/`hotfix` branch, the branch instead adopts that source branch's own version as its base with no increment applied, keeping its own label — so a `feature` off `release/2.0.0` yields `2.0.0-{label}...` (not `2.1.0`/`2.0.1`), with the commit count taken from the underlying version source.
`{BranchName}` expands to the portion of the branch name captured by the branch regex's group — the name with its matched prefix (e.g. `feature/`) removed: `feature/foo` → label `foo`. This captured label is distinct from the `BranchName` output variable (which keeps the full name, `feature/foo`) and from `EscapedBranchName` (`feature-foo`). A branch that matches none of these is treated as an unknown branch and uses the matched name as its label.

## Configuration

`-config <path>` reads a YAML configuration file from the given path. Keys use hyphenated names — `tag-prefix`, `next-version`, `mode`, `label`, ... (e.g. a file containing `mode: ContinuousDeployment` or `tag-prefix: ver`).

`-overrideconfig <key=value>` overrides individual configuration values on the command line; it may be repeated and takes precedence over both the `-config` file and the defaults. For example: `-overrideconfig tag-prefix=ver`, `-overrideconfig next-version=3.0.0`, `-overrideconfig mode=ContinuousDeployment`.

`-overrideconfig workflow=TrunkBased/preview1` switches to the trunk-based workflow: `main` uses the Mainline strategy (each commit increments patch) in ContinuousDeployment mode, so N commits with no tag give `0.0.N`.

The commit-message increment directives are themselves configurable regexes: `major-version-bump-message`, `minor-version-bump-message`, and `patch-version-bump-message` (the default set matches the `+semver:` directives above). Each is tested against the full text (subject and body) of every commit message since the version source; the highest matching field wins (major > minor > patch) and a commit matching none leaves the branch default. Overriding them via `-config` therefore adapts the bump rules to other commit conventions (e.g. Conventional Commits, where a `BREAKING CHANGE:` footer in the body bumps major).

The `ignore` config (set via a `-config` file) excludes commits from the calculation:
`ignore: { sha: [<sha>, ...] }` drops those commits (reducing the commit count), and
`ignore: { commits-before: <timestamp> }` drops every commit dated before the timestamp — including a tagged one, so if the version tag is excluded the base falls back to `0.0.0`.

## Error behaviour

The CLI exits non-zero with a clear message when it cannot compute a version:

- Target directory is not a git repository → `Cannot find the .git directory`.
- Repository has no commits → `No commits found on the current branch.`

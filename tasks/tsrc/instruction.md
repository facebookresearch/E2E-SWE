# tsrc

Build `tsrc`, a Python CLI tool for managing groups of git repositories via a YAML manifest.

## Dependencies

The environment is **offline** and all dependencies are **already installed** — do not install anything (there is no network). The runtime libraries available are `cli-ui`, `colored_traceback`, `ruamel-yaml`, `schema`, and `mypy_extensions` (plus `git`, which the CLI shells out to). The project is installed for you by a `setup.sh` that runs offline (see below); just implement the package so that an editable install exposes the `tsrc` console script.

## Package Structure

Importable as `tsrc`. The CLI entry point is `tsrc.cli.main:main` (console script `tsrc`).

## CLI Commands

All commands accept `--verbose`, `-q`/`--quiet`, `--color {auto,always,never}`, and `--version` (prints `tsrc <version>`).

- **tsrc init** `<manifest_url> [--branch BRANCH] [--shallow] [-g GROUP...] [--clone-all-repos] [-r REMOTE] [-w PATH] [-j JOBS]` -- Initialize workspace: clone manifest repo into `.tsrc/manifest/`, save config to `.tsrc/config.yml`, clone repos. The manifest repository URL is recorded in `.tsrc/config.yml` under the key `manifest_url`; later commands read it back from that key to locate the manifest remote. `--shallow` creates depth-1 clones; it is incompatible with sha1-pinned repos, so when `--shallow` is combined with a selected repo that carries a `sha1` pin, tsrc prints a clear error and exits non-zero. `-r REMOTE` specifies a single remote name to use for cloning; this choice is recorded in `.tsrc/config.yml` (under a `singular_remote` key) so later commands honor the single-remote selection. When a repo entry declares several named remotes via a `remotes:` list, `tsrc init` configures ALL of those declared remotes on the freshly cloned repo, so immediately after `tsrc init` — without any subsequent `sync` — the clone has every declared remote configured. Running `tsrc init` in a directory that is already an initialized tsrc workspace (a `.tsrc/config.yml` already exists at the target root) is an error: tsrc prints a clear message that the workspace is already configured and exits non-zero, rather than re-initializing or updating it in place.
- **tsrc sync** `[--force] [--no-update-manifest] [--no-update-config] [--no-correct-branch] [--switch] [--clean] [--hard-clean] [-g GROUP...] [--all-cloned] [-i REGEX] [-e REGEX] [-r REMOTE] [-w PATH] [-j JOBS]` -- Update workspace. Merges upstream using fast-forward only (`merge --ff-only @{upstream}`). For tag/sha1-pinned repos, resets to the ref (refuses if dirty). By default, corrects the branch to match the manifest (skipped with error if dirty). `--no-correct-branch` disables branch correction. Sync pulls the manifest from the URL recorded under `manifest_url` in `.tsrc/config.yml`, so editing that key changes which remote the manifest is fetched from. Repointing `manifest_url` (or the manifest branch) to a different manifest repository fully takes effect on the next sync: the internal `.tsrc/manifest/` bookkeeping checkout is updated to match the configured remote's branch HEAD even when that remote's history does not fast-forward from the current checkout, so repos newly listed in the new manifest are cloned and repos no longer listed are dropped from the sync. By default, sync refreshes the workspace's configured `repo_groups` in `.tsrc/config.yml` from the manifest/CLI groups; `--no-update-config` leaves the existing `repo_groups` untouched. `--force` passes `--force` to git fetch. `--switch` applies the manifest's `switch.config` section to update workspace configuration: it replaces the configured `repo_groups` with the manifest's `switch.config.groups` (intersected with the available groups), so after `--switch` the config's `repo_groups` is exactly that switch group set, not the previous groups. `--clean` runs `git clean -f -d`, `--hard-clean` additionally runs `git clean -f -X -d`. Fetches with `--tags --prune`. Sync reconciles each repo's git remotes with its manifest entry: any remote declared in the manifest that is missing on an already-cloned repo is added (so adding an `upstream` remote to a repo's manifest entry causes the next sync to configure `upstream` on the existing clone), then all configured remotes are fetched. After updating repos, sync re-applies the manifest's filesystem operations (the `copy` and `symlink` directives) for the selected repos, so a changed source file is re-copied and a removed symlink is re-created on every sync. Sync exits non-zero if any selected repo fails to sync (the other repos are still processed). A repo counts as failing to sync when its remote cannot be fetched (e.g. an unreachable or deleted remote), when its branch cannot be fast-forwarded onto its upstream (a non-fast-forward divergence under the ff-only merge), when a tag/sha1-pinned repo is dirty (the reset is refused), or — with branch correction enabled — when a dirty repo's branch cannot be corrected; under `--no-correct-branch`, a repo left on detached HEAD (on no branch) likewise counts as a failure.
- **tsrc status** `[-g GROUP...] [--all-cloned] [-i REGEX] [-e REGEX] [--no-dm] [--no-fm] [--no-mm] [--local-git-only] [--strict] [--show-leftovers-status] [-w PATH] [-j JOBS]` -- Report repo status. Prints a header with the manifest branch, then for each repo: its dest, current branch name, ahead/behind counts relative to upstream (using `+`/`-` indicators), dirty state, and wrong-branch indicator (`(expected: <branch>)`) if the repo is on a different branch than the manifest specifies. A repo with uncommitted or untracked changes is annotated with the literal marker `(dirty)` (after the branch / ahead-behind info); a clean repo shows no such marker. `--local-git-only` skips all remote access (computes status from local git state only, without fetching). Status reports **only the currently selected repos**: a repo that exists on disk in the workspace but is excluded from this invocation's selection (e.g. filtered out by `-g`/`--groups`, `-i`, or `-e`) does NOT appear anywhere in the output — neither as a status line nor as a "leftover" — so `status -g <group>` never surfaces the name of an in-manifest repo that is outside `<group>`. The "leftover repo descriptions" that `--strict` omits (and that `--show-leftovers-status` augments with full git status) refer only to repos that are part of the workspace's manifest bookkeeping but absent from the current selected repo set; they are shown by default and are never triggered merely by a repo being excluded via the selection flags above.
- **tsrc foreach** `[--] CMD... [-c 'SHELL_CMD'] [-g GROUP...] [--all-cloned] [-i REGEX] [-e REGEX] [-X] [-w PATH] [-j JOBS]` -- Run command in each repo. Before running the command in a repo, prints a per-repo header line that includes the repo's `dest` (its path), so each repo's output is preceded by a header identifying it. The command is given either directly (`-- CMD...`, run without a shell) or as a single shell string via `-c` (run through the shell); the two forms are mutually exclusive. When `-c` is used, exactly one command token must be supplied — invoking `-c` with zero tokens, or with more than one token (e.g. `foreach -c echo hello`, which leaves a surplus positional alongside `-c`), is an error and exits non-zero. Invoking `foreach` with no command at all is likewise an error and exits non-zero. Reports failures, non-zero exit if any fail. Raises error if repo directory missing.
- **tsrc log** `--from FROM [--to TO] [-g GROUP...] [--all-cloned] [-i REGEX] [-e REGEX] [-w PATH] [-j JOBS]` -- Show `git log` between refs (`--to` defaults to `HEAD`). Only repos that have commits in the `from..to` range are shown; a repo with an empty range is omitted from the output entirely. Errors if `FROM`/`TO` cannot be resolved in a selected repo.
- **tsrc apply-manifest** `<manifest_path> [-w PATH] [-j JOBS]` -- Apply local manifest: clone missing repos, perform filesystem ops.
- **tsrc manifest** `[-b BRANCH] [-g GROUP...] [--all-cloned] [-i REGEX] [-e REGEX] [-w PATH]` -- Manage manifest config. `-b` changes manifest branch.
- **tsrc dump-manifest** `[--raw RAW_PATH] [-u] [-U PATH] [--no-repo-delete] [--sha1-on] [--sha1-off] [-X] [-M] [-p] [-s PATH] [-f] [-g GROUP...] [--all-cloned] [-i REGEX] [-e REGEX] [-w PATH] [-j JOBS]` -- Dump workspace state as manifest YAML. `--raw RAW_PATH` creates manifest from raw git repos found recursively in a directory (no workspace needed); computes a COMMON PATH from discovered repos and uses it for `dest` values. Raw mode emits one repo entry for **every** git repository discovered under RAW_PATH, whether or not the repository has a configured git remote — a discovered repo is never dropped for lacking a remote. A discovered repo that has no remote is emitted with its computed common-path `dest` but with no remote information: its entry carries neither a `url` nor a `remotes` field (both are simply omitted for that repo). `-p`/`--preview` outputs the resulting manifest to stdout (preview mode) and makes no filesystem write. `-p` has the highest priority of the destination options: when combined with an update (`-u`/`-U`) the computed updated manifest is written to stdout instead of being written in place, so `dump-manifest -u -p` (or `-U PATH ... -p`) previews the updated manifest on stdout and does not modify any file on disk. `-s PATH` saves output to a specified file. `-f` allows overwriting an existing file (required when `-s` targets an existing file). `-u`/`--update` updates the Deep Manifest in-place with current workspace state. The Deep Manifest is the manifest repository **as checked out at its workspace dest** — i.e. the repo whose remote URL matches the configured `manifest_url`, located at `<workspace-root>/<manifest-dest>/manifest.yml` (e.g. `workspace/manifest/manifest.yml` when the manifest is listed as a repo with `dest: manifest`), **not** the internal `.tsrc/manifest/` bookkeeping clone. So a `-u` write lands in that dest-checked-out `manifest.yml`, and any freshly-observed workspace state (such as a repo's current local branch) is reflected there. `-U PATH`/`--update-on PATH` updates a specific manifest file at PATH. `--no-repo-delete` prevents deletion of repo entries from the manifest during update, even if those repos are no longer in the workspace. `--sha1-on` includes sha1 hashes for every repo. `--sha1-off` excludes sha1 hashes. `--sha1-on` and `--sha1-off` are mutually exclusive: providing both fails with an error message containing the phrase `mutually exclusive` (e.g. `'--sha1-on' and '--sha1-off' are mutually exclusive`). `-X`/`--skip-manifest-repo` skips the manifest repo from the output. `-M`/`--only-manifest-repo` dumps only the manifest repo. `-i`/`-e` regex filters apply to raw mode as well. When updating (`-u`/`-U`), if a repo's URL matches an existing entry but the `dest` has changed, the entry is renamed rather than deleted and re-added. Groups and their `includes` directives are preserved during updates. A repo's existing per-repo pin fields (`tag` and `sha1`) are likewise preserved from the source manifest entry unless the current workspace state requires changing them, so a repo still checked out at a pinned tag keeps its `tag: <name>` in the updated manifest (a detached tag checkout is not downgraded to a bare `sha1`). Capturing "current workspace state" also includes each cloned repo's currently checked-out local branch: the updated/previewed entry's `branch` reflects the branch the repo is on as observed on disk. Errors in dump-manifest are caught internally and printed as an error message (the command may still exit 0).

Running `tsrc` with no subcommand prints help and exits non-zero. Running commands outside a workspace produces a clear error and exits non-zero. tsrc discovers the workspace by walking up the directory tree from the current directory (or `-w` path) to find `.tsrc/`.

## Manifest Format

YAML file (`manifest.yml`):

```yaml
repos:
  - dest: repo_name
    url: git@example.com:org/repo.git
    branch: main              # optional, defaults to "master"
    tag: v1.0                 # optional
    sha1: abc1234             # optional
    ignore_submodules: false  # optional
    copy:                     # optional
      - file: src_file
        dest: dest_file       # optional, defaults to src_file
    symlink:                  # optional
      - source: link_path
        target: target_path
  - dest: another_repo
    remotes:                  # alternative to url
      - name: origin
        url: git@example.com:org/repo.git
      - name: upstream
        url: git@example.com:other/repo.git

groups:
  default:
    repos: [repo_name]
  backend:
    repos: [another_repo]
    includes: [default]       # optional, include other groups

switch:                         # optional
  config:
    groups: [backend]           # groups applied with --switch
```

A repo must have either `url` (creates an `origin` remote) or `remotes`, but not both. A repo entry that violates this — declaring **both** `url` and `remotes`, or **neither** — is an invalid manifest: any command that loads the manifest prints a clear error and exits non-zero.

By default (`ignore_submodules: false`) repos are cloned with their git submodules recursed into and checked out, and `sync` runs a submodule update so submodules are initialized. When `ignore_submodules: true`, submodules are left untouched: the repo is cloned without recursing into submodules and `sync` does not initialize them, so a submodule's working tree stays empty.

When the environment variable `TSRC_TESTING` is set (to any non-empty value), tsrc must permit git's `file://` protocol on the git operations it runs (pass `-c protocol.file.allow=always` to git). Git disables `file://` for clone and submodule operations by default (CVE-2022-39253), so without this a clone or submodule recursion against a local `file://` remote silently fails to populate the submodule. This relaxation applies only when `TSRC_TESTING` is set.

Copy and symlink destinations are resolved relative to the **workspace root**. For a `copy` directive, `file` is read from the repo's own `dest` directory and written to `dest` under the workspace root; `dest` defaults to the source filename. For a `symlink` directive, `source` is the symlink path created under the workspace root and `target` is the existing path it points to.

## Repo Selection

Commands that operate on repos support `-g`/`--groups`, `--all-cloned`, `-i` (include regex), `-e` (exclude regex). Without flags, uses configured groups, or all repos if `clone_all_repos` is set, or the `default` group if it exists. Selecting a group via `-g`/`--groups` that is not defined in the manifest is an error: the command prints a clear error naming the unknown group and exits non-zero, rather than silently operating on an empty set of repos.

## setup.sh

The project is installed offline against the pre-baked dependencies:

```bash
pip install -e . --no-build-isolation
```

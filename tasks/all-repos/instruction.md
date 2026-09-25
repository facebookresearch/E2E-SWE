# all-repos

Build `all_repos`, a Python tool to **clone many git repositories and apply sweeping changes across all of them**. It provides a set of command-line tools (clone, query, and bulk-edit) plus a small library for writing your own "autofixers".

Everything operates on ordinary local git repositories — there is no dependency on any specific git host for the functionality described here.

## Example use case

all-repos clones every repository a *source* lists into an output directory, then lets you query across the checkouts or apply a sweeping change. A minimal config (`all-repos.json`, which must be mode `0o600`) uses the `json_file` source and a read-only push:

```json
{
    "output_dir": "output",
    "source": "all_repos.source.json_file",
    "source_settings": {"filename": "repos.json"},
    "push": "all_repos.push.readonly",
    "push_settings": {}
}
```

```console
$ all-repos-clone -C all-repos.json                       # clone/update every repo into output/
$ all-repos-grep -C all-repos.json 'TODO'                 # distributed git grep across checkouts
$ all-repos-sed -C all-repos.json 's/foo/bar/g' -- '*.py' # bulk edit, committed via the autofixer
```

## Dependencies

The environment is **offline** and every dependency below is **already installed** — do not attempt to install, download, or clone anything.

- Python 3.10.
- PyPI packages (pre-installed): `identify`, `packaging`, and `contextlib-chdir` (the `contextlib.chdir` backport for Python < 3.11; on 3.10 use `from contextlib_chdir import chdir`).
- The `git` command-line tool and GNU `sed` are available on `PATH` (invoked as subprocesses); they are pre-installed.
- The project must be installable offline by a `setup.sh` (a `setup.py` / `setup.cfg` / `pyproject.toml` installable with `pip install -e . --no-build-isolation`); the build backend is pre-installed.

Organize the package internals (modules, helpers, file layout) however you like, as long as the import paths, console commands, output formats, and exit codes described below resolve exactly.

## Console scripts

Installing the package must provide these console entry points:

```
all-repos-clone  all-repos-find-files  all-repos-grep  all-repos-list-repos
all-repos-sed    all-repos-manual      all-repos-complete
```

### Common options (all commands)

- `-C CONFIG` / `--config-filename CONFIG`: config file to use. Default is the value of the `ALL_REPOS_CONFIG_FILENAME` environment variable, or `all-repos.json` if unset.
- `--color {auto,always,never}`: colorize output (default `auto`: color only when stdout is a TTY). With `never`, output contains no ANSI escapes.

## Configuration file

A JSON object. Example:

```json
{
    "output_dir": "output",
    "source": "all_repos.source.json_file",
    "source_settings": {"filename": "repos.json"},
    "push": "all_repos.push.merge_to_master",
    "push_settings": {}
}
```

Keys:

- `output_dir` (required): directory the repositories are cloned into. **It is resolved relative to the directory containing the config file.**
- `source` (required): import path of a *source* module (see below). `source_settings` is a JSON object passed to that module.
- `push` (required): import path of a *push* module (see below). `push_settings` is a JSON object passed to that module.
- `include` (default `""`): a Python regex; only repo names matched (via `re.search`) are included.
- `exclude` (default `"^$"`): a Python regex; repo names matched are excluded.
- `all_branches` (default `false`): if true, clone every branch instead of only the default branch.

Validation (performed when a config is loaded, i.e. at the start of every command):

- The config file must have permissions exactly `0o600`. Otherwise exit with this message (to stderr) and a non-zero status:
  ```
  {config_path} has too-permissive permissions, Expected 0o600, got 0o{actual:o}
  ```
- The `output_dir`, if it already exists and is non-empty, must either contain a `.all-repos` marker file, or contain *only* `repos.json`, `repos_filtered.json`, and directories. Otherwise exit non-zero with:
  ```
  output_dir should only contain repos.json, repos_filtered.json, and directories
  ```

## Sources

A *source* lists the repositories to clone. A source module exposes:

- a `Settings` type constructed with the `source_settings` JSON as keyword arguments, and
- `list_repos(settings) -> dict[str, str]` mapping `repo_name -> clone_url`. The `repo_name` becomes the directory name (it may contain `/`, creating nested directories) inside `output_dir`.

Implement these three built-in sources:

### `all_repos.source.json_file`

`Settings` takes a single `filename`; `list_repos` returns the JSON object (a `{name: url}` mapping) read from that file.

### `all_repos.source.github`

Clones the repositories visible to an authenticated GitHub user.

- `Settings` fields: `username` (required), `collaborator=False`, `forks=False`, `private=False`, `archived=False`, `base_url='https://api.github.com'`, `api_key=None`, `api_key_env=None`.
- `list_repos` issues a GET to `{base_url}/user/repos` (the per-page size is up to you) and **follows pagination via the `Link` header** (request the URL given by the `rel="next"` link until there is none), accumulating all returned repo objects.
- Each repo object has at least: `full_name` (str), `ssh_url` (str), `fork` (bool), `private` (bool), `archived` (bool), and `permissions` (an object with an `admin` bool — `admin` is false for a repo the user can only contribute to as a collaborator).
- Keep a repo only when **all** of these hold: `forks or not fork`, `private or not private`, `collaborator or permissions.admin`, `archived or not archived`.
- Return `{full_name: ssh_url}`, with a single trailing `.git` removed from each `ssh_url`.

### `all_repos.source.gitlab_org`

Clones the projects in a GitLab group.

- `Settings` fields: `org` (required), `base_url='https://gitlab.com/api/v4'`, `archived=False`, `api_key=None`, `api_key_env=None`.
- `list_repos` issues a GET to `{base_url}/groups/{org}/projects?with_shared=False&include_subgroups=true` (URL-escape `org`) and **follows `Link` `rel="next"` pagination** like the github source.
- Each project object has at least `path_with_namespace` (str), `ssh_url_to_repo` (str), and `archived` (bool).
- Keep a project only when `archived or not archived`. Return `{path_with_namespace: ssh_url_to_repo}` (do not strip `.git` here).

**API key resolution (github + gitlab_org):** exactly one of `api_key` / `api_key_env` must be provided. This is resolved lazily **when `list_repos` issues a request**, not at `Settings` construction — constructing a `Settings` with neither key (or both) must succeed, and the `ValueError` surfaces only from the `list_repos` call. When `api_key_env` is given, it names an environment variable holding the token; the token is sent as an authentication header on each request.

(Sources for Bitbucket, Azure, gitolite, and other GitHub/GitLab variants talk to external hosting APIs that aren't reachable here and are **out of scope** — you do not need to implement them.)

## `all-repos-clone`

Clone (or update) all repositories into `output_dir`.

Behavior:

- Compute the repo list from the source, then keep only names matching `include` and not matching `exclude`.
- For each selected repo, ensure `output_dir/<name>` is a git checkout of the repo's current upstream **default branch** at its latest commit. Re-running the command updates existing checkouts to the latest upstream commit.
- A repo present in `output_dir` but no longer selected is **removed**, and any directories left empty by that removal are also removed.
- If a repo cannot be fetched (e.g. an unreachable URL), print `Error fetching {output_dir/name}` and continue with the others (the command still exits `0`).
- With `all_branches: true`, all upstream branches are fetched (available as `origin/*` remote-tracking refs) instead of only the default branch.

After processing, write into `output_dir`:

- `repos.json`: the **full** `{name: url}` mapping from the source (source order).
- `repos_filtered.json`: the selected mapping, **sorted by name**.
- an empty `.all-repos` marker file.

Exit `0` on success.

## Query commands

These read `repos_filtered.json` to know which repos exist, and operate on the checkouts in `output_dir`. In their output, a repository is identified by its **full path** `output_dir/<name>`.

### `all-repos-find-files [options] PATTERN`

Find files whose path matches the Python regex `PATTERN` in each repo. `PATTERN` is applied with `re.search` (an unanchored substring match) to each repo-relative path produced by `git ls-files` — so it can match anywhere in the path, not just the basename.

- Default output, one line per matching file: `{repo_path}:{filename}`.
- `--output-paths`: join repo and filename with the OS path separator instead of `:`, i.e. `{repo_path}/{filename}`.
- `--repos-with-matches`: print only `{repo_path}` for repos that have at least one match.
- Exit `0` if there were any matches, non-zero otherwise (and print nothing when there are none).

### `all-repos-grep [options] [GIT_GREP_OPTIONS...]`

A distributed `git grep`. Any options not recognized below are passed straight through to `git grep`.

- Default output, sorted by repo: `{repo_path}:{git_grep_line}` for every line `git grep` produces in each repo (so a plain pattern yields `{repo_path}:{file}:{matching_line}`).
- `--repos-with-matches`: print only the matching `{repo_path}`, sorted.
- `--output-paths`: use the OS path separator instead of `:` between the repo path and the rest of the line.
- Exit `0` if any repo matched, `1` if none matched. If `git grep` fails for another reason (for example, **no pattern given**, which `git grep` exits `128` for), propagate that exit code.

### `all-repos-list-repos [options]`

Print the name of each cloned repo (the keys of `repos_filtered.json`), one per line. With `--output-paths`, print the full `output_dir/<name>` path instead.

## `all-repos-complete --bash | --zsh`

Print a shell completion script to stdout. The first line must be:

```
__all_repos__repos_json={output_dir}/repos_filtered.json
```

followed by the bash or zsh completion body (the bash body references `git clone`).

## Autofixers

An *autofixer* applies a change across repositories: for each repo it creates a branch, runs your change, and—if anything changed—commits and pushes it. The library module `all_repos.autofix_lib` provides:

### `autofix_lib.add_fixer_args(parser)`

Add the standard autofixer options to an `argparse` parser. These include the common options (`-C`, `--color`) plus:

- `--dry-run`: make and show the change but do not push.
- `-i` / `--interactive`: prompt for approval of each repo before committing.
- `--limit LIMIT`: process at most `LIMIT` repos.
- `--author AUTHOR`: override the commit author, passed through to `git commit --author` (e.g. `'A B <a@a.a>'`).
- `--repos REPOS [REPOS ...]`: operate on exactly these repository paths instead of discovering them.

### `autofix_lib.from_cli(args, *, find_repos, msg, branch_name)`

Returns a 4-tuple `(repos, config, commit, autofix_settings)` to feed into `fix`.

- `repos`: the `--repos` values if given, else `find_repos(config)` (a callable you pass that takes the loaded config and returns repo paths).
- `msg` is the commit message; `branch_name` identifies the branch.

### `autofix_lib.fix(repos, *, apply_fix, check_fix=<noop>, config, commit, autofix_settings)`

Apply the fix to each repo (respecting `--limit`). For each repo:

1. Create a branch named **`all-repos_autofix_{branch_name}`** off the repo's default branch.
2. Call `apply_fix()` with the current working directory set to the repository root.
3. If nothing changed, skip the repo (no commit).
4. Otherwise call `check_fix()` (default: a no-op). If it raises, the repo is reported as errored and nothing is committed.
5. If interactive, prompt and skip the repo unless approved.
6. Commit **all** changes. The commit message is exactly:
   ```
   {msg}

   Committed via https://github.com/asottile/all-repos
   ```
   If `--author` was given, it is passed to `git commit`.
7. If `--dry-run`, stop here (do not push). Otherwise hand the branch to the configured push module.

Every git command run during a fix is echoed to stdout first, prefixed with `$ ` (the command is shell-quoted). `--dry-run` therefore prints the would-be diff. If processing a repo raises, print `***Errored` and continue with the rest.

The interactive prompt accepts `y` (yes), `n` (no), `s` (open a shell), `q` (quit), or `?` (help).

### Built-in autofixers

#### `all-repos-sed [autofix options] [-r] [--branch-name NAME] [--commit-msg MSG] EXPRESSION FILENAMES`

Run `sed -i EXPRESSION` over files across repos, like a distributed `git ls-files -z -- FILENAMES | xargs -0 sed -i EXPRESSION`.

- `EXPRESSION` is a sed program (e.g. `s/hi/hello/g`); `FILENAMES` is a glob passed to `git ls-files` selecting which files to edit.
- Only repos that have at least one matching file are processed, and only **text** files are edited (binary/symlink/other entries are skipped).
- `-r` / `--regexp-extended`: use extended regular expressions.
- `--branch-name` (default `all-repos-sed`) and `--commit-msg` (default: the equivalent `git ls-files ... | xargs ... sed ...` string) override the autofix branch/message.
- Changes are committed and pushed through the autofix framework.

#### `all-repos-manual [autofix options] --commit-msg MSG [--branch-name NAME]`

Apply a manual change interactively. It always runs in interactive mode, **requires** `--repos` and `--commit-msg`, and uses your `$SHELL` as the edit step (it opens `$SHELL` in each repo; whatever you change there is committed if you approve). Default branch name `all-repos-manual`.

## Push modules

A *push* deploys the autofix branch. A push module exposes a `Settings` type (constructed from `push_settings`) and `push(settings, branch_name)`, called with the working directory at the repository root. Implement these built-ins:

In every push module, the repository slug is taken from the `origin` remote URL — the portion **after the last `:`** (e.g. `git@github.com:owner/repo` → `owner/repo`). The "target" branch is the repository's default branch (the upstream the autofix branch was created from). The last commit's subject and body are its `git log -1` `%s` and `%b`.

- `all_repos.push.readonly`: `Settings` takes no arguments; `push` does nothing.
- `all_repos.push.merge_to_master`: `Settings` is constructed from `push_settings` (an empty `{}` is valid). `push` checks out the repo's default branch, pulls, merges the autofix branch as a **merge commit** (`--no-ff`), and pushes to `origin`.
- `all_repos.push.github_pull_request`: opens a GitHub pull request. `Settings` fields: `username` (required), `fork=False`, `base_url='https://api.github.com'`, `api_key=None`, `api_key_env=None`, `draft=False`.
  - Non-fork: push `HEAD:{branch_name}` to `origin`; then POST to `{base_url}/repos/{slug}/pulls` with JSON body `{"title": <subject>, "body": <body>, "base": <default branch>, "head": <branch_name>, "draft": <draft>}`; print the response's `html_url`.
  - Fork (`fork=True`): first POST `{base_url}/repos/{slug}/forks`; use the response's `full_name` as the fork slug, add a `fork` remote (the origin URL with the slug replaced by the fork slug), push `HEAD:{branch_name}` to that `fork` remote (not `origin`), and use `head = "{username}:{branch_name}"` in the `/pulls` POST.
- `all_repos.push.gitlab_pull_request`: opens a GitLab merge request. `Settings` fields: `base_url='https://gitlab.com/api/v4'`, `fork=False`, `api_key=None`, `api_key_env=None`. `push` strips a trailing `.git` from the slug and URL-escapes it, pushes `HEAD:{branch_name}` to `origin`, then POSTs to `{base_url}/projects/{escaped_slug}/merge_requests` with JSON body `{"source_branch": <branch_name>, "target_branch": <default branch>, "title": <subject>, "description": <body>, "remove_source_branch": true}`; print the response's `web_url`.

The same api_key / api_key_env resolution rule as the sources applies to the GitHub/GitLab pushes.

(Pull-request pushes for Bitbucket and Azure are **out of scope** here.)

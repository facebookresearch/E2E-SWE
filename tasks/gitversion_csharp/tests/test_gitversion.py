"""Behavioral tests for the `gitv` CLI, graded by running the compiled binary.

The candidate's `setup.sh` produces an executable at /app/dist/gitv. Each test builds a real git
repository fixture with the `git` CLI, runs the binary against it, and asserts on the JSON output (or
on error behaviour). Commit dates and identity are pinned so output is deterministic.

Tests are grouped by distinct behaviour: related simple cases share one function (with per-case
assert messages) so the suite counts behaviours, not near-duplicate micro-cases.
"""

import json
import os
import subprocess
from pathlib import Path

GITV = "/app/dist/gitv"

# Deterministic git identity + commit timestamps so version output is reproducible.
_DET_ENV = {
    **os.environ,
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00 +0000",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00 +0000",
    "GIT_AUTHOR_NAME": "WRG",
    "GIT_AUTHOR_EMAIL": "wrg@example.com",
    "GIT_COMMITTER_NAME": "WRG",
    "GIT_COMMITTER_EMAIL": "wrg@example.com",
}


class Repo:
    """A throwaway git repository fixture driven through the `git` CLI."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.path, env=_DET_ENV,
            check=True, capture_output=True, text=True,
        ).stdout

    def commit(self, message: str = "commit") -> None:
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def tag(self, name: str) -> None:
        self.git("tag", name)

    def new_branch(self, name: str) -> None:
        self.git("checkout", "-q", "-b", name)

    def checkout(self, ref: str) -> None:
        self.git("checkout", "-q", ref)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def write(self, relpath: str, content: str) -> str:
        p = self.path / relpath
        p.write_text(content)
        return str(p)

    def commit_at(self, date: str, message: str = "commit") -> None:
        env = {**_DET_ENV, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", message],
            cwd=self.path, env=env, check=True, capture_output=True, text=True,
        )


def make_repo(path: Path) -> Repo:
    """Initialise an empty repo on branch `main` with a fixed identity (creating `path` if needed)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    repo = Repo(path)
    repo.git("init", "-q", "-b", "main")
    repo.git("config", "user.email", "wrg@example.com")
    repo.git("config", "user.name", "WRG")
    return repo


def run_gv(target_path, *args) -> subprocess.CompletedProcess:
    """Run the gitv binary against `target_path`; return the completed process (no assert)."""
    return subprocess.run(
        [GITV, str(target_path), *args],
        capture_output=True, text=True, env=_DET_ENV,
    )


def get_json(repo: Repo, *args) -> dict:
    """Run the CLI (default JSON output) and parse the emitted object."""
    result = run_gv(repo.path, *args)
    assert result.returncode == 0, (
        f"gitv exited {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    out = result.stdout
    return json.loads(out[out.find("{"): out.rfind("}") + 1])


def full_semver(repo: Repo, *args) -> str:
    return get_json(repo, *args)["FullSemVer"]


def _repo_tag_plus_two(path) -> Repo:
    """main with tag v1.0.0 and two further commits (deployment mode applied via -overrideconfig)."""
    repo = make_repo(path)
    repo.commit()
    repo.tag("v1.0.0")
    repo.commit()
    repo.commit()
    return repo


# --------------------------------------------------------------------------------------------------
# Core version calculation — mainline baseline, tags, branch types
# --------------------------------------------------------------------------------------------------

def test_main_and_tag_basics(tmp_path):
    """Mainline baseline, tag + commits patch bump, and HEAD-exactly-on-tag verbatim."""
    r = make_repo(tmp_path / "no_tag")
    r.commit()
    assert full_semver(r) == "0.0.1-1", "main with no tags → 0.0.1 baseline"

    r = make_repo(tmp_path / "tagged")
    r.commit(); r.tag("v1.0.0"); r.commit(); r.commit()
    assert full_semver(r) == "1.0.1-2", "main, tag v1.0.0 + 2 commits → patch bump"

    r = make_repo(tmp_path / "on_tag")
    r.commit(); r.tag("v1.0.0")
    assert full_semver(r) == "1.0.0", "HEAD exactly on tag → emitted verbatim, no increment"


def test_branch_type_labels(tmp_path):
    """Each branch type maps to its configured pre-release label and increment strategy."""
    r = make_repo(tmp_path / "develop")
    r.commit(); r.new_branch("develop"); r.commit()
    assert full_semver(r) == "0.1.0-alpha.2", "develop → minor increment + alpha label"

    r = make_repo(tmp_path / "feature")
    r.commit(); r.tag("v1.0.0"); r.new_branch("feature/foo"); r.commit()
    assert full_semver(r) == "1.0.1-foo.1+1", "feature off main → branch-name label, inherits patch"

    r = make_repo(tmp_path / "release")
    r.commit(); r.tag("v1.1.0"); r.new_branch("release/2.0.0"); r.commit()
    assert full_semver(r) == "2.0.0-beta.1+1", "release → version from branch name, beta label"

    r = make_repo(tmp_path / "hotfix")
    r.commit(); r.tag("v1.2.0"); r.new_branch("hotfix/1.2.1"); r.commit()
    assert full_semver(r) == "1.2.1-beta.1+1", "hotfix → version from branch name, beta label"

    r = make_repo(tmp_path / "support")
    r.commit(); r.tag("v1.0.0"); r.new_branch("support/1.x"); r.commit()
    assert full_semver(r) == "1.0.1-1", "support → mainline patch, stable (empty) label"

    r = make_repo(tmp_path / "pr")
    r.commit(); r.tag("v1.0.0"); r.new_branch("pull/2"); r.commit()
    assert full_semver(r) == "1.0.1-PullRequest2.1", "pull-request → PR-number label"


def test_detached_head(tmp_path):
    """A detached HEAD still resolves the mainline version for that commit."""
    repo = make_repo(tmp_path)
    repo.commit()
    repo.tag("v1.0.0")
    repo.commit()
    repo.commit()
    repo.checkout(repo.head())
    assert full_semver(repo) == "1.0.1-2"


# --------------------------------------------------------------------------------------------------
# Increment control — commit-message directives
# --------------------------------------------------------------------------------------------------

def test_commit_message_directives(tmp_path):
    """`+semver:` directives raise the increment above the branch default; the highest wins."""
    r = make_repo(tmp_path / "minor")
    r.commit(); r.tag("v1.0.0"); r.commit("feature work +semver: minor")
    assert full_semver(r) == "1.1.0-1", "+semver: minor bumps minor"

    r = make_repo(tmp_path / "major")
    r.commit(); r.tag("v1.0.0"); r.commit("breaking change +semver: major")
    assert full_semver(r) == "2.0.0-1", "+semver: major bumps major, resets minor/patch"

    r = make_repo(tmp_path / "none")
    r.commit(); r.tag("v1.0.0"); r.commit("chore +semver: none")
    assert full_semver(r) == "1.0.1-1", "+semver: none → branch default (patch)"

    r = make_repo(tmp_path / "highest")
    r.commit(); r.tag("v1.0.0"); r.commit("a +semver: minor"); r.commit("b +semver: major")
    assert full_semver(r) == "2.0.0-2", "highest directive among commits wins"


def test_tag_over_lower_next_version(tmp_path):
    """The base is the highest source: a reachable version tag higher than `next-version` wins over it."""
    repo = make_repo(tmp_path)
    repo.commit()
    repo.tag("v2.0.0")
    repo.commit()
    assert full_semver(repo, "-overrideconfig", "next-version=1.0.0") == "2.0.1-1"


def test_version_source_selection(tmp_path):
    """`VersionSourceSha`/`CommitsSinceVersionSource` track the source *commit*, even when the base
    version comes from `next-version` (anchored to the last tag) or is the highest of several tags
    reachable through a merge."""
    # next-version supplies the base version, but the source commit stays the tag commit.
    r = make_repo(tmp_path / "nextver")
    r.commit()
    r.tag("v1.0.0")
    tag_sha = r.git("rev-parse", "v1.0.0^{commit}").strip()
    r.commit()
    r.commit()
    d = get_json(r, "-overrideconfig", "next-version=2.0.0")
    assert d["FullSemVer"] == "2.0.0-2"
    assert d["VersionSourceSemVer"] == "2.0.0"
    assert d["VersionSourceSha"] == tag_sha, "source commit is the tag, not HEAD"
    assert d["CommitsSinceVersionSource"] == 2

    # Two divergent tags merged: the highest reachable (on the merged-in branch) is the source.
    r = make_repo(tmp_path / "merge")
    r.commit("base")
    r.new_branch("br1")
    r.commit("b1")
    r.tag("v1.5.0")
    hi_sha = r.git("rev-parse", "v1.5.0^{commit}").strip()
    r.checkout("main")
    r.commit("m1")
    r.tag("v1.2.0")
    r.git("merge", "-q", "--no-ff", "br1", "-m", "Merge branch 'br1'")
    d = get_json(r)
    assert d["FullSemVer"] == "1.5.1-2"
    assert d["VersionSourceSemVer"] == "1.5.0"
    assert d["VersionSourceSha"] == hi_sha, "highest reachable tag is the source"
    assert d["CommitsSinceVersionSource"] == 2


# Conventional-Commits config: `<type>!:`→major, `feat:`→minor, `fix:`→patch.
_CC_CONFIG = (
    "major-version-bump-message: '^\\w+(\\(.*\\))?!:'\n"
    "minor-version-bump-message: '^(feat)(\\(.*\\))?:'\n"
    "patch-version-bump-message: '^(fix)(\\(.*\\))?:'\n"
)


def _cc_repo(path, messages, config=_CC_CONFIG):
    """main tagged v1.0.0 then `messages`, with a Conventional-Commits `-config` file written."""
    r = make_repo(path)
    r.commit()
    r.tag("v1.0.0")
    for m in messages:
        r.commit(m)
    return r, r.write("cc.yml", config)


def test_conventional_commits_via_config(tmp_path):
    """Redefining the `*-version-bump-message` regexes via `-config` maps Conventional-Commit prefixes to
    increments: `feat:`→minor, `fix:`→patch, a `!` breaking marker (with or without scope)→major, and a
    type matching none falls back to the branch default (patch)."""
    r, cfg = _cc_repo(tmp_path / "feat", ["feat: add a feature"])
    assert full_semver(r, "-config", cfg) == "1.1.0-1", "feat: → minor"
    r, cfg = _cc_repo(tmp_path / "fix", ["fix: a bug"])
    assert full_semver(r, "-config", cfg) == "1.0.1-1", "fix: → patch"
    r, cfg = _cc_repo(tmp_path / "breaking", ["feat!: breaking change"])
    assert full_semver(r, "-config", cfg) == "2.0.0-1", "feat!: → major"
    r, cfg = _cc_repo(tmp_path / "scoped", ["feat(api)!: drop v1"])
    assert full_semver(r, "-config", cfg) == "2.0.0-1", "scoped breaking feat(api)!: → major"
    r, cfg = _cc_repo(tmp_path / "nonmatch", ["docs: update readme"])
    assert full_semver(r, "-config", cfg) == "1.0.1-1", "non-matching type → branch default (patch)"


def test_conventional_commits_highest_bump_wins(tmp_path):
    """The highest matching bump wins across all commits since the source (major > minor > patch),
    even when the highest-bump commit is not at HEAD (all commit messages since the source are
    scanned, not just the tip)."""
    r, cfg = _cc_repo(tmp_path / "pm", ["feat: b", "fix: a"])
    assert full_semver(r, "-config", cfg) == "1.1.0-2", "non-HEAD minor beats HEAD patch"
    r, cfg = _cc_repo(tmp_path / "pmm", ["feat!: c", "feat: b", "fix: a"])
    assert full_semver(r, "-config", cfg) == "2.0.0-3", "non-HEAD major beats later minor and HEAD patch"


def test_conventional_commits_breaking_footer(tmp_path):
    """A `BREAKING CHANGE:` footer in the commit *body* triggers major — the bump-message regex is
    matched against the full commit message, not just the subject line."""
    footer_cfg = (
        "major-version-bump-message: 'BREAKING[ -]CHANGE:'\n"
        "minor-version-bump-message: '^(feat)(\\(.*\\))?:'\n"
        "patch-version-bump-message: '^(fix)(\\(.*\\))?:'\n"
    )
    r, cfg = _cc_repo(
        tmp_path / "footer",
        ["chore: cleanup\n\nBREAKING CHANGE: removed the old api"],
        config=footer_cfg,
    )
    assert full_semver(r, "-config", cfg) == "2.0.0-1", "BREAKING CHANGE body footer → major"


# --------------------------------------------------------------------------------------------------
# JSON output object — fields and types
# --------------------------------------------------------------------------------------------------

def test_json_output_fields_and_types(tmp_path):
    """The JSON output exposes the version variables with correct values and JSON types."""
    repo = make_repo(tmp_path)
    repo.commit()
    repo.tag("v1.2.0")
    repo.commit()
    repo.commit()
    repo.commit()
    data = get_json(repo)

    assert data["Major"] == 1 and data["Minor"] == 2 and data["Patch"] == 1
    assert data["MajorMinorPatch"] == "1.2.1"
    assert data["SemVer"] == "1.2.1-3"
    assert data["FullSemVer"] == "1.2.1-3"
    assert data["PreReleaseTag"] == "3"
    assert data["PreReleaseLabel"] == ""
    assert data["PreReleaseNumber"] == 3
    assert data["AssemblySemVer"] == "1.2.1.0"
    assert data["BranchName"] == "main"
    assert data["VersionSourceSemVer"] == "1.2.0"
    assert data["CommitsSinceVersionSource"] == 3
    assert data["WeightedPreReleaseNumber"] == 55003
    assert data["UncommittedChanges"] == 0
    assert data["CommitDate"] == "2020-01-01"
    # Sha is the real HEAD sha; ShortSha is its 7-char prefix.
    assert data["Sha"] == repo.head()
    assert data["ShortSha"] == repo.head()[:7]
    # Informational/build-metadata formatting embeds branch + full sha; under ContinuousDelivery
    # the commit count is in the pre-release, so BuildMetaData is null (no leading count).
    assert data["InformationalVersion"] == f"1.2.1-3+Branch.main.Sha.{repo.head()}"
    assert data["FullBuildMetaData"] == f"Branch.main.Sha.{repo.head()}"
    # Numeric fields are JSON numbers; composite fields are JSON strings.
    assert isinstance(data["Major"], int) and isinstance(data["PreReleaseNumber"], int)
    assert isinstance(data["MajorMinorPatch"], str) and isinstance(data["FullSemVer"], str)


def test_weighted_prerelease_number_on_tag(tmp_path):
    """`WeightedPreReleaseNumber` is `PreReleaseNumber` + the branch weight; when there is no pre-release
    number it is the applicable weight itself (not null). On a stable tagged HEAD that is the global
    `tag-pre-release-weight` (60000)."""
    r = make_repo(tmp_path / "main_tag")
    r.commit()
    r.tag("v1.2.3")
    d = get_json(r)
    assert d["FullSemVer"] == "1.2.3"
    assert d["PreReleaseNumber"] is None, "no pre-release number on a stable tagged HEAD"
    assert d["WeightedPreReleaseNumber"] == 60000, "global tag-pre-release-weight when no pre-release number"

    r = make_repo(tmp_path / "dev_tag")
    r.commit()
    r.new_branch("develop")
    r.tag("v1.2.3")
    d = get_json(r)
    assert d["FullSemVer"] == "1.3.0-alpha.0", "develop on a tag → minor bump, alpha.0"
    assert d["WeightedPreReleaseNumber"] == 0, "develop weight 0 + pre-release number 0"


# --------------------------------------------------------------------------------------------------
# Deployment modes and configuration surface
# --------------------------------------------------------------------------------------------------

def test_deployment_modes(tmp_path):
    """The three deployment modes format the pre-release / build metadata differently."""
    r = _repo_tag_plus_two(tmp_path / "cd")
    assert full_semver(r, "-overrideconfig", "mode=ContinuousDelivery") == "1.0.1-2", \
        "ContinuousDelivery → advancing pre-release number, no build metadata"

    r = _repo_tag_plus_two(tmp_path / "md")
    assert full_semver(r, "-overrideconfig", "mode=ManualDeployment") == "1.0.1-1+2", \
        "ManualDeployment → baseline pre-release .1 + commit count as build metadata"

    r = _repo_tag_plus_two(tmp_path / "cdeploy")
    cfg = r.write("gitv.yml", "mode: ContinuousDeployment\n")
    assert full_semver(r, "-config", cfg) == "1.0.1", \
        "ContinuousDeployment (via -config file) → stable, pre-release stripped"


def test_config_and_overrides(tmp_path):
    """`-config` and `-overrideconfig` apply values; overrideconfig wins over the config file."""
    r = make_repo(tmp_path / "prefix")
    r.commit(); r.tag("ver1.5.0"); r.commit()
    assert full_semver(r, "-overrideconfig", "tag-prefix=ver") == "1.5.1-1", \
        "-overrideconfig tag-prefix=ver recognises the ver-prefixed tag"
    assert full_semver(r) == "0.0.1-2", "default tag-prefix ignores the ver tag → baseline"

    r = make_repo(tmp_path / "nextver")
    r.commit(); r.commit()
    assert full_semver(r, "-overrideconfig", "next-version=3.0.0") == "3.0.0-2", \
        "-overrideconfig next-version sets the base version"

    r = make_repo(tmp_path / "cfgfile")
    r.commit(); r.tag("ver1.5.0"); r.commit()
    cfg = r.write("gitv.yml", "tag-prefix: ver\n")
    assert full_semver(r, "-config", cfg) == "1.5.1-1", "-config file tag-prefix is applied"

    r = _repo_tag_plus_two(tmp_path / "precedence")
    cfg = r.write("gitv.yml", "mode: ManualDeployment\n")
    assert full_semver(r, "-config", cfg, "-overrideconfig", "mode=ContinuousDeployment") == "1.0.1", \
        "-overrideconfig takes precedence over the same value in the -config file"


def test_ignore_config(tmp_path):
    """`ignore.sha` drops specific commits; `ignore.commits-before` drops by date (incl. the tag)."""
    r = make_repo(tmp_path / "sha")
    r.commit(); r.tag("v1.0.0"); r.commit()
    ignored = r.head()  # the intermediate commit to ignore
    r.commit()
    cfg = r.write("gitv.yml", f"ignore:\n  sha:\n    - {ignored}\n")
    assert full_semver(r, "-config", cfg) == "1.0.1-1", "ignore.sha excludes a commit (count drops)"

    r = make_repo(tmp_path / "before")
    r.commit_at("2020-01-01T00:00:00 +0000", "c1")
    r.tag("v1.0.0")
    r.commit_at("2020-06-01T00:00:00 +0000", "c2")
    r.commit_at("2020-12-01T00:00:00 +0000", "c3")
    cfg = r.write("gitv.yml", "ignore:\n  commits-before: 2020-09-01T00:00:00\n")
    assert full_semver(r, "-config", cfg) == "0.0.1-1", \
        "ignore.commits-before drops the tagged commit too → 0.0.0 fallback"


# --------------------------------------------------------------------------------------------------
# Tag semantics
# --------------------------------------------------------------------------------------------------

def test_prerelease_base_tag(tmp_path):
    """A commit past a pre-release tag (v1.0.0-beta.1) stays on 1.0.0 with an advancing number."""
    repo = make_repo(tmp_path)
    repo.commit()
    repo.tag("v1.0.0-beta.1")
    repo.commit()
    assert full_semver(repo) == "1.0.0-2"


def test_tag_selection(tmp_path):
    """Non-version tags are ignored; with several version tags, the highest reachable wins."""
    r = make_repo(tmp_path / "nonsemver")
    r.commit(); r.tag("not-a-version"); r.commit()
    assert full_semver(r) == "0.0.1-2", "non-version tag ignored → baseline"

    r = make_repo(tmp_path / "competing")
    r.commit(); r.tag("v1.0.0"); r.commit(); r.tag("v2.0.0"); r.commit()
    assert full_semver(r) == "2.0.1-1", "highest reachable version tag is chosen"


# --------------------------------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------------------------------

def test_error_handling(tmp_path):
    """Clear non-zero errors for a non-git directory and for a repository with no commits."""
    plain = tmp_path / "plain"
    plain.mkdir()
    result = run_gv(plain)
    assert result.returncode != 0 and "Cannot find the .git directory" in (result.stdout + result.stderr), \
        f"non-git directory should fail clearly; got rc={result.returncode}\n{result.stdout}\n{result.stderr}"

    repo = make_repo(tmp_path / "empty")
    result = run_gv(repo.path)
    assert result.returncode != 0 and "No commits found on the current branch." in (result.stdout + result.stderr), \
        f"empty repo should fail clearly; got rc={result.returncode}\n{result.stdout}\n{result.stderr}"


# --------------------------------------------------------------------------------------------------
# Merges (commit-graph reasoning)
# --------------------------------------------------------------------------------------------------

def test_feature_and_release_merges(tmp_path):
    """Merging a branch counts its commits (incl. the merge commit) toward the target's version."""
    r = make_repo(tmp_path / "feat_main")
    r.commit(); r.tag("v1.0.0")
    r.new_branch("feature/foo"); r.commit(); r.commit()
    r.checkout("main")
    r.git("merge", "-q", "--no-ff", "feature/foo", "-m", "Merge branch 'feature/foo'")
    assert full_semver(r) == "1.0.1-3", "feature → main counts feature commits + merge"

    r = make_repo(tmp_path / "feat_dev")
    r.commit()
    r.new_branch("develop"); r.commit()
    r.new_branch("feature/bar"); r.commit()
    r.checkout("develop")
    r.git("merge", "-q", "--no-ff", "feature/bar", "-m", "Merge branch 'feature/bar'")
    assert full_semver(r) == "0.1.0-alpha.4", "feature → develop keeps minor/alpha, counts all commits"


def test_release_branch_merged_to_main(tmp_path):
    """Merging a release/2.0.0 branch into main adopts 2.0.0 as the base version (from the merge)."""
    repo = make_repo(tmp_path)
    repo.commit()
    repo.tag("v1.0.0")
    repo.new_branch("release/2.0.0")
    repo.commit()
    repo.checkout("main")
    repo.git("merge", "-q", "--no-ff", "release/2.0.0", "-m", "Merge branch 'release/2.0.0'")
    assert full_semver(repo) == "2.0.0-2"


# --------------------------------------------------------------------------------------------------
# Increment inheritance across branch sources
# --------------------------------------------------------------------------------------------------

def test_feature_inherits_minor_from_develop(tmp_path):
    """A feature branch created off develop inherits develop's Minor increment (not main's Patch)."""
    repo = make_repo(tmp_path)
    repo.commit()
    repo.new_branch("develop")
    repo.commit()
    repo.new_branch("feature/baz")
    repo.commit()
    assert full_semver(repo) == "0.1.0-baz.1+3"


def test_feature_branch_from_release_adopts_release_version(tmp_path):
    """A feature branch cut from a release branch adopts the release's version verbatim, with no
    increment applied — its own label replaces `beta`, but the number stays at the release's base
    (2.0.0), NOT main's Patch bump (1.0.1) nor a Minor bump (2.1.0)."""
    repo = make_repo(tmp_path)
    repo.commit()
    repo.tag("v1.0.0")
    repo.new_branch("release/2.0.0")
    repo.new_branch("feature/foo")
    repo.commit()
    data = get_json(repo)
    assert data["FullSemVer"] == "2.0.0-foo.1+1"
    # BranchName keeps the raw name; EscapedBranchName replaces `/` (invalid in env-var names) with `-`.
    assert data["BranchName"] == "feature/foo"
    assert data["EscapedBranchName"] == "feature-foo"


# --------------------------------------------------------------------------------------------------
# Trunk-based workflow (Mainline)
# --------------------------------------------------------------------------------------------------

def test_trunk_based_workflow(tmp_path):
    """The TrunkBased workflow increments patch per commit on main as a stable release (no tag → 0.0.N)."""
    repo = make_repo(tmp_path)
    repo.commit()
    repo.commit()
    repo.commit()
    assert full_semver(repo, "-overrideconfig", "workflow=TrunkBased/preview1") == "0.0.3"

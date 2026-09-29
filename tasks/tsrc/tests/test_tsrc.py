"""
End-to-end integration tests for tsrc CLI tool.

These tests create real git repositories on disk and exercise tsrc commands
via subprocess to verify user-facing behavior.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd, *, cwd=None, check=True, env=None):
    """Run a command and return CompletedProcess."""
    run_env = os.environ.copy()
    run_env["TSRC_TESTING"] = "1"  # allows file:// protocol in git clone
    # Ensure git operations work without global git config (e.g., in containers)
    run_env.setdefault("GIT_AUTHOR_NAME", "Test")
    run_env.setdefault("GIT_AUTHOR_EMAIL", "test@test.com")
    run_env.setdefault("GIT_COMMITTER_NAME", "Test")
    run_env.setdefault("GIT_COMMITTER_EMAIL", "test@test.com")
    if env:
        run_env.update(env)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=run_env,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result


def _git(repo_path, *args, **kwargs):
    """Run a git command in repo_path."""
    return _run(["git"] + list(args), cwd=repo_path, **kwargs)


def _tsrc(args, *, cwd=None, check=True, env=None):
    """Run the tsrc CLI."""
    return _run(["tsrc"] + list(args), cwd=cwd, check=check, env=env)


def _create_git_repo(path, files=None, branch="master"):
    """Create a bare-bones git repository with optional files."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "--initial-branch", branch)
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    if files:
        for name, content in files.items():
            filepath = path / name
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            _git(path, "add", name)
    else:
        (path / "README.md").write_text("# Repo\n")
        _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial commit")


def _create_manifest_repo(path, manifest_content, branch="master"):
    """Create a git repo containing manifest.yml."""
    _create_git_repo(path, files={"manifest.yml": manifest_content}, branch=branch)


def _make_manifest_yaml(*repos, groups=None, switch=None):
    """Build a manifest YAML string from repo specs."""
    import ruamel.yaml

    data = {"repos": []}
    for r in repos:
        data["repos"].append(r)
    if groups:
        data["groups"] = groups
    if switch:
        data["switch"] = switch
    yaml = ruamel.yaml.YAML()
    import io

    stream = io.StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """Provide a clean workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def git_server(tmp_path):
    """Provide a directory to host bare-like git repos as remotes."""
    server = tmp_path / "git_server"
    server.mkdir()
    return server


def _setup_remote_repo(git_server, name, files=None, branch="master"):
    """Create a repo under git_server that can be cloned via file:// protocol."""
    repo_path = git_server / name
    _create_git_repo(repo_path, files=files, branch=branch)
    return f"file://{repo_path}"


def _add_submodule_to_remote(git_server, parent_name, submodule_url, sub_path):
    """Embed an existing remote repo as a git submodule of parent_name.

    file:// submodule operations are blocked by git's default
    protocol.file.allow=user (CVE-2022-39253), so we pass -c
    protocol.file.allow=always for the add/commit -- mirroring what tsrc itself
    injects under TSRC_TESTING for its own clone/sync.
    """
    parent_path = git_server / parent_name
    _git(
        parent_path,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        submodule_url,
        sub_path,
    )
    _git(parent_path, "commit", "-m", f"add submodule {sub_path}")


def _setup_workspace(
    git_server,
    workspace,
    repos,
    groups=None,
    branch="master",
    shallow=False,
    extra_init_args=None,
    switch=None,
):
    """
    Full setup: create remote repos, manifest repo, and run tsrc init.
    repos: list of dicts with 'dest' and optionally 'files', 'repo_branch'.
    Returns the manifest repo URL.
    """
    manifest_repos = []
    for r in repos:
        repo_name = r["dest"]
        repo_branch = r.get("repo_branch", "master")
        url = _setup_remote_repo(
            git_server, repo_name, files=r.get("files"), branch=repo_branch
        )
        entry = {"dest": repo_name, "url": url}
        if r.get("branch"):
            entry["branch"] = r["branch"]
        if r.get("tag"):
            entry["tag"] = r["tag"]
        if r.get("sha1"):
            entry["sha1"] = r["sha1"]
        if r.get("copy"):
            entry["copy"] = r["copy"]
        if r.get("symlink"):
            entry["symlink"] = r["symlink"]
        if r.get("ignore_submodules") is not None:
            entry["ignore_submodules"] = r["ignore_submodules"]
        if r.get("remotes"):
            del entry["url"]
            entry["remotes"] = r["remotes"]
        manifest_repos.append(entry)

    manifest_content = _make_manifest_yaml(
        *manifest_repos, groups=groups, switch=switch
    )
    manifest_path = git_server / "manifest"
    _create_manifest_repo(manifest_path, manifest_content, branch=branch)
    manifest_url = f"file://{manifest_path}"

    init_args = ["init", manifest_url]
    if branch != "master":
        init_args += ["--branch", branch]
    if shallow:
        init_args.append("--shallow")
    if extra_init_args:
        init_args += extra_init_args
    _tsrc(init_args, cwd=workspace)
    return manifest_url


# ===========================================================================
# Tests
# ===========================================================================


class TestInit:
    """Tests for tsrc init command."""

    def test_init_clones_repos_and_creates_config(self, workspace, git_server):
        """tsrc init clones repos, creates config with manifest_url, and
        defaults unspecified branch to 'master'. Also verifies workspace
        structure (.tsrc/config.yml, .tsrc/manifest/manifest.yml)."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "repo_a", "files": {"a.txt": "hello"}},
                {"dest": "repo_b", "files": {"b.txt": "world"}},
            ],
        )
        assert (workspace / "repo_a" / "a.txt").read_text() == "hello"
        assert (workspace / "repo_b" / "b.txt").read_text() == "world"

        # Verify workspace structure
        assert (workspace / ".tsrc" / "config.yml").exists()
        assert (workspace / ".tsrc" / "manifest" / "manifest.yml").exists()

        # Config records manifest_url
        config_text = (workspace / ".tsrc" / "config.yml").read_text()
        assert "manifest_url" in config_text

        # Default branch is master when not specified
        branch = _git(
            workspace / "repo_a", "rev-parse", "--abbrev-ref", "HEAD"
        ).stdout.strip()
        assert branch == "master"

    def test_init_with_groups(self, workspace, git_server):
        """tsrc init with -g only clones repos in the specified group."""
        url_a = _setup_remote_repo(git_server, "alpha", files={"alpha.txt": "a"})
        url_b = _setup_remote_repo(git_server, "beta", files={"beta.txt": "b"})
        manifest_content = _make_manifest_yaml(
            {"dest": "alpha", "url": url_a},
            {"dest": "beta", "url": url_b},
            groups={"front": {"repos": ["alpha"]}, "back": {"repos": ["beta"]}},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        manifest_url = f"file://{manifest_path}"

        _tsrc(["init", manifest_url, "-g", "front"], cwd=workspace)
        assert (workspace / "alpha").is_dir()
        assert not (workspace / "beta").exists()

    def test_init_refuses_double_init(self, workspace, git_server):
        """tsrc init errors if workspace is already initialized."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "repo_x"},
            ],
        )
        result = _tsrc(["init", "file:///dummy"], cwd=workspace, check=False)
        assert result.returncode != 0

    def test_init_with_branch(self, workspace, git_server):
        """tsrc init with --branch uses that manifest branch."""
        url = _setup_remote_repo(git_server, "repo1")
        manifest_content = _make_manifest_yaml({"dest": "repo1", "url": url})
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content, branch="develop")
        manifest_url = f"file://{manifest_path}"

        _tsrc(["init", manifest_url, "--branch", "develop"], cwd=workspace)
        assert (workspace / "repo1").is_dir()
        # Verify config records the branch
        config_text = (workspace / ".tsrc" / "config.yml").read_text()
        assert "develop" in config_text


class TestSync:
    """Tests for tsrc sync command."""

    def test_sync_updates_repos(self, workspace, git_server):
        """tsrc sync pulls new commits into cloned repos."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "myrepo", "files": {"initial.txt": "v1"}},
            ],
        )
        # Add a new commit to the remote
        remote_path = git_server / "myrepo"
        (remote_path / "update.txt").write_text("v2")
        _git(remote_path, "add", "update.txt")
        _git(remote_path, "commit", "-m", "add update")

        _tsrc(["sync"], cwd=workspace)
        assert (workspace / "myrepo" / "update.txt").read_text() == "v2"

    def test_sync_reports_dirty_repos(self, workspace, git_server):
        """tsrc sync does not destroy uncommitted changes and reports errors
        when a repo has a sha1 pin and is dirty."""
        url = _setup_remote_repo(git_server, "pinned", files={"f.txt": "orig"})
        remote_path = git_server / "pinned"
        sha1 = _git(remote_path, "rev-parse", "HEAD").stdout.strip()

        manifest_content = _make_manifest_yaml(
            {"dest": "pinned", "url": url, "sha1": sha1},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Dirty the repo
        (workspace / "pinned" / "dirty.txt").write_text("dirty")
        _git(workspace / "pinned", "add", "dirty.txt")

        result = _tsrc(["sync"], cwd=workspace, check=False)
        assert result.returncode != 0

    def test_sync_clones_new_repos(self, workspace, git_server):
        """tsrc sync clones repos that were added to the manifest after init."""
        url_a = _setup_remote_repo(git_server, "original")
        manifest_content = _make_manifest_yaml(
            {"dest": "original", "url": url_a},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Add a new repo to the manifest
        url_b = _setup_remote_repo(git_server, "newrepo", files={"new.txt": "fresh"})
        updated_manifest = _make_manifest_yaml(
            {"dest": "original", "url": url_a},
            {"dest": "newrepo", "url": url_b},
        )
        (manifest_path / "manifest.yml").write_text(updated_manifest)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "add newrepo")

        _tsrc(["sync"], cwd=workspace)
        assert (workspace / "newrepo" / "new.txt").read_text() == "fresh"

    def test_sync_no_update_manifest(self, workspace, git_server):
        """tsrc sync --no-update-manifest skips manifest pull."""
        url_a = _setup_remote_repo(git_server, "repo_noupdate")
        manifest_content = _make_manifest_yaml(
            {"dest": "repo_noupdate", "url": url_a},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Add a new repo to remote manifest
        url_b = _setup_remote_repo(git_server, "invisible")
        updated = _make_manifest_yaml(
            {"dest": "repo_noupdate", "url": url_a},
            {"dest": "invisible", "url": url_b},
        )
        (manifest_path / "manifest.yml").write_text(updated)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "add invisible")

        _tsrc(["sync", "--no-update-manifest"], cwd=workspace)
        # invisible should not be cloned since manifest was not updated
        assert not (workspace / "invisible").exists()


class TestForeach:
    """Tests for tsrc foreach command."""

    def test_foreach_with_group_filter(self, workspace, git_server):
        """tsrc foreach -g runs command only in repos of the specified group."""
        url_a = _setup_remote_repo(git_server, "in_group")
        url_b = _setup_remote_repo(git_server, "out_group")
        manifest_content = _make_manifest_yaml(
            {"dest": "in_group", "url": url_a},
            {"dest": "out_group", "url": url_b},
            groups={"mygroup": {"repos": ["in_group"]}},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}", "--clone-all-repos"], cwd=workspace)

        # Create a marker file in each repo
        (workspace / "in_group" / "marker.txt").write_text("yes")
        (workspace / "out_group" / "marker.txt").write_text("yes")

        result = _tsrc(
            ["foreach", "-g", "mygroup", "-c", "cat marker.txt"],
            cwd=workspace,
        )
        output_lines = result.stdout + result.stderr
        # in_group should appear in the output, out_group should not be processed
        assert "in_group" in output_lines
        assert "out_group" not in output_lines

    def test_foreach_shell_mode_and_direct_mode(self, workspace, git_server):
        """tsrc foreach -c runs through shell, foreach -- runs directly.
        Both modes should produce correct output in sequential mode.
        Also verifies foreach runs in each repo (multiple repos)."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "shell_r1", "files": {"data.txt": "content123"}},
                {"dest": "shell_r2", "files": {"data.txt": "other456"}},
            ],
        )
        # Shell mode: verify shell features work (shell expansion of $PWD)
        result = _tsrc(
            ["foreach", "-c", "echo $PWD && cat data.txt"],
            cwd=workspace,
            env={"TSRC_PARALLEL_JOBS": "1"},
        )
        assert "content123" in result.stdout
        assert "other456" in result.stdout
        # Verify both repos are visited
        assert "shell_r1" in result.stdout
        assert "shell_r2" in result.stdout

        # Direct mode: verify git log works
        result2 = _tsrc(
            ["foreach", "--", "git", "log", "--oneline", "-1"],
            cwd=workspace,
            env={"TSRC_PARALLEL_JOBS": "1"},
        )
        assert "initial commit" in result2.stdout

    def test_foreach_failure_propagation_and_success(self, workspace, git_server):
        """tsrc foreach exits non-zero when any command fails, and exits 0
        when all succeed. Also verifies failure is reported."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "ok_repo", "files": {"exists.txt": "ok"}},
                {"dest": "fail_repo"},
            ],
        )
        # Mixed: one succeeds, one fails -> nonzero exit
        result = _tsrc(
            ["foreach", "-c", "cat exists.txt"],
            cwd=workspace,
            check=False,
        )
        assert result.returncode != 0

        # All succeed -> zero exit
        result2 = _tsrc(
            ["foreach", "-c", "true"],
            cwd=workspace,
            check=False,
        )
        assert result2.returncode == 0


class TestStatus:
    """Tests for tsrc status command."""

    def test_status_shows_dirty_state(self, workspace, git_server):
        """tsrc status indicates dirty repos and lists repo names."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "dirty_repo"},
            ],
        )
        # First check clean status shows the repo without a dirty marker
        result = _tsrc(["status"], cwd=workspace)
        combined = result.stdout + result.stderr
        assert "dirty_repo" in combined
        assert "(dirty)" not in combined

        # Now dirty it (untracked file) and check the dirty marker appears
        (workspace / "dirty_repo" / "untracked.txt").write_text("junk")
        result2 = _tsrc(["status"], cwd=workspace)
        combined2 = result2.stdout + result2.stderr
        assert "dirty_repo" in combined2
        assert "(dirty)" in combined2


class TestLog:
    """Tests for tsrc log command."""

    def test_log_shows_changes_and_no_changes(self, workspace, git_server):
        """tsrc log --from shows the commits between two refs, and shows nothing
        when from == to. `--from` must resolve in every selected repo, so a
        shared ref is tagged on each."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "log_repo"},
                {"dest": "unchanged_repo"},
            ],
        )

        # Same from/to -> no changes, should succeed
        result_no = _tsrc(["log", "--from", "HEAD", "--to", "HEAD"], cwd=workspace)
        assert result_no.returncode == 0

        # Tag a shared ref on both repos so `--from base` resolves everywhere.
        for dest in ("log_repo", "unchanged_repo"):
            _git(workspace / dest, "tag", "base")

        # Add a commit only to log_repo.
        repo_path = workspace / "log_repo"
        (repo_path / "change1.txt").write_text("c1")
        _git(repo_path, "add", "change1.txt")
        _git(repo_path, "commit", "-m", "change one")

        result = _tsrc(["log", "--from", "base"], cwd=workspace)
        combined = result.stdout + result.stderr
        assert "change one" in combined


class TestApplyManifest:
    """Tests for tsrc apply-manifest command."""

    def test_apply_manifest_clones_repos_and_copies(self, workspace, git_server):
        """tsrc apply-manifest clones repos from a local manifest file
        AND performs filesystem operations like copies."""
        # Initialize with one repo
        url_a = _setup_remote_repo(git_server, "existing")
        manifest_content = _make_manifest_yaml(
            {"dest": "existing", "url": url_a},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Create a local manifest with an additional repo + copy directive
        url_b = _setup_remote_repo(
            git_server,
            "added_by_apply",
            files={"apply.txt": "applied", "app.conf": "listen_port=8080"},
        )
        local_manifest = _make_manifest_yaml(
            {"dest": "existing", "url": url_a},
            {
                "dest": "added_by_apply",
                "url": url_b,
                "copy": [{"file": "app.conf", "dest": "runtime.conf"}],
            },
        )
        local_manifest_file = workspace / "local_manifest.yml"
        local_manifest_file.write_text(local_manifest)

        _tsrc(["apply-manifest", str(local_manifest_file)], cwd=workspace)
        assert (workspace / "added_by_apply" / "apply.txt").read_text() == "applied"
        # Verify copy operation was performed
        assert (workspace / "runtime.conf").read_text() == "listen_port=8080"


class TestManifestParsing:
    """Tests for manifest format handling."""

    def test_manifest_with_multiple_remotes(self, workspace, git_server):
        """Repos can be configured with multiple named remotes."""
        repo_path = git_server / "multi_remote"
        _create_git_repo(repo_path, files={"mr.txt": "multi"})
        url = f"file://{repo_path}"

        manifest_content = _make_manifest_yaml(
            {
                "dest": "multi_remote",
                "remotes": [
                    {"name": "origin", "url": url},
                    {"name": "upstream", "url": url},
                ],
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Verify both remotes are configured
        result = _git(workspace / "multi_remote", "remote", "-v")
        assert "origin" in result.stdout
        assert "upstream" in result.stdout

    def test_manifest_with_copy_and_default_dest(self, workspace, git_server):
        """Manifest copy directives copy files. When 'dest' is omitted,
        the file is copied to the workspace root with the source filename."""
        url = _setup_remote_repo(
            git_server,
            "copy_source",
            files={
                "config.ini": "key=value",
                "settings.cfg": "db_host=localhost\ndb_port=5432",
            },
        )
        manifest_content = _make_manifest_yaml(
            {
                "dest": "copy_source",
                "url": url,
                "copy": [
                    {"file": "config.ini", "dest": "copied_config.ini"},
                    {"file": "settings.cfg"},  # no 'dest' key -- defaults to filename
                ],
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        assert (workspace / "copied_config.ini").read_text() == "key=value"
        # Default dest = source filename
        copied = workspace / "settings.cfg"
        assert copied.exists(), "Copy with default dest should copy to workspace root"
        assert "db_host=localhost" in copied.read_text()

    def test_manifest_with_symlink_operation(self, workspace, git_server):
        """Manifest symlink directives create symlinks in the workspace."""
        url = _setup_remote_repo(
            git_server, "link_source", files={"link_target.txt": "linked"}
        )
        target_path = str(workspace / "link_source" / "link_target.txt")
        manifest_content = _make_manifest_yaml(
            {
                "dest": "link_source",
                "url": url,
                "symlink": [{"source": "my_link.txt", "target": target_path}],
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        link_path = workspace / "my_link.txt"
        # Must be a real symlink (not a plain copy) that resolves to the
        # manifest's target file, whose content is "linked".
        assert link_path.is_symlink()
        assert link_path.read_text() == "linked"

    def test_manifest_repo_with_branch(self, workspace, git_server):
        """Repos can specify a branch to clone."""
        repo_path = git_server / "branched"
        _create_git_repo(repo_path, files={"main.txt": "on main"}, branch="main")
        # Create develop branch
        _git(repo_path, "checkout", "-b", "develop")
        (repo_path / "dev.txt").write_text("on develop")
        _git(repo_path, "add", "dev.txt")
        _git(repo_path, "commit", "-m", "dev commit")
        _git(repo_path, "checkout", "main")  # go back to main
        url = f"file://{repo_path}"

        manifest_content = _make_manifest_yaml(
            {"dest": "branched", "url": url, "branch": "develop"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        assert (workspace / "branched" / "dev.txt").exists()
        branch = _git(
            workspace / "branched", "rev-parse", "--abbrev-ref", "HEAD"
        ).stdout.strip()
        assert branch == "develop"

    def test_manifest_repo_with_tag(self, workspace, git_server):
        """Repos can specify a tag to checkout."""
        repo_path = git_server / "tagged"
        _create_git_repo(repo_path, files={"v1.txt": "version1"})
        _git(repo_path, "tag", "v1.0")
        # Add more commits past the tag
        (repo_path / "v2.txt").write_text("version2")
        _git(repo_path, "add", "v2.txt")
        _git(repo_path, "commit", "-m", "v2")
        url = f"file://{repo_path}"

        manifest_content = _make_manifest_yaml(
            {"dest": "tagged", "url": url, "tag": "v1.0"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        assert (workspace / "tagged" / "v1.txt").exists()
        # v2.txt should NOT exist since we checked out at v1.0
        assert not (workspace / "tagged" / "v2.txt").exists()

    def test_manifest_repo_with_sha1(self, workspace, git_server):
        """Repos can pin to a specific sha1."""
        repo_path = git_server / "pinned_sha"
        _create_git_repo(repo_path, files={"first.txt": "first"})
        pinned_sha = _git(repo_path, "rev-parse", "HEAD").stdout.strip()
        # Add another commit
        (repo_path / "second.txt").write_text("second")
        _git(repo_path, "add", "second.txt")
        _git(repo_path, "commit", "-m", "second")
        url = f"file://{repo_path}"

        manifest_content = _make_manifest_yaml(
            {"dest": "pinned_sha", "url": url, "sha1": pinned_sha},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        assert (workspace / "pinned_sha" / "first.txt").exists()
        assert not (workspace / "pinned_sha" / "second.txt").exists()

    def test_invalid_manifest_url_and_remotes(self, workspace, git_server, tmp_path):
        """A repo with both url and remotes is rejected by manifest validation."""
        repo_path = git_server / "bad_repo"
        _create_git_repo(repo_path)
        url = f"file://{repo_path}"

        # Write a raw manifest that has both url and remotes (invalid)
        manifest_text = textwrap.dedent(
            f"""\
            repos:
              - dest: bad_repo
                url: "{url}"
                remotes:
                  - name: origin
                    url: "{url}"
        """
        )
        manifest_dir = git_server / "bad_manifest"
        _create_manifest_repo(manifest_dir, manifest_text)
        result = _tsrc(["init", f"file://{manifest_dir}"], cwd=workspace, check=False)
        assert result.returncode != 0


class TestGroups:
    """Tests for group-based repo selection."""

    def test_groups_with_includes(self, workspace, git_server):
        """Groups can include other groups."""
        url_a = _setup_remote_repo(git_server, "base_repo")
        url_b = _setup_remote_repo(git_server, "ext_repo")
        manifest_content = _make_manifest_yaml(
            {"dest": "base_repo", "url": url_a},
            {"dest": "ext_repo", "url": url_b},
            groups={
                "base": {"repos": ["base_repo"]},
                "extended": {"repos": ["ext_repo"], "includes": ["base"]},
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}", "-g", "extended"], cwd=workspace)

        assert (workspace / "base_repo").is_dir()
        assert (workspace / "ext_repo").is_dir()

    def test_default_group(self, workspace, git_server):
        """When a 'default' group exists, it is used when no -g flag is given."""
        url_a = _setup_remote_repo(git_server, "default_repo")
        url_b = _setup_remote_repo(git_server, "other_repo")
        manifest_content = _make_manifest_yaml(
            {"dest": "default_repo", "url": url_a},
            {"dest": "other_repo", "url": url_b},
            groups={
                "default": {"repos": ["default_repo"]},
                "extra": {"repos": ["other_repo"]},
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        assert (workspace / "default_repo").is_dir()
        assert not (workspace / "other_repo").exists()

    def test_clone_all_repos(self, workspace, git_server):
        """--clone-all-repos ignores groups and clones everything."""
        url_a = _setup_remote_repo(git_server, "repo_all_1")
        url_b = _setup_remote_repo(git_server, "repo_all_2")
        manifest_content = _make_manifest_yaml(
            {"dest": "repo_all_1", "url": url_a},
            {"dest": "repo_all_2", "url": url_b},
            groups={"partial": {"repos": ["repo_all_1"]}},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}", "--clone-all-repos"], cwd=workspace)

        assert (workspace / "repo_all_1").is_dir()
        assert (workspace / "repo_all_2").is_dir()

    def test_nonexistent_group_errors(self, workspace, git_server):
        """Requesting a non-existent group raises an error."""
        url = _setup_remote_repo(git_server, "any_repo")
        manifest_content = _make_manifest_yaml(
            {"dest": "any_repo", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}", "--clone-all-repos"], cwd=workspace)

        result = _tsrc(
            ["foreach", "-g", "nonexistent", "-c", "true"],
            cwd=workspace,
            check=False,
        )
        assert result.returncode != 0


class TestRepoFiltering:
    """Tests for include/exclude regex filtering."""

    def test_include_regex(self, workspace, git_server):
        """foreach -i only processes matching repos."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "frontend-app"},
                {"dest": "backend-api"},
            ],
        )
        result = _tsrc(
            ["foreach", "-i", "front", "-c", "pwd"],
            cwd=workspace,
        )
        assert "frontend-app" in result.stdout
        assert "backend-api" not in result.stdout

    def test_exclude_regex(self, workspace, git_server):
        """foreach -e excludes matching repos."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "keep-this"},
                {"dest": "skip-this"},
            ],
        )
        result = _tsrc(
            ["foreach", "-e", "skip", "-c", "pwd"],
            cwd=workspace,
        )
        assert "keep-this" in result.stdout
        assert "skip-this" not in result.stdout


class TestWorkspaceConfig:
    """Tests for workspace configuration persistence."""

    def test_workspace_path_option(self, workspace, git_server, tmp_path):
        """tsrc -w allows specifying a different workspace path."""
        url = _setup_remote_repo(git_server, "remote_ws")
        manifest_content = _make_manifest_yaml(
            {"dest": "remote_ws", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        manifest_url = f"file://{manifest_path}"

        other_ws = tmp_path / "other_workspace"
        other_ws.mkdir()
        _tsrc(["init", manifest_url, "-w", str(other_ws)], cwd=tmp_path)
        assert (other_ws / "remote_ws").is_dir()


class TestErrorHandling:
    """Tests for error scenarios."""

    def test_sync_with_unreachable_remote(self, workspace, git_server, tmp_path):
        """tsrc sync handles repos whose remote is unreachable."""
        url = _setup_remote_repo(git_server, "will_vanish")
        manifest_content = _make_manifest_yaml(
            {"dest": "will_vanish", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Delete the remote repo
        import shutil

        shutil.rmtree(git_server / "will_vanish")

        result = _tsrc(["sync", "--no-update-manifest"], cwd=workspace, check=False)
        assert result.returncode != 0

    def test_foreach_missing_repo(self, workspace, git_server):
        """tsrc foreach errors when a repo directory is missing from disk."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "present_repo"},
                {"dest": "missing_repo"},
            ],
        )
        import shutil

        shutil.rmtree(workspace / "missing_repo")

        result = _tsrc(["foreach", "-c", "true"], cwd=workspace, check=False)
        assert result.returncode != 0

    def test_no_workspace_and_no_subcommand(self, tmp_path):
        """Running tsrc commands outside a workspace produces a clear error.
        Running tsrc with no subcommand exits non-zero.
        tsrc --version prints version info."""
        # No workspace
        empty = tmp_path / "empty"
        empty.mkdir()
        result = _tsrc(["sync"], cwd=empty, check=False)
        assert result.returncode != 0

        # No subcommand
        result2 = _tsrc([], check=False)
        assert result2.returncode != 0

        # Version flag prints "tsrc <version>" -- assert the program name appears
        # (a stub printing arbitrary text must not pass).
        result3 = _tsrc(["--version"])
        assert "tsrc" in result3.stdout.lower()

    def test_foreach_arg_validation(self, workspace, git_server):
        """tsrc foreach with no command produces an error.
        tsrc foreach -c with multiple arguments errors (requires exactly one)."""
        _setup_workspace(
            git_server,
            workspace,
            [{"dest": "argval_repo"}],
        )
        # No command at all
        result = _tsrc(["foreach"], cwd=workspace, check=False)
        assert result.returncode != 0

        # -c with multiple args (not one shell string)
        result2 = _tsrc(
            ["foreach", "-c", "echo", "hello"],
            cwd=workspace,
            check=False,
        )
        assert result2.returncode != 0


class TestSyncWithBranch:
    """Tests for sync branch handling."""

    def test_sync_with_correct_branch(self, workspace, git_server):
        """tsrc sync corrects the branch if repo is on wrong branch and clean."""
        url = _setup_remote_repo(
            git_server, "branch_repo", files={"main.txt": "main content"}, branch="main"
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "branch_repo", "url": url, "branch": "main"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Switch to a different branch locally
        repo_path = workspace / "branch_repo"
        _git(repo_path, "checkout", "-b", "feature")

        # Sync should correct back to main
        _tsrc(["sync"], cwd=workspace)
        branch = _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        assert branch == "main"

    def test_sync_no_correct_branch(self, workspace, git_server):
        """tsrc sync --no-correct-branch leaves the repo on its current branch."""
        url = _setup_remote_repo(git_server, "nocorrect_repo", branch="main")
        manifest_content = _make_manifest_yaml(
            {"dest": "nocorrect_repo", "url": url, "branch": "main"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        repo_path = workspace / "nocorrect_repo"
        _git(repo_path, "checkout", "-b", "feature")

        # Sync with --no-correct-branch: should stay on feature
        # (but report an error about wrong branch)
        result = _tsrc(
            ["sync", "--no-correct-branch", "--no-update-manifest"],
            cwd=workspace,
            check=False,
        )
        branch = _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        assert branch == "feature"


class TestDumpManifest:
    """Tests for tsrc dump-manifest command."""

    def test_dump_manifest_preview_yaml_with_url(self, workspace, git_server):
        """tsrc dump-manifest -p outputs valid YAML to stdout containing
        repo dest, 'repos' key, and URL reference."""
        url = _setup_remote_repo(git_server, "yaml_repo", files={"y.txt": "yaml test"})
        manifest_content = _make_manifest_yaml(
            {"dest": "yaml_repo", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        result = _tsrc(["dump-manifest", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "yaml_repo" in combined
        assert "repos" in combined
        # The dumped manifest must round-trip the repo's exact configured url,
        # not merely emit a url-shaped token.
        assert url in combined


class TestNestedDest:
    """Tests for repos with nested destination paths."""

    def test_nested_and_deeply_nested_repo_dest(self, workspace, git_server):
        """Repos can have nested destination paths like org/repo and even
        deeper like company/team/service. foreach should find them all."""
        url_a = _setup_remote_repo(
            git_server, "nested_src", files={"nested.txt": "nested content"}
        )
        url_b = _setup_remote_repo(git_server, "deep_a", files={"a.txt": "deep_a"})
        url_c = _setup_remote_repo(git_server, "deep_b", files={"b.txt": "deep_b"})
        manifest_content = _make_manifest_yaml(
            {"dest": "org/nested_src", "url": url_a},
            {"dest": "company/team1/service-a", "url": url_b},
            {"dest": "company/team2/service-b", "url": url_c},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        assert (
            workspace / "org" / "nested_src" / "nested.txt"
        ).read_text() == "nested content"
        assert (
            workspace / "company" / "team1" / "service-a" / "a.txt"
        ).read_text() == "deep_a"
        assert (
            workspace / "company" / "team2" / "service-b" / "b.txt"
        ).read_text() == "deep_b"

        # Foreach should find all deeply nested repos
        result = _tsrc(["foreach", "-c", "pwd"], cwd=workspace)
        combined = result.stdout + result.stderr
        assert "nested_src" in combined
        assert "service-a" in combined
        assert "service-b" in combined


# ===========================================================================
# HARDENING: Tests for scope gaps, deeper assertions, and complex flows
# ===========================================================================


class TestShallowClone:
    """Tests for --shallow clone option."""

    def test_init_shallow_clones_repos(self, workspace, git_server):
        """tsrc init --shallow creates shallow clones with depth 1."""
        url = _setup_remote_repo(git_server, "shallow_repo", files={"s.txt": "shallow"})
        # Add extra commits so we can verify shallowness
        remote_path = git_server / "shallow_repo"
        for i in range(5):
            (remote_path / f"extra_{i}.txt").write_text(f"extra {i}")
            _git(remote_path, "add", f"extra_{i}.txt")
            _git(remote_path, "commit", "-m", f"extra commit {i}")

        manifest_content = _make_manifest_yaml(
            {"dest": "shallow_repo", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}", "--shallow"], cwd=workspace)

        # Verify repo was cloned
        assert (workspace / "shallow_repo" / "s.txt").exists()
        # Verify it is actually a shallow clone: git rev-list --count HEAD should be 1
        result = _git(workspace / "shallow_repo", "rev-list", "--count", "HEAD")
        commit_count = int(result.stdout.strip())
        assert (
            commit_count == 1
        ), f"Expected 1 commit in shallow clone, got {commit_count}"

    def test_shallow_clone_rejects_sha1_pin(self, workspace, git_server):
        """tsrc init --shallow with a sha1-pinned repo produces an error."""
        url = _setup_remote_repo(git_server, "sha1_shallow")
        remote_path = git_server / "sha1_shallow"
        sha1 = _git(remote_path, "rev-parse", "HEAD").stdout.strip()

        manifest_content = _make_manifest_yaml(
            {"dest": "sha1_shallow", "url": url, "sha1": sha1},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        result = _tsrc(
            ["init", f"file://{manifest_path}", "--shallow"],
            cwd=workspace,
            check=False,
        )
        assert result.returncode != 0


class TestSyncTagAndSha1Advanced:
    """Tests for complex sync scenarios involving tags and sha1 pins."""

    def test_sync_tag_pinned_repo_stays_at_tag(self, workspace, git_server):
        """After init with a tag, sync keeps the repo at the tagged commit,
        not moving to HEAD."""
        repo_path = git_server / "tag_sync"
        _create_git_repo(repo_path, files={"v1.txt": "v1data"})
        _git(repo_path, "tag", "release-1.0")
        # Add commits past the tag
        (repo_path / "v2.txt").write_text("v2data")
        _git(repo_path, "add", "v2.txt")
        _git(repo_path, "commit", "-m", "post-tag commit")
        url = f"file://{repo_path}"

        manifest_content = _make_manifest_yaml(
            {"dest": "tag_sync", "url": url, "tag": "release-1.0"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Verify initial state
        assert (workspace / "tag_sync" / "v1.txt").exists()
        assert not (workspace / "tag_sync" / "v2.txt").exists()

        # Add more commits on the remote past the tag
        (repo_path / "v3.txt").write_text("v3data")
        _git(repo_path, "add", "v3.txt")
        _git(repo_path, "commit", "-m", "more post-tag")

        # Sync should keep the repo at the tag, not move to latest
        _tsrc(["sync"], cwd=workspace)
        assert (workspace / "tag_sync" / "v1.txt").exists()
        assert not (workspace / "tag_sync" / "v2.txt").exists()
        assert not (workspace / "tag_sync" / "v3.txt").exists()

    def test_sync_sha1_pinned_updates_on_fetch_then_resets(self, workspace, git_server):
        """Sync with sha1 pin fetches and resets to the exact commit.
        Verifying the sha1 pin stays consistent after multiple syncs."""
        repo_path = git_server / "sha1_sync"
        _create_git_repo(repo_path, files={"base.txt": "base"})
        pinned = _git(repo_path, "rev-parse", "HEAD").stdout.strip()

        # Add more commits
        (repo_path / "later.txt").write_text("later")
        _git(repo_path, "add", "later.txt")
        _git(repo_path, "commit", "-m", "later commit")
        url = f"file://{repo_path}"

        manifest_content = _make_manifest_yaml(
            {"dest": "sha1_sync", "url": url, "sha1": pinned},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Verify pinned at correct commit
        ws_sha = _git(workspace / "sha1_sync", "rev-parse", "HEAD").stdout.strip()
        assert ws_sha == pinned
        assert not (workspace / "sha1_sync" / "later.txt").exists()

        # Sync again -- should stay at pinned sha1
        _tsrc(["sync"], cwd=workspace)
        ws_sha_after = _git(workspace / "sha1_sync", "rev-parse", "HEAD").stdout.strip()
        assert ws_sha_after == pinned


class TestSyncCleanFlags:
    """Tests for sync --clean and --hard-clean flags."""

    def test_sync_clean_removes_untracked_files(self, workspace, git_server):
        """tsrc sync --clean removes untracked (non-ignored) files from repos."""
        _setup_workspace(
            git_server,
            workspace,
            [{"dest": "clean_repo", "files": {"tracked.txt": "tracked"}}],
        )
        repo_path = workspace / "clean_repo"

        # Create an untracked file
        (repo_path / "untracked_junk.txt").write_text("junk")
        assert (repo_path / "untracked_junk.txt").exists()

        _tsrc(["sync", "--clean"], cwd=workspace)
        # Untracked file should be cleaned
        assert not (repo_path / "untracked_junk.txt").exists()
        # Tracked file should remain
        assert (repo_path / "tracked.txt").read_text() == "tracked"

    def test_sync_hard_clean_removes_gitignored_files(self, workspace, git_server):
        """tsrc sync --hard-clean removes even .gitignore'd files."""
        url = _setup_remote_repo(
            git_server,
            "hard_clean_repo",
            files={"code.py": "print('hi')", ".gitignore": "*.pyc\nbuild/\n"},
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "hard_clean_repo", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        repo_path = workspace / "hard_clean_repo"
        # Create a gitignored file and an untracked file
        (repo_path / "compiled.pyc").write_text("bytecode")
        (repo_path / "temp.txt").write_text("temp")
        assert (repo_path / "compiled.pyc").exists()
        assert (repo_path / "temp.txt").exists()

        _tsrc(["sync", "--hard-clean"], cwd=workspace)
        # Both should be removed
        assert not (repo_path / "compiled.pyc").exists()
        assert not (repo_path / "temp.txt").exists()
        # Tracked files remain
        assert (repo_path / "code.py").read_text() == "print('hi')"


class TestSyncForceFlag:
    """Tests for sync --force flag."""

    def test_sync_force_passes_force_to_fetch(self, workspace, git_server):
        """tsrc sync --force passes --force to git fetch, accepting a
        force-updated tag that a plain (non-force) fetch refuses.

        A tag-pinned repo is reset to its tag on every sync. When the remote
        moves the tag to a new commit (git tag -f), a non-force fetch rejects
        the clobbering ref update ('would clobber existing tag'), so a bare
        sync leaves the repo at the OLD tag target; only sync --force fetches
        the moved tag and resets the repo to the NEW one. This distinguishes a
        correct --force wiring from a no-op, which the previous fast-forward
        scenario could not."""
        url = _setup_remote_repo(git_server, "force_repo", files={"latest.txt": "v1"})
        remote_path = git_server / "force_repo"
        # Pin the repo to a tag so each sync resets to that tag's target.
        _git(remote_path, "tag", "latest")

        manifest_content = _make_manifest_yaml(
            {"dest": "force_repo", "url": url, "tag": "latest"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Workspace starts at the original tag target.
        assert (workspace / "force_repo" / "latest.txt").read_text() == "v1"

        # Remote advances and force-moves the tag onto the new commit.
        (remote_path / "latest.txt").write_text("v2")
        _git(remote_path, "add", "latest.txt")
        _git(remote_path, "commit", "-m", "v2 update")
        _git(remote_path, "tag", "-f", "latest")

        # A bare sync's non-force fetch refuses the clobbering tag update, so
        # the local tag (and thus the repo reset target) stays at the old commit.
        _tsrc(["sync"], cwd=workspace, check=False)
        assert (workspace / "force_repo" / "latest.txt").read_text() == "v1"

        # sync --force fetches the moved tag and resets the repo to the new one.
        _tsrc(["sync", "--force"], cwd=workspace)
        assert (workspace / "force_repo" / "latest.txt").read_text() == "v2"


class TestManifestBranchSwitch:
    """Tests for tsrc manifest -b (branch switching)."""

    def test_manifest_branch_switch_updates_config(self, workspace, git_server):
        """tsrc manifest -b changes the configured manifest branch in config.yml,
        so the next sync will fetch from the new branch."""
        url = _setup_remote_repo(git_server, "mb_repo")
        manifest_content = _make_manifest_yaml({"dest": "mb_repo", "url": url})
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content, branch="main")
        # Create a 'develop' branch on the manifest repo
        _git(manifest_path, "checkout", "-b", "develop")
        _git(manifest_path, "checkout", "main")

        _tsrc(["init", f"file://{manifest_path}", "--branch", "main"], cwd=workspace)

        # Switch manifest branch to develop
        _tsrc(["manifest", "-b", "develop"], cwd=workspace)

        # Config should now record 'develop' as the manifest branch
        config_text = (workspace / ".tsrc" / "config.yml").read_text()
        assert "develop" in config_text


class TestSyncWithIncludeExcludeRegex:
    """Tests for sync with -i and -e regex filters."""

    def test_sync_include_regex_only_syncs_matching(self, workspace, git_server):
        """tsrc sync -i only syncs repos matching the include regex."""
        url_a = _setup_remote_repo(git_server, "lib-core", files={"a.txt": "core"})
        url_b = _setup_remote_repo(git_server, "lib-extra", files={"b.txt": "extra"})
        manifest_content = _make_manifest_yaml(
            {"dest": "lib-core", "url": url_a},
            {"dest": "lib-extra", "url": url_b},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Add new commits to both repos
        for name in ("lib-core", "lib-extra"):
            remote = git_server / name
            (remote / "update.txt").write_text(f"updated-{name}")
            _git(remote, "add", "update.txt")
            _git(remote, "commit", "-m", f"update {name}")

        # Only sync repos matching 'core'
        _tsrc(["sync", "-i", "core"], cwd=workspace)

        # lib-core should have the update
        assert (workspace / "lib-core" / "update.txt").read_text() == "updated-lib-core"
        # lib-extra should NOT have the update (it wasn't synced)
        assert not (workspace / "lib-extra" / "update.txt").exists()


class TestSyncSwitchFlag:
    """Tests for tsrc sync --switch with manifest switch config."""

    def test_sync_switch_updates_config_groups(self, workspace, git_server):
        """tsrc sync --switch applies the switch config from the manifest,
        changing workspace groups to match the manifest's switch section."""
        url_a = _setup_remote_repo(git_server, "core_svc")
        url_b = _setup_remote_repo(git_server, "extra_svc")
        manifest_content = _make_manifest_yaml(
            {"dest": "core_svc", "url": url_a},
            {"dest": "extra_svc", "url": url_b},
            groups={
                "core": {"repos": ["core_svc"]},
                "all": {"repos": ["extra_svc"], "includes": ["core"]},
            },
            switch={"config": {"groups": ["core"]}},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(
            ["init", f"file://{manifest_path}", "--clone-all-repos"],
            cwd=workspace,
        )

        # Sync with --switch to apply switch config
        _tsrc(["sync", "--switch"], cwd=workspace)

        # Config's repo_groups should be REPLACED by exactly the switch group
        # set (['core']), not merely contain 'core' alongside stale groups.
        import ruamel.yaml

        config_path = workspace / ".tsrc" / "config.yml"
        yaml = ruamel.yaml.YAML(typ="rt")
        config = yaml.load(config_path.read_text())
        assert list(config["repo_groups"]) == ["core"]


class TestCopyOnSync:
    """Tests for copy operations being re-applied on sync."""

    def test_copy_reapplied_after_source_file_changes(self, workspace, git_server):
        """When a file that has a copy directive changes in the remote repo,
        tsrc sync re-copies the updated file."""
        url = _setup_remote_repo(
            git_server,
            "copy_sync_repo",
            files={"config.json": '{"version": 1}'},
        )
        manifest_content = _make_manifest_yaml(
            {
                "dest": "copy_sync_repo",
                "url": url,
                "copy": [{"file": "config.json", "dest": "app_config.json"}],
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Verify initial copy
        assert (workspace / "app_config.json").read_text() == '{"version": 1}'

        # Update the source file in the remote
        remote = git_server / "copy_sync_repo"
        (remote / "config.json").write_text('{"version": 2}')
        _git(remote, "add", "config.json")
        _git(remote, "commit", "-m", "bump version")

        # Sync should pull the update AND re-copy
        _tsrc(["sync"], cwd=workspace)
        assert (
            workspace / "copy_sync_repo" / "config.json"
        ).read_text() == '{"version": 2}'
        assert (workspace / "app_config.json").read_text() == '{"version": 2}'


class TestAllClonedFlag:
    """Tests for --all-cloned flag on status/foreach."""

    def test_status_all_cloned_shows_all_repos(self, workspace, git_server):
        """tsrc status --all-cloned shows status for every cloned repo,
        regardless of group configuration."""
        url_a = _setup_remote_repo(git_server, "grp_repo_a")
        url_b = _setup_remote_repo(git_server, "grp_repo_b")
        manifest_content = _make_manifest_yaml(
            {"dest": "grp_repo_a", "url": url_a},
            {"dest": "grp_repo_b", "url": url_b},
            groups={"only_a": {"repos": ["grp_repo_a"]}},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        # Init with --clone-all-repos so both are cloned, but config records only_a
        _tsrc(
            ["init", f"file://{manifest_path}", "--clone-all-repos"],
            cwd=workspace,
        )

        # status --all-cloned should show both repos
        result = _tsrc(["status", "--all-cloned"], cwd=workspace)
        combined = result.stdout + result.stderr
        assert "grp_repo_a" in combined
        assert "grp_repo_b" in combined


class TestSingularRemote:
    """Tests for --singular-remote / -r flag on init."""

    def test_init_singular_remote_only_uses_named_remote(self, workspace, git_server):
        """tsrc init -r specifies which remote to use when a repo has multiple."""
        repo_path = git_server / "sr_repo"
        _create_git_repo(repo_path, files={"sr.txt": "singular"})
        url = f"file://{repo_path}"

        manifest_content = _make_manifest_yaml(
            {
                "dest": "sr_repo",
                "remotes": [
                    {"name": "primary", "url": url},
                    {"name": "secondary", "url": url},
                ],
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(
            ["init", f"file://{manifest_path}", "-r", "primary"],
            cwd=workspace,
        )

        # Repo should be cloned
        assert (workspace / "sr_repo" / "sr.txt").read_text() == "singular"
        # Config should record singular_remote
        config_text = (workspace / ".tsrc" / "config.yml").read_text()
        assert "primary" in config_text


class TestInitSyncStatusWorkflow:
    """Tests for multi-step workflows that chain operations together."""

    def test_sync_clones_new_repo_without_disturbing_dirty_existing_repo(
        self, workspace, git_server
    ):
        """Cross-operation invariant: when a manifest update adds a new repo,
        a sync clones that new repo WITHOUT touching an unrelated existing repo
        that has uncommitted local changes -- the dirty file's content survives.

        This is the integration property the per-command tests don't check:
        test_sync_clones_new_repos covers cloning in isolation and
        test_sync_reports_dirty_repos covers a dirty pinned repo, but neither
        verifies that cloning a newly-added repo leaves a *different* repo's
        dirty working tree intact."""
        url_a = _setup_remote_repo(git_server, "wf_alpha", files={"a.txt": "alpha"})
        manifest_content = _make_manifest_yaml(
            {"dest": "wf_alpha", "url": url_a},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Dirty wf_alpha BEFORE the sync (uncommitted local edit + new file).
        (workspace / "wf_alpha" / "a.txt").write_text("locally-edited")
        (workspace / "wf_alpha" / "scratch.txt").write_text("work-in-progress")

        # Add a new repo to the manifest.
        url_b = _setup_remote_repo(git_server, "wf_beta", files={"b.txt": "beta"})
        updated = _make_manifest_yaml(
            {"dest": "wf_alpha", "url": url_a},
            {"dest": "wf_beta", "url": url_b},
        )
        (manifest_path / "manifest.yml").write_text(updated)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "add wf_beta")

        # Sync clones wf_beta. wf_alpha is on its branch and only has uncommitted
        # changes (no divergence), so the ff-only sync touches it without
        # discarding the dirty content.
        _tsrc(["sync"], cwd=workspace)

        # New repo was cloned...
        assert (workspace / "wf_beta" / "b.txt").read_text() == "beta"
        # ...and the existing repo's uncommitted edits were preserved.
        assert (workspace / "wf_alpha" / "a.txt").read_text() == "locally-edited"
        assert (workspace / "wf_alpha" / "scratch.txt").read_text() == "work-in-progress"

    def test_group_selection_persists_across_sync(self, workspace, git_server):
        """Cross-operation invariant: the group chosen at `init -g web` is
        persisted to config and HONORED by a later bare `sync` -- which updates
        only the in-group repos and does NOT pull in the out-of-group `database`
        repo, even though it is present in the manifest.

        The per-command group tests (test_init_with_groups, test_default_group,
        test_foreach_with_group_filter) each check selection for a single
        command in isolation; this asserts the selection survives the init ->
        sync handoff via config, which they cannot."""
        url_fe = _setup_remote_repo(
            git_server, "frontend", files={"index.html": "<h1>hi</h1>"}
        )
        url_be = _setup_remote_repo(
            git_server, "backend", files={"server.py": "app.run()"}
        )
        url_db = _setup_remote_repo(
            git_server, "database", files={"schema.sql": "CREATE TABLE t;"}
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "frontend", "url": url_fe},
            {"dest": "backend", "url": url_be},
            {"dest": "database", "url": url_db},
            groups={
                "web": {"repos": ["frontend", "backend"]},
                "data": {"repos": ["database"]},
                "all": {"repos": ["frontend", "backend", "database"]},
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        # Init with web group only
        _tsrc(
            ["init", f"file://{manifest_path}", "-g", "web"],
            cwd=workspace,
        )

        # frontend and backend should be cloned, database should not
        assert (workspace / "frontend").is_dir()
        assert (workspace / "backend").is_dir()
        assert not (workspace / "database").exists()

        # Add remote changes to an in-group repo
        remote_fe = git_server / "frontend"
        (remote_fe / "style.css").write_text("body{}")
        _git(remote_fe, "add", "style.css")
        _git(remote_fe, "commit", "-m", "add css")

        # A bare sync (no -g) must use the persisted 'web' group: it updates
        # frontend but must NOT clone the out-of-group database repo.
        _tsrc(["sync"], cwd=workspace)
        assert (workspace / "frontend" / "style.css").read_text() == "body{}"
        assert not (
            workspace / "database"
        ).exists(), "sync pulled in an out-of-group repo, ignoring persisted group selection"


class TestSyncBranchCorrection:
    """Tests for sync branch correction with dirty repos."""

    def test_sync_refuses_branch_correction_on_dirty_repo(self, workspace, git_server):
        """tsrc sync cannot correct branch when the repo is dirty --
        it reports an error instead of destroying changes."""
        url = _setup_remote_repo(
            git_server, "dirty_branch", files={"main.txt": "content"}, branch="main"
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "dirty_branch", "url": url, "branch": "main"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        repo_path = workspace / "dirty_branch"
        # Switch to feature branch and make it dirty
        _git(repo_path, "checkout", "-b", "feature")
        (repo_path / "dirty.txt").write_text("uncommitted")
        _git(repo_path, "add", "dirty.txt")

        # Sync should fail because repo is dirty AND on wrong branch
        result = _tsrc(["sync"], cwd=workspace, check=False)
        assert result.returncode != 0
        # Verify the dirty file is still there (not destroyed)
        assert (repo_path / "dirty.txt").read_text() == "uncommitted"


class TestMultipleCopyAndSymlink:
    """Tests for multiple copy and symlink operations in one manifest."""

    def test_copy_source_in_subdirectory_of_repo(self, workspace, git_server):
        """A copy directive's `file` may be a path nested in a subdirectory of
        the repo: it is read relative to the repo's own dest directory and
        written to `dest` under the workspace root.

        This is the distinct branch that the top-level copy tests
        (test_manifest_with_copy_and_default_dest) don't reach -- there the
        source is always a file at the repo root, so the repo/<subdir>/<file>
        source-path join is never exercised."""
        url = _setup_remote_repo(
            git_server,
            "subdir_copy",
            files={
                "configs/app.conf": "listen_port=9090",
                "README.md": "# Subdir Copy",
            },
        )
        manifest_content = _make_manifest_yaml(
            {
                "dest": "subdir_copy",
                "url": url,
                "copy": [
                    {"file": "configs/app.conf", "dest": "deployed.conf"},
                ],
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # The nested source is resolved against the repo dest and copied to the
        # workspace-root dest.
        assert (workspace / "deployed.conf").read_text() == "listen_port=9090"


class TestLogWithMultipleRepos:
    """Tests for tsrc log across multiple repos."""

    def test_log_filters_commits_to_from_to_range_per_repo(
        self, workspace, git_server
    ):
        """tsrc log reports, for each repo, only the commits in the `from..to`
        range -- the range boundary is applied per repo. A commit that lies
        BEFORE `from` in one repo must not appear, while an in-range commit in
        another repo does. This is the range-filtering contract, distinct from
        TestLog.test_log_shows_changes_and_no_changes (which only checks an
        in-range commit is shown and that from == to shows nothing)."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "changed_repo"},
                {"dest": "quiet_repo"},
            ],
        )

        # quiet_repo: make a distinctively-messaged commit, THEN tag `base` on
        # it -- so that commit is at/below `base` and thus out of `base..HEAD`.
        quiet_path = workspace / "quiet_repo"
        (quiet_path / "old.txt").write_text("old")
        _git(quiet_path, "add", "old.txt")
        _git(quiet_path, "commit", "-m", "QUIET_BASELINE_ONLY before the range")
        _git(quiet_path, "tag", "base")

        # changed_repo: tag `base` first, THEN add a commit -- so it IS in range.
        changed_path = workspace / "changed_repo"
        _git(changed_path, "tag", "base")
        (changed_path / "new_file.txt").write_text("new content")
        _git(changed_path, "add", "new_file.txt")
        _git(changed_path, "commit", "-m", "IN_RANGE important change")

        result = _tsrc(["log", "--from", "base"], cwd=workspace)
        combined = result.stdout + result.stderr
        # The in-range commit of changed_repo is reported...
        assert "IN_RANGE important change" in combined
        # ...while quiet_repo's pre-`base` commit is filtered out of the range,
        # so its message never appears (proving per-repo from..to filtering, not
        # a global "any commit anywhere" dump).
        assert "QUIET_BASELINE_ONLY" not in combined


class TestStatusWithFiltering:
    """Tests for status with group and regex filtering."""

    def test_status_with_group_filter(self, workspace, git_server):
        """tsrc status -g shows status only for repos in the specified group."""
        url_a = _setup_remote_repo(git_server, "st_repo_in")
        url_b = _setup_remote_repo(git_server, "st_repo_out")
        manifest_content = _make_manifest_yaml(
            {"dest": "st_repo_in", "url": url_a},
            {"dest": "st_repo_out", "url": url_b},
            groups={"selected": {"repos": ["st_repo_in"]}},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(
            ["init", f"file://{manifest_path}", "--clone-all-repos"],
            cwd=workspace,
        )

        result = _tsrc(["status", "-g", "selected"], cwd=workspace)
        combined = result.stdout + result.stderr
        assert "st_repo_in" in combined
        assert "st_repo_out" not in combined


# ===========================================================================
# ROUND 2 HARDENING: Tests requiring PRECISE behavioral details
# ===========================================================================


class TestSyncMergeSemantics:
    """Tests that verify the exact merge behavior of tsrc sync."""

    def test_sync_rejects_non_fast_forward_merge(self, workspace, git_server):
        """tsrc sync uses merge --ff-only which means it refuses
        non-fast-forward merges. If the local branch has diverged from
        upstream (local commits not in upstream), sync should fail."""
        url = _setup_remote_repo(
            git_server, "ff_repo", files={"base.txt": "base"}, branch="main"
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "ff_repo", "url": url, "branch": "main"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        repo_path = workspace / "ff_repo"

        # Add a LOCAL commit that is NOT on the remote (diverge)
        (repo_path / "local_only.txt").write_text("local change")
        _git(repo_path, "add", "local_only.txt")
        _git(repo_path, "commit", "-m", "local divergence")

        # Also add a commit to the REMOTE (to create a true divergence)
        remote_path = git_server / "ff_repo"
        (remote_path / "remote_only.txt").write_text("remote change")
        _git(remote_path, "add", "remote_only.txt")
        _git(remote_path, "commit", "-m", "remote divergence")

        # Sync should fail: can't fast-forward because branches diverged
        result = _tsrc(["sync"], cwd=workspace, check=False)
        assert result.returncode != 0

        # Local commit should still be there (not destroyed)
        assert (repo_path / "local_only.txt").read_text() == "local change"
        # Remote file should NOT be here (merge didn't happen)
        assert not (repo_path / "remote_only.txt").exists()

    def test_sync_fetch_uses_tags_and_prune(self, workspace, git_server):
        """tsrc sync fetches with --tags --prune. Verify that remote tags
        are fetched locally and deleted remote tags are pruned."""
        url = _setup_remote_repo(git_server, "tags_repo", files={"file.txt": "content"})
        manifest_content = _make_manifest_yaml(
            {"dest": "tags_repo", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Create a tag on the remote
        remote_path = git_server / "tags_repo"
        _git(remote_path, "tag", "v2.0")

        # Sync should fetch the new tag
        _tsrc(["sync"], cwd=workspace)

        # Verify the tag was fetched
        result = _git(workspace / "tags_repo", "tag", "--list")
        assert "v2.0" in result.stdout


class TestSyncDetachedHead:
    """Tests for sync behavior when repo is in detached HEAD state."""

    def test_sync_on_detached_head_reports_error(self, workspace, git_server):
        """When a non-pinned repo is in detached HEAD state (not on any branch),
        tsrc sync should report an error since it can't determine the correct
        branch."""
        url = _setup_remote_repo(
            git_server, "detached_repo", files={"f.txt": "content"}, branch="main"
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "detached_repo", "url": url, "branch": "main"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        repo_path = workspace / "detached_repo"
        # Detach HEAD by checking out a specific commit
        sha1 = _git(repo_path, "rev-parse", "HEAD").stdout.strip()
        _git(repo_path, "checkout", sha1)

        # Sync should report an error about wrong branch (or missing branch)
        # with --no-correct-branch, since the repo is on no branch
        result = _tsrc(
            ["sync", "--no-correct-branch"],
            cwd=workspace,
            check=False,
        )
        assert result.returncode != 0


class TestWorkspaceDiscovery:
    """Tests for workspace discovery by walking up directories."""

    def test_workspace_found_from_subdirectory(self, workspace, git_server):
        """tsrc commands work when run from a subdirectory of the workspace,
        since tsrc walks up the directory tree to find .tsrc/."""
        _setup_workspace(
            git_server,
            workspace,
            [{"dest": "discovery_repo", "files": {"d.txt": "discover"}}],
        )

        # Create a deep subdirectory within the workspace
        subdir = workspace / "discovery_repo" / "subdir" / "deep"
        subdir.mkdir(parents=True, exist_ok=True)

        # Run tsrc status from the subdirectory -- should find workspace
        result = _tsrc(["status"], cwd=subdir)
        combined = result.stdout + result.stderr
        assert "discovery_repo" in combined


class TestManifestValidationEdgeCases:
    """Tests for manifest validation edge cases."""

    def test_repo_without_url_or_remotes_is_rejected(self, workspace, git_server):
        """A repo entry with neither url nor remotes is invalid."""
        manifest_text = textwrap.dedent(
            """\
            repos:
              - dest: no_remote_repo
        """
        )
        manifest_dir = git_server / "normt_manifest"
        _create_manifest_repo(manifest_dir, manifest_text)
        result = _tsrc(["init", f"file://{manifest_dir}"], cwd=workspace, check=False)
        assert result.returncode != 0

    def test_manifest_with_invalid_yaml_is_rejected(self, workspace, git_server):
        """A manifest with invalid YAML syntax is rejected."""
        manifest_text = "repos:\n  - dest: bad\n  url: missing_indent\n"
        manifest_dir = git_server / "badyaml_manifest"
        _create_manifest_repo(manifest_dir, manifest_text)
        result = _tsrc(["init", f"file://{manifest_dir}"], cwd=workspace, check=False)
        assert result.returncode != 0


class TestSyncSubmoduleDefault:
    """Tests that sync handles submodules by default (unless ignore_submodules)."""

    def test_ignore_submodules_leaves_submodule_uninitialized(
        self, workspace, git_server
    ):
        """ignore_submodules: true makes tsrc clone/sync WITHOUT recursing into
        submodules, so the submodule's working tree stays empty.

        The repo embeds a real submodule whose tracked file is `sub_marker.txt`.
        Honoring the flag (no --recurse-submodules on clone, no `git submodule
        update` on sync) is the only thing that leaves that file absent."""
        sub_url = _setup_remote_repo(
            git_server, "sub_src", files={"sub_marker.txt": "from-submodule"}
        )
        _setup_remote_repo(git_server, "has_sub", files={"main.py": "pass"})
        _add_submodule_to_remote(git_server, "has_sub", sub_url, "libs/sub")
        url = f"file://{git_server / 'has_sub'}"

        manifest_content = _make_manifest_yaml(
            {"dest": "has_sub", "url": url, "ignore_submodules": True},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # The parent repo is cloned, but the submodule is NOT checked out.
        assert (workspace / "has_sub" / "main.py").read_text() == "pass"
        assert not (workspace / "has_sub" / "libs" / "sub" / "sub_marker.txt").exists()

        # Sync must not initialize the submodule either.
        _tsrc(["sync"], cwd=workspace)
        assert not (workspace / "has_sub" / "libs" / "sub" / "sub_marker.txt").exists()

    def test_default_recurses_and_populates_submodule(self, workspace, git_server):
        """With the default (ignore_submodules omitted / false) tsrc clones with
        --recurse-submodules, so the submodule's tracked file IS present after
        init -- the observable opposite of the ignore_submodules case above."""
        sub_url = _setup_remote_repo(
            git_server, "sub_src2", files={"sub_marker.txt": "from-submodule"}
        )
        _setup_remote_repo(git_server, "with_sub", files={"main.py": "pass"})
        _add_submodule_to_remote(git_server, "with_sub", sub_url, "libs/sub")
        url = f"file://{git_server / 'with_sub'}"

        manifest_content = _make_manifest_yaml(
            {"dest": "with_sub", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # The submodule is recursed into and checked out.
        assert (
            workspace / "with_sub" / "libs" / "sub" / "sub_marker.txt"
        ).read_text() == "from-submodule"


class TestSyncMultipleRemoteFetch:
    """Tests for sync behavior with repos that have multiple remotes."""

    def test_sync_fetches_all_remotes(self, workspace, git_server):
        """When a repo has multiple remotes, sync fetches from all of them."""
        repo_path = git_server / "multi_r"
        _create_git_repo(repo_path, files={"base.txt": "base"})
        url = f"file://{repo_path}"

        # Create a second "remote" (same repo for test purposes)
        repo_path2 = git_server / "multi_r_upstream"
        _create_git_repo(repo_path2, files={"base.txt": "base"})
        url2 = f"file://{repo_path2}"

        manifest_content = _make_manifest_yaml(
            {
                "dest": "multi_r",
                "remotes": [
                    {"name": "origin", "url": url},
                    {"name": "upstream", "url": url2},
                ],
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Add a commit to the upstream remote
        (repo_path2 / "upstream_change.txt").write_text("from upstream")
        _git(repo_path2, "add", "upstream_change.txt")
        _git(repo_path2, "commit", "-m", "upstream commit")

        # Sync should fetch from both remotes (fetch --tags --prune for each)
        _tsrc(["sync"], cwd=workspace)

        # Verify both remotes are still configured
        result = _git(workspace / "multi_r", "remote", "-v")
        assert "origin" in result.stdout
        assert "upstream" in result.stdout

        # The upstream commit should be fetchable
        result2 = _git(
            workspace / "multi_r",
            "log",
            "--oneline",
            "--all",
            check=False,
        )
        # The upstream commit should appear in the fetched refs
        assert "upstream commit" in result2.stdout


# ===========================================================================
# DUMP-MANIFEST ADVANCED: Tests for dump-manifest coverage gaps
# ===========================================================================


class TestDumpManifestAdvanced:
    """Advanced tests for tsrc dump-manifest command covering update, save,
    filtering, sha1 flags, raw mode with nesting/filtering, and groups."""

    def test_dump_manifest_update_on_path(self, workspace, git_server):
        """tsrc dump-manifest -U PATH updates a specific manifest file
        instead of the Deep Manifest."""
        url_a = _setup_remote_repo(git_server, "uon_repo", files={"f.txt": "content"})
        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "uon_repo", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Create a separate manifest file to update
        import shutil

        target_manifest = workspace / "custom_manifest.yml"
        shutil.copy(workspace / "manifest" / "manifest.yml", target_manifest)

        # Change branch locally
        repo_path = workspace / "uon_repo"
        _git(repo_path, "checkout", "-b", "dev-branch")

        # Update the custom manifest file
        _tsrc(
            ["dump-manifest", "-U", str(target_manifest)],
            cwd=workspace,
        )

        # Verify the custom manifest was updated
        updated_content = target_manifest.read_text()
        assert "dev-branch" in updated_content
        assert "uon_repo" in updated_content

    def test_dump_manifest_save_to_force(self, workspace, git_server):
        """tsrc dump-manifest -s PATH -f saves to a file, overwriting
        if it already exists."""
        _setup_workspace(
            git_server,
            workspace,
            [{"dest": "stf_repo", "files": {"x.txt": "data"}}],
        )
        output_file = workspace / "output_manifest.yml"

        # First save (creates new file)
        _tsrc(
            ["dump-manifest", "-s", str(output_file)],
            cwd=workspace,
        )
        assert output_file.exists()
        content1 = output_file.read_text()
        assert "stf_repo" in content1

        # Second save without force should fail (file exists)
        result = _tsrc(
            ["dump-manifest", "-s", str(output_file)],
            cwd=workspace,
            check=False,
        )
        combined = result.stdout + result.stderr
        # tsrc catches exception and prints error, but may exit 0
        assert (
            "exist" in combined.lower()
            or "overwrite" in combined.lower()
            or result.returncode != 0
        )

        # Third save WITH force should succeed
        _tsrc(
            ["dump-manifest", "-s", str(output_file), "-f"],
            cwd=workspace,
        )
        content3 = output_file.read_text()
        assert "stf_repo" in content3

    def test_dump_manifest_skip_manifest_repo(self, workspace, git_server):
        """tsrc dump-manifest -X skips the manifest repo from the output."""
        url_a = _setup_remote_repo(
            git_server, "skip_repo", files={"s.txt": "skip test"}
        )
        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "skip_repo", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Dump with -X (skip manifest repo)
        result = _tsrc(["dump-manifest", "-X", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "skip_repo" in combined
        # Manifest repo should NOT appear in the dump output
        # Check that "manifest" appears only in noise lines (paths, etc.)
        # but not as a "dest: manifest" entry
        lines = combined.split("\n")
        dest_lines = [l for l in lines if "dest:" in l and "manifest" in l]
        assert (
            len(dest_lines) == 0
        ), f"Expected manifest repo to be skipped, but found: {dest_lines}"

    def test_dump_manifest_only_manifest_repo(self, workspace, git_server):
        """tsrc dump-manifest -M dumps ONLY the manifest repo."""
        url_a = _setup_remote_repo(git_server, "only_other", files={"o.txt": "other"})
        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "only_other", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Dump with -M (only manifest repo)
        result = _tsrc(["dump-manifest", "-M", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        # Should contain manifest repo
        lines = combined.split("\n")
        dest_lines = [l.strip() for l in lines if l.strip().startswith("- dest:")]
        # Only the manifest repo should be present
        assert len(dest_lines) == 1
        assert "manifest" in dest_lines[0]
        # other repo should NOT appear as a dest entry
        assert not any("only_other" in l for l in dest_lines)

    def test_dump_manifest_sha1_off(self, workspace, git_server):
        """tsrc dump-manifest --sha1-off ensures sha1 hashes are NOT
        included in the output."""
        _setup_workspace(
            git_server,
            workspace,
            [{"dest": "sha1off_repo", "files": {"f.txt": "val"}}],
        )
        result = _tsrc(
            ["dump-manifest", "--sha1-off", "-p"],
            cwd=workspace,
        )
        combined = result.stdout + result.stderr
        assert "sha1off_repo" in combined

        # Parse the YAML-like output: should NOT contain 'sha1:' key
        lines = combined.split("\n")
        sha1_lines = [
            l for l in lines if "sha1:" in l.lower() and "sha1-" not in l.lower()
        ]
        assert (
            len(sha1_lines) == 0
        ), f"Expected no sha1 field with --sha1-off, but found: {sha1_lines}"

    def test_dump_manifest_sha1_on_and_sha1_off_mutually_exclusive(
        self, workspace, git_server
    ):
        """tsrc dump-manifest --sha1-on --sha1-off together produce an error
        about mutually exclusive flags."""
        _setup_workspace(
            git_server,
            workspace,
            [{"dest": "mx_repo", "files": {"f.txt": "val"}}],
        )
        result = _tsrc(
            ["dump-manifest", "--sha1-on", "--sha1-off", "-p"],
            cwd=workspace,
            check=False,
        )
        combined = result.stdout + result.stderr
        assert "mutually exclusive" in combined.lower()

    def test_dump_manifest_raw_include_regex(self, tmp_path):
        """tsrc dump-manifest --raw -i REGEX only includes repos matching
        the include regex."""
        raw_dir = tmp_path / "filter_raw"
        raw_dir.mkdir()
        _create_git_repo(raw_dir / "alpha_svc", files={"a.txt": "alpha"})
        _create_git_repo(raw_dir / "beta_svc", files={"b.txt": "beta"})
        _create_git_repo(raw_dir / "gamma_lib", files={"g.txt": "gamma"})

        result = _tsrc(
            ["dump-manifest", "--raw", str(raw_dir), "-p", "-i", "svc"],
            cwd=tmp_path,
        )
        combined = result.stdout + result.stderr
        assert "alpha_svc" in combined
        assert "beta_svc" in combined
        assert "gamma_lib" not in combined

# ===========================================================================
# DUMP-MANIFEST DEEP: Tests for deep code paths in dump_manifest.py
# ===========================================================================


class TestDumpManifestDeep:
    """Deep integration tests for tsrc dump-manifest exercising the complex
    YAML manipulation logic in ManifestDumper: rename/collision handling,
    repo deletion, multi-remote preservation, tag/sha1 tracking, raw mode
    common path calculation, group preservation, and filtering."""

    def test_update_after_repo_removed(self, workspace, git_server):
        """dump-manifest -u reflects repo removal: when a repo is removed from
        the workspace (via manifest change + sync), updating the manifest
        should delete the removed repo entry from the YAML output."""
        url_a = _setup_remote_repo(git_server, "kept_repo", files={"a.txt": "keep"})
        url_b = _setup_remote_repo(
            git_server, "removed_repo", files={"b.txt": "remove"}
        )
        manifest_url_str = f"file://{git_server / 'manifest'}"

        manifest_content = _make_manifest_yaml(
            {"dest": "kept_repo", "url": url_a},
            {"dest": "removed_repo", "url": url_b},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Remove removed_repo from manifest
        updated_manifest = _make_manifest_yaml(
            {"dest": "kept_repo", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        (manifest_path / "manifest.yml").write_text(updated_manifest)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "remove removed_repo")

        # Sync to get updated manifest
        _tsrc(["sync"], cwd=workspace)

        # dump-manifest -u -p should not include removed_repo
        result = _tsrc(["dump-manifest", "-u", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "kept_repo" in combined
        lines = combined.split("\n")
        dest_lines = [l.strip() for l in lines if "dest:" in l]
        removed_dests = [l for l in dest_lines if "removed_repo" in l]
        assert (
            len(removed_dests) == 0
        ), f"removed_repo should not be in updated manifest, found: {removed_dests}"

    def test_update_with_multi_remote_repos(self, workspace, git_server):
        """dump-manifest -u -p with a repo configured with multiple remotes
        (origin + upstream) preserves the remotes list structure in the
        updated YAML output instead of collapsing to a single url field."""
        repo_path = git_server / "mr_repo"
        _create_git_repo(repo_path, files={"mr.txt": "multi"})
        url = f"file://{repo_path}"

        repo_path2 = git_server / "mr_repo_upstream"
        _create_git_repo(repo_path2, files={"mr.txt": "multi"})
        url2 = f"file://{repo_path2}"

        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {
                "dest": "mr_repo",
                "remotes": [
                    {"name": "origin", "url": url},
                    {"name": "upstream", "url": url2},
                ],
            },
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        result = _tsrc(["dump-manifest", "-u", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "mr_repo" in combined
        assert "remotes" in combined.lower()
        assert "origin" in combined
        assert "upstream" in combined

    def test_update_after_branch_change(self, workspace, git_server):
        """dump-manifest update reflects the current local branch after a branch
        switch, both in the -u -p preview output and in the written Deep Manifest
        file. When a repo is switched from master to a feature branch, the updated
        manifest must show the new branch name."""
        url_a = _setup_remote_repo(git_server, "branch_chg", files={"a.txt": "data"})
        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "branch_chg", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Switch to a new branch locally
        repo_path = workspace / "branch_chg"
        _git(repo_path, "checkout", "-b", "new-feature")
        (repo_path / "feature.txt").write_text("feature")
        _git(repo_path, "add", "feature.txt")
        _git(repo_path, "commit", "-m", "feature commit")

        # Preview output reflects the new branch.
        result = _tsrc(["dump-manifest", "-u", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr
        assert "branch_chg" in combined
        assert "new-feature" in combined

        # Writing the Deep Manifest in-place also reflects the new branch.
        _tsrc(["dump-manifest", "-u"], cwd=workspace)
        dm_content = (workspace / "manifest" / "manifest.yml").read_text()
        assert "branch_chg" in dm_content
        assert "new-feature" in dm_content

    def test_update_sha1_reflects_new_commits(self, workspace, git_server):
        """dump-manifest --sha1-on -u -p includes the sha1 of the current HEAD,
        not the old sha1. After adding new commits to a repo, the sha1 field
        in the updated manifest should match the new HEAD commit."""
        url_a = _setup_remote_repo(git_server, "sha_upd_repo", files={"a.txt": "v1"})
        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "sha_upd_repo", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        repo_path = workspace / "sha_upd_repo"
        initial_sha = _git(repo_path, "rev-parse", "HEAD").stdout.strip()

        # Add a commit
        (repo_path / "new.txt").write_text("new content")
        _git(repo_path, "add", "new.txt")
        _git(repo_path, "commit", "-m", "new commit")
        new_sha = _git(repo_path, "rev-parse", "HEAD").stdout.strip()

        result = _tsrc(["dump-manifest", "--sha1-on", "-u", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "sha_upd_repo" in combined
        assert new_sha in combined
        assert initial_sha not in combined

    def test_update_preserves_tag(self, workspace, git_server):
        """dump-manifest -u -p preserves the tag field when the repo is
        checked out at a tagged commit. The output should contain
        'tag: <tag_name>' for the pinned repo."""
        repo_path = git_server / "tag_pres_repo"
        _create_git_repo(repo_path, files={"v1.txt": "v1"})
        _git(repo_path, "tag", "v1.0")
        url = f"file://{repo_path}"

        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "tag_pres_repo", "url": url, "tag": "v1.0"},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        result = _tsrc(["dump-manifest", "-u", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "tag_pres_repo" in combined
        lines = combined.split("\n")
        tag_lines = [l.strip() for l in lines if "tag:" in l]
        assert any(
            "v1.0" in l for l in tag_lines
        ), f"Expected tag: v1.0 in output, found: {tag_lines}"

    def test_raw_common_path_calculation(self, tmp_path):
        """dump-manifest --raw discovers git repos at differing nesting depths
        and computes dest values relative to the common prefix of all
        discovered repos. Repos under projects/frontend/app, projects/backend/api
        and a shallower tools/cli are all found, each producing a dest derived
        from its path relative to the deepest common parent directory."""
        raw_dir = tmp_path / "raw_repos"
        raw_dir.mkdir()

        _create_git_repo(
            raw_dir / "projects" / "frontend" / "app",
            files={"f.txt": "front"},
        )
        _create_git_repo(
            raw_dir / "projects" / "backend" / "api",
            files={"b.txt": "back"},
        )
        _create_git_repo(
            raw_dir / "tools" / "cli",
            files={"c.txt": "cli"},
        )

        result = _tsrc(
            ["dump-manifest", "--raw", str(raw_dir), "-p"],
            cwd=tmp_path,
        )
        combined = result.stdout + result.stderr

        # One dest entry per discovered repo, each relativized against the
        # deepest common parent (raw_dir). The exact relative paths pin the
        # common-path/relativization computation -- absolute or wrongly-rooted
        # dests would fail here even though the repo names still appear.
        # Manifest YAML emits each repo as a `  - dest: <path>` list item.
        dest_values = {
            l.split("dest:", 1)[1].strip() for l in combined.split("\n") if "dest:" in l
        }
        assert dest_values == {
            "projects/frontend/app",
            "projects/backend/api",
            "tools/cli",
        }, f"Expected relativized dests, got: {sorted(dest_values)}"

    def test_update_groups_with_includes_preserved(self, workspace, git_server):
        """dump-manifest -u -p preserves group definitions including groups
        that use the 'includes' directive to compose other groups."""
        url_a = _setup_remote_repo(git_server, "grp_inc_a", files={"a.txt": "a"})
        url_b = _setup_remote_repo(git_server, "grp_inc_b", files={"b.txt": "b"})
        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "grp_inc_a", "url": url_a},
            {"dest": "grp_inc_b", "url": url_b},
            {"dest": "manifest", "url": manifest_url_str},
            groups={
                "team_alpha": {"repos": ["grp_inc_a"]},
                "team_beta": {"repos": ["grp_inc_b"]},
                "all_teams": {
                    "repos": ["grp_inc_a", "grp_inc_b"],
                    "includes": ["team_alpha"],
                },
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(
            ["init", f"file://{manifest_path}", "--clone-all-repos"],
            cwd=workspace,
        )

        result = _tsrc(["dump-manifest", "-u", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "groups" in combined.lower()
        assert "team_alpha" in combined
        assert "team_beta" in combined
        assert "all_teams" in combined
        # The includes composition itself must round-trip, not just the group
        # names: all_teams includes team_alpha. Without this, the output would
        # pass even if the includes directive were silently dropped.
        assert "includes" in combined
        # Pin the relationship: team_alpha is listed under all_teams' includes.
        # Isolate the all_teams group block (from its header to the next
        # top-level key / group) and require the includes -> team_alpha link there.
        all_teams_idx = combined.index("all_teams")
        all_teams_block = combined[all_teams_idx:]
        includes_idx = all_teams_block.find("includes")
        assert includes_idx != -1, "all_teams must retain its includes directive"
        assert "team_alpha" in all_teams_block[includes_idx:includes_idx + 60]

    def test_update_no_repo_delete_flag(self, workspace, git_server):
        """dump-manifest -U <path> --no-repo-delete preserves repo entries in
        the target manifest even if those repos are no longer in the workspace.
        This exercises the ManifestDumpersOptions.delete_repo=False path."""
        url_a = _setup_remote_repo(git_server, "still_here", files={"a.txt": "a"})
        url_b = _setup_remote_repo(git_server, "gone_repo", files={"b.txt": "b"})
        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "still_here", "url": url_a},
            {"dest": "gone_repo", "url": url_b},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Remove gone_repo from manifest and sync
        updated = _make_manifest_yaml(
            {"dest": "still_here", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        (manifest_path / "manifest.yml").write_text(updated)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "remove gone_repo")
        _tsrc(["sync"], cwd=workspace)

        # Create a target with both repos for update
        import shutil

        restored = _make_manifest_yaml(
            {"dest": "still_here", "url": url_a},
            {"dest": "gone_repo", "url": url_b},
            {"dest": "manifest", "url": manifest_url_str},
        )
        target_file = workspace / "target_manifest.yml"
        target_file.write_text(restored)

        # Update with --no-repo-delete
        result = _tsrc(
            [
                "dump-manifest",
                "-U",
                str(target_file),
                "--no-repo-delete",
                "-p",
            ],
            cwd=workspace,
        )
        combined = result.stdout + result.stderr

        assert "still_here" in combined
        # With --no-repo-delete, gone_repo should still be present
        assert "gone_repo" in combined

    def test_update_repo_dest_renamed(self, workspace, git_server):
        """dump-manifest -u detects when a repo URL maps to a new dest
        (same URL, different dest) and renames the entry in the YAML
        instead of deleting the old entry and adding a new one. This
        exercises the rename/collision logic in ManifestDumper."""
        url_a = _setup_remote_repo(git_server, "old_name", files={"a.txt": "data"})
        manifest_url_str = f"file://{git_server / 'manifest'}"
        manifest_content = _make_manifest_yaml(
            {"dest": "old_name", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Rename dest in manifest but keep same URL
        renamed = _make_manifest_yaml(
            {"dest": "new_name", "url": url_a},
            {"dest": "manifest", "url": manifest_url_str},
        )
        (manifest_path / "manifest.yml").write_text(renamed)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "rename old_name to new_name")
        _tsrc(["sync"], cwd=workspace)

        result = _tsrc(["dump-manifest", "-u", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "new_name" in combined
        lines = combined.split("\n")
        dest_lines = [l.strip() for l in lines if "dest:" in l]
        old_dests = [l for l in dest_lines if "old_name" in l]
        assert len(old_dests) == 0, f"old_name should not appear, found: {old_dests}"

    def test_dump_manifest_include_regex_workspace_mode(self, workspace, git_server):
        """dump-manifest -i REGEX -p in workspace mode only outputs repos
        whose dest matches the include regex, filtering out non-matching
        repos from the YAML output."""
        url_a = _setup_remote_repo(git_server, "svc-alpha", files={"a.txt": "a"})
        url_b = _setup_remote_repo(git_server, "svc-beta", files={"b.txt": "b"})
        url_c = _setup_remote_repo(git_server, "lib-gamma", files={"c.txt": "c"})
        manifest_content = _make_manifest_yaml(
            {"dest": "svc-alpha", "url": url_a},
            {"dest": "svc-beta", "url": url_b},
            {"dest": "lib-gamma", "url": url_c},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        result = _tsrc(["dump-manifest", "-i", "svc", "-p"], cwd=workspace)
        combined = result.stdout + result.stderr

        assert "svc-alpha" in combined
        assert "svc-beta" in combined
        lines = combined.split("\n")
        dest_lines = [l.strip() for l in lines if "dest:" in l]
        gamma_dests = [l for l in dest_lines if "lib-gamma" in l]
        assert (
            len(gamma_dests) == 0
        ), f"lib-gamma should not appear, found: {gamma_dests}"


# ===========================================================================
# STATUS DEEP: Tests exercising the display pipeline for tsrc status
# ===========================================================================


class TestStatusDeep:
    """Deep E2E tests for tsrc status, exercising the display pipeline:
    StatusCollector, GitStatus.describe, WorkspaceReposSummary, and
    StatusHeader."""

    def test_status_shows_branch_name_per_repo(self, workspace, git_server):
        """tsrc status output includes the branch name (e.g. 'master') for
        each repo in the workspace. The branch appears in the per-repo
        status line alongside the repo dest."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "alpha", "files": {"a.txt": "alpha content"}},
                {"dest": "beta", "files": {"b.txt": "beta content"}},
            ],
        )
        result = _tsrc(
            ["status"],
            cwd=workspace,
            env={"TSRC_PARALLEL_JOBS": "1"},
        )
        combined = result.stdout + result.stderr
        # Both repos should be listed
        assert "alpha" in combined
        assert "beta" in combined
        # Default branch is 'master', must appear in output
        assert "master" in combined

    def test_status_shows_ahead_count(self, workspace, git_server):
        """After adding local commits that are ahead of upstream, tsrc
        status shows the ahead count in its output using the up-arrow
        indicator."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "ahead_repo", "files": {"base.txt": "base"}},
            ],
        )
        repo_path = workspace / "ahead_repo"
        # Add 2 local commits ahead of upstream
        for i in range(2):
            (repo_path / f"local_{i}.txt").write_text(f"local {i}")
            _git(repo_path, "add", f"local_{i}.txt")
            _git(repo_path, "commit", "-m", f"local commit {i}")

        result = _tsrc(
            ["status"],
            cwd=workspace,
            env={"TSRC_PARALLEL_JOBS": "1"},
        )
        combined = result.stdout + result.stderr
        assert "ahead_repo" in combined
        # The ahead indicator is the up marker ('↑' unicode, '+' ascii
        # fallback) immediately followed by the count.
        assert "↑2" in combined or "+2" in combined

    def test_status_local_git_only(self, workspace, git_server):
        """tsrc status --local-git-only succeeds and shows repos without
        needing remote access. This exercises the StatusCollectorLocalOnly
        code path."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "local_repo", "files": {"l.txt": "local content"}},
            ],
        )
        result = _tsrc(
            ["status", "--local-git-only"],
            cwd=workspace,
            env={"TSRC_PARALLEL_JOBS": "1"},
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0
        assert "local_repo" in combined
        # Branch should still appear
        assert "master" in combined

    def test_status_wrong_branch_indicator(self, workspace, git_server):
        """When a repo is on a different branch than what the manifest
        specifies, tsrc status shows the expected branch indicator
        (e.g. 'expected: main')."""
        url = _setup_remote_repo(
            git_server,
            "wrongbr_repo",
            files={"m.txt": "main content"},
            branch="main",
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "wrongbr_repo", "url": url, "branch": "main"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        repo_path = workspace / "wrongbr_repo"
        # Switch to a feature branch locally
        _git(repo_path, "checkout", "-b", "feature-x")

        result = _tsrc(
            ["status"],
            cwd=workspace,
            env={"TSRC_PARALLEL_JOBS": "1"},
        )
        combined = result.stdout + result.stderr
        assert "wrongbr_repo" in combined
        # The wrong-branch state shows "(expected: main)"
        assert "expected: main" in combined

    def test_status_renders_distinct_per_repo_states(self, workspace, git_server):
        """A single `tsrc status` renders each repo's OWN state: a clean repo,
        a dirty repo, and an ahead-of-upstream repo are each annotated with
        their distinct marker on their own status line.

        Unlike test_status_shows_branch_name_per_repo (which only checks that
        every repo dest is enumerated) and the single-condition marker tests,
        this verifies status maps the right state to the right repo in one
        render -- the clean repo must NOT be marked dirty, the dirty repo must
        be, and the ahead repo must carry the ahead count."""
        _setup_workspace(
            git_server,
            workspace,
            [
                {"dest": "clean_svc", "files": {"c.txt": "clean"}},
                {"dest": "dirty_svc", "files": {"d.txt": "dirty"}},
                {"dest": "ahead_svc", "files": {"a.txt": "ahead"}},
            ],
        )
        # Dirty one repo with an untracked file.
        (workspace / "dirty_svc" / "junk.txt").write_text("uncommitted")
        # Put another repo ahead of upstream with a local commit.
        ahead_path = workspace / "ahead_svc"
        (ahead_path / "local.txt").write_text("local change")
        _git(ahead_path, "add", "local.txt")
        _git(ahead_path, "commit", "-m", "local ahead commit")

        result = _tsrc(["status"], cwd=workspace, env={"TSRC_PARALLEL_JOBS": "1"})
        combined = result.stdout + result.stderr
        lines = combined.split("\n")

        def _line_for(dest):
            matches = [ln for ln in lines if dest in ln]
            assert matches, f"Expected a status line for {dest}"
            return " ".join(matches)

        # The clean repo's line shows no dirty marker.
        assert "(dirty)" not in _line_for("clean_svc")
        # The dirty repo's line carries the dirty marker.
        assert "(dirty)" in _line_for("dirty_svc")
        # The ahead repo's line carries the ahead count (↑1 unicode / +1 ascii).
        ahead_line = _line_for("ahead_svc")
        assert "↑1" in ahead_line or "+1" in ahead_line

    def test_status_shows_manifest_branch_header(self, workspace, git_server):
        """tsrc status prints a header line showing the manifest branch.
        This exercises the StatusHeader.display() method which outputs
        'Manifest's branch: <branch>'."""
        url = _setup_remote_repo(git_server, "hdr_repo", files={"h.txt": "header"})
        manifest_content = _make_manifest_yaml(
            {"dest": "hdr_repo", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content, branch="develop")
        _tsrc(
            ["init", f"file://{manifest_path}", "--branch", "develop"],
            cwd=workspace,
        )

        result = _tsrc(
            ["status"],
            cwd=workspace,
            env={"TSRC_PARALLEL_JOBS": "1"},
        )
        combined = result.stdout + result.stderr
        # StatusHeader prints "Manifest's branch: develop"
        assert "develop" in combined


# ===========================================================================
# SYNC DEEP: Tests for complex sync orchestration logic
# ===========================================================================


class TestSyncDeep:
    """Deep E2E tests for tsrc sync exercising complex ref resolution,
    sync orchestration, config management, and error handling paths."""

    def test_sync_updates_config_when_manifest_url_changes(
        self, workspace, git_server, tmp_path
    ):
        """After init, if the manifest URL is changed in .tsrc/config.yml,
        sync should use the new manifest URL. This exercises the code path
        in workspace.update_manifest() where config.manifest_url drives
        which remote is pulled."""
        # Set up initial workspace with one repo
        url_a = _setup_remote_repo(
            git_server, "url_chg_repo", files={"a.txt": "original"}
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "url_chg_repo", "url": url_a},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        manifest_url = f"file://{manifest_path}"
        _tsrc(["init", manifest_url], cwd=workspace)

        # Create a SECOND manifest repo at a different path with a new repo
        url_b = _setup_remote_repo(
            git_server, "new_from_url2", files={"b.txt": "from_url2"}
        )
        manifest2_content = _make_manifest_yaml(
            {"dest": "url_chg_repo", "url": url_a},
            {"dest": "new_from_url2", "url": url_b},
        )
        manifest2_path = git_server / "manifest2"
        _create_manifest_repo(manifest2_path, manifest2_content)
        manifest2_url = f"file://{manifest2_path}"

        # Manually edit config.yml to point to the new manifest URL
        import ruamel.yaml

        config_path = workspace / ".tsrc" / "config.yml"
        yaml = ruamel.yaml.YAML(typ="rt")
        config = yaml.load(config_path.read_text())
        config["manifest_url"] = manifest2_url
        with config_path.open("w") as f:
            yaml.dump(config, f)

        # Sync should use the new manifest URL and clone new_from_url2
        _tsrc(["sync"], cwd=workspace)
        assert (
            workspace / "new_from_url2" / "b.txt"
        ).read_text() == "from_url2", (
            "Sync should clone repos from the new manifest URL"
        )
        # Original repo should still be present
        assert (workspace / "url_chg_repo" / "a.txt").read_text() == "original"

    def test_sync_with_repo_having_both_branch_and_sha1(self, workspace, git_server):
        """When a manifest entry has both branch and sha1, sync should
        reset to sha1 (sha1 takes precedence over branch). This exercises
        the sync_repo_to_ref -> sync_repo_to_ref_and_branch code path
        in syncer.py where orig_branch is set but sha1 drives the reset."""
        repo_path = git_server / "branch_sha1_repo"
        _create_git_repo(repo_path, files={"base.txt": "base"}, branch="main")
        first_sha = _git(repo_path, "rev-parse", "HEAD").stdout.strip()

        # Add more commits past the pinned sha1
        (repo_path / "after.txt").write_text("after pin")
        _git(repo_path, "add", "after.txt")
        _git(repo_path, "commit", "-m", "post-pin commit")

        url = f"file://{repo_path}"
        manifest_content = _make_manifest_yaml(
            {
                "dest": "branch_sha1_repo",
                "url": url,
                "branch": "main",
                "sha1": first_sha,
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Verify initial state: should be at sha1, not at branch HEAD
        ws_sha = _git(
            workspace / "branch_sha1_repo", "rev-parse", "HEAD"
        ).stdout.strip()
        assert ws_sha == first_sha
        assert (workspace / "branch_sha1_repo" / "base.txt").exists()
        assert not (workspace / "branch_sha1_repo" / "after.txt").exists()

        # Add even more commits to remote
        (repo_path / "later.txt").write_text("much later")
        _git(repo_path, "add", "later.txt")
        _git(repo_path, "commit", "-m", "much later commit")

        # Sync should fetch but still reset to pinned sha1
        _tsrc(["sync"], cwd=workspace)
        ws_sha_after = _git(
            workspace / "branch_sha1_repo", "rev-parse", "HEAD"
        ).stdout.strip()
        assert (
            ws_sha_after == first_sha
        ), "Sync should reset to pinned sha1 even with branch set"
        assert not (workspace / "branch_sha1_repo" / "after.txt").exists()
        assert not (workspace / "branch_sha1_repo" / "later.txt").exists()

    def test_sync_clones_missing_repo_with_correct_branch(self, workspace, git_server):
        """When a repo with branch=develop is added to the manifest after
        init, sync should clone it and check it out on the develop branch.
        This exercises the clone_missing -> Cloner -> clone_repo path where
        repo.branch is passed as --branch to git clone."""
        url_a = _setup_remote_repo(git_server, "existing_repo")
        manifest_content = _make_manifest_yaml(
            {"dest": "existing_repo", "url": url_a},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Create a new repo with a develop branch
        new_repo_path = git_server / "dev_repo"
        _create_git_repo(
            new_repo_path,
            files={"main.txt": "on main"},
            branch="main",
        )
        _git(new_repo_path, "checkout", "-b", "develop")
        (new_repo_path / "dev.txt").write_text("on develop")
        _git(new_repo_path, "add", "dev.txt")
        _git(new_repo_path, "commit", "-m", "develop commit")
        _git(new_repo_path, "checkout", "main")
        url_b = f"file://{new_repo_path}"

        # Update manifest to include the new repo with branch=develop
        updated_manifest = _make_manifest_yaml(
            {"dest": "existing_repo", "url": url_a},
            {"dest": "dev_repo", "url": url_b, "branch": "develop"},
        )
        (manifest_path / "manifest.yml").write_text(updated_manifest)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "add dev_repo with branch=develop")

        # Sync should clone dev_repo on the develop branch
        _tsrc(["sync"], cwd=workspace)

        assert (
            workspace / "dev_repo" / "dev.txt"
        ).exists(), "dev.txt should exist (only on develop branch)"
        branch = _git(
            workspace / "dev_repo", "rev-parse", "--abbrev-ref", "HEAD"
        ).stdout.strip()
        assert branch == "develop", f"Expected develop branch, got {branch}"

    def test_sync_fast_forwards_preserving_initial_commits(self, workspace, git_server):
        """When the remote has new commits on top of what the workspace has,
        sync should fast-forward the local branch, advancing HEAD to include
        both the original commit and the new remote commits. This exercises
        the merge --ff-only @{upstream} path in sync_repo_to_branch. After
        sync, all commits (initial and new) should be in the log and the
        working tree should reflect the latest state."""
        url = _setup_remote_repo(
            git_server,
            "ff_repo",
            files={"base.txt": "base content"},
            branch="main",
        )
        manifest_content = _make_manifest_yaml(
            {"dest": "ff_repo", "url": url, "branch": "main"},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Record the initial commit sha (this is what the workspace has)
        repo_path = workspace / "ff_repo"
        initial_sha = _git(repo_path, "rev-parse", "HEAD").stdout.strip()
        assert (repo_path / "base.txt").read_text() == "base content"

        # Add two new commits to the remote
        remote_path = git_server / "ff_repo"
        (remote_path / "second.txt").write_text("second commit data")
        _git(remote_path, "add", "second.txt")
        _git(remote_path, "commit", "-m", "second commit")
        second_sha = _git(remote_path, "rev-parse", "HEAD").stdout.strip()

        (remote_path / "third.txt").write_text("third commit data")
        _git(remote_path, "add", "third.txt")
        _git(remote_path, "commit", "-m", "third commit")
        third_sha = _git(remote_path, "rev-parse", "HEAD").stdout.strip()

        # Sync should fast-forward the local repo
        _tsrc(["sync"], cwd=workspace)

        # HEAD should now be at the latest remote commit
        head_sha = _git(repo_path, "rev-parse", "HEAD").stdout.strip()
        assert (
            head_sha == third_sha
        ), f"HEAD should be at third commit ({third_sha}), got {head_sha}"

        # All files should be present (initial + both new commits)
        assert (repo_path / "base.txt").read_text() == "base content"
        assert (repo_path / "second.txt").read_text() == "second commit data"
        assert (repo_path / "third.txt").read_text() == "third commit data"

        # The original commit should still be in the history
        log_output = _git(repo_path, "log", "--oneline").stdout
        assert (
            "initial commit" in log_output
        ), "Initial commit should be preserved in history after ff"
        assert "second commit" in log_output
        assert "third commit" in log_output

        # Verify it was a true fast-forward: initial_sha is ancestor of HEAD
        result = _git(
            repo_path,
            "merge-base",
            "--is-ancestor",
            initial_sha,
            "HEAD",
            check=False,
        )
        assert (
            result.returncode == 0
        ), "Initial commit should be an ancestor of HEAD after ff"

    def test_sync_no_update_config_preserves_groups(self, workspace, git_server):
        """tsrc sync --no-update-config leaves repo_groups in config.yml
        unchanged even when the manifest defines new or different groups.
        This exercises the update_config_repo_groups flag being False."""
        url_a = _setup_remote_repo(git_server, "nuc_repo_a")
        url_b = _setup_remote_repo(git_server, "nuc_repo_b")
        manifest_content = _make_manifest_yaml(
            {"dest": "nuc_repo_a", "url": url_a},
            {"dest": "nuc_repo_b", "url": url_b},
            groups={
                "original": {"repos": ["nuc_repo_a"]},
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(
            ["init", f"file://{manifest_path}", "-g", "original"],
            cwd=workspace,
        )

        # Read the initial config to record repo_groups
        import ruamel.yaml

        config_path = workspace / ".tsrc" / "config.yml"
        yaml = ruamel.yaml.YAML(typ="rt")
        config_before = yaml.load(config_path.read_text())
        groups_before = list(config_before.get("repo_groups", []))

        # Update manifest with different groups
        updated_manifest = _make_manifest_yaml(
            {"dest": "nuc_repo_a", "url": url_a},
            {"dest": "nuc_repo_b", "url": url_b},
            groups={
                "new_group": {"repos": ["nuc_repo_a", "nuc_repo_b"]},
            },
        )
        (manifest_path / "manifest.yml").write_text(updated_manifest)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "change groups to new_group")

        # Sync with --no-update-config
        _tsrc(
            ["sync", "--no-update-config"],
            cwd=workspace,
            check=False,
        )

        # Config should NOT be updated with new groups
        config_after = yaml.load(config_path.read_text())
        groups_after = list(config_after.get("repo_groups", []))
        assert (
            groups_after == groups_before
        ), f"Expected groups unchanged ({groups_before}), got {groups_after}"

    def test_sync_sets_up_new_remotes_on_existing_repos(self, workspace, git_server):
        """When a second remote is added to a repo's manifest entry after
        init (which only had a single url), sync should configure the new
        remote on the existing repo. This exercises workspace.set_remotes
        -> RemoteSetter -> add_remote."""
        repo_path = git_server / "remote_add_repo"
        _create_git_repo(repo_path, files={"r.txt": "remote"})
        url = f"file://{repo_path}"

        # Start with a simple url-based manifest (single remote named origin)
        manifest_content = _make_manifest_yaml(
            {"dest": "remote_add_repo", "url": url},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Verify initial state: only origin remote
        result = _git(workspace / "remote_add_repo", "remote", "-v")
        assert "origin" in result.stdout
        assert "upstream" not in result.stdout

        # Create a second "upstream" remote repo
        upstream_path = git_server / "remote_add_upstream"
        _create_git_repo(upstream_path, files={"r.txt": "remote"})
        upstream_url = f"file://{upstream_path}"

        # Update manifest to use remotes list with both origin and upstream
        updated_manifest = _make_manifest_yaml(
            {
                "dest": "remote_add_repo",
                "remotes": [
                    {"name": "origin", "url": url},
                    {"name": "upstream", "url": upstream_url},
                ],
            },
        )
        (manifest_path / "manifest.yml").write_text(updated_manifest)
        _git(manifest_path, "add", "manifest.yml")
        _git(manifest_path, "commit", "-m", "add upstream remote")

        # Sync should add the new upstream remote
        _tsrc(["sync"], cwd=workspace)

        # Verify both remotes are now configured
        result2 = _git(workspace / "remote_add_repo", "remote", "-v")
        assert "origin" in result2.stdout, "origin remote should still exist"
        assert "upstream" in result2.stdout, "upstream remote should be added by sync"

    def test_sync_recreates_deleted_symlink(self, workspace, git_server):
        """Sync re-runs filesystem operations (symlink) after updating repos.
        A symlink directive removed from the workspace should be re-created by
        the next sync. This exercises the symlink branch of
        workspace.perform_filesystem_operations, distinct from the copy branch."""
        url = _setup_remote_repo(
            git_server,
            "fslink_repo",
            files={"link_target.txt": "linked"},
        )
        target_path = str(workspace / "fslink_repo" / "link_target.txt")
        manifest_content = _make_manifest_yaml(
            {
                "dest": "fslink_repo",
                "url": url,
                "symlink": [{"source": "active_link.txt", "target": target_path}],
            },
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Verify initial symlink creation
        link_path = workspace / "active_link.txt"
        assert link_path.is_symlink()
        assert link_path.read_text() == "linked"

        # Delete the symlink, then sync should re-create it
        link_path.unlink()
        assert not link_path.exists()
        _tsrc(["sync"], cwd=workspace)

        assert link_path.is_symlink(), "sync should re-create the deleted symlink"
        assert link_path.read_text() == "linked"

    def test_sync_with_multiple_repos_where_one_fails(self, workspace, git_server):
        """When sync processes multiple repos and one fails (e.g., remote
        is unreachable), the other repos should still be synced. Sync
        reports a non-zero exit code but processes all repos. This exercises
        the executor's error collection in workspace.sync."""
        url_good = _setup_remote_repo(
            git_server, "good_repo", files={"good.txt": "good"}
        )
        url_bad = _setup_remote_repo(git_server, "bad_repo", files={"bad.txt": "bad"})
        manifest_content = _make_manifest_yaml(
            {"dest": "good_repo", "url": url_good},
            {"dest": "bad_repo", "url": url_bad},
        )
        manifest_path = git_server / "manifest"
        _create_manifest_repo(manifest_path, manifest_content)
        _tsrc(["init", f"file://{manifest_path}"], cwd=workspace)

        # Add new commits to both remote repos
        remote_good = git_server / "good_repo"
        (remote_good / "update.txt").write_text("updated")
        _git(remote_good, "add", "update.txt")
        _git(remote_good, "commit", "-m", "good update")

        remote_bad = git_server / "bad_repo"
        (remote_bad / "update.txt").write_text("updated")
        _git(remote_bad, "add", "update.txt")
        _git(remote_bad, "commit", "-m", "bad update")

        # Delete the bad repo's remote to make it unreachable
        import shutil

        shutil.rmtree(git_server / "bad_repo")

        # Sync should fail overall but still process good_repo
        result = _tsrc(
            ["sync", "--no-update-manifest"],
            cwd=workspace,
            check=False,
        )
        assert result.returncode != 0, "Sync should fail when a repo errors"

        # good_repo should still have been synced (update.txt present)
        assert (
            workspace / "good_repo" / "update.txt"
        ).read_text() == "updated", (
            "good_repo should be synced even when bad_repo fails"
        )

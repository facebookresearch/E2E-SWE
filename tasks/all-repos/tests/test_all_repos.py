"""End-to-end tests for the ``all-repos`` engine.

Each test exercises a user-facing capability the way a real user would: the
command-line tools are driven as installed console scripts (``all-repos-clone``,
``all-repos-grep`` ...) over real local git repositories, and the autofixer
framework is driven through its documented ``all_repos.autofix_lib`` API by
writing a small autofixer (exactly as the project documents for custom fixers).

The "remotes" are ordinary local git repositories created with
``receive.denyCurrentBranch=updateInstead`` so that a push updates their working
tree -- this is the standard way the project itself tests clone/autofix/push
without contacting any external git host.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(
        ['git', *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout


def revparse(path) -> str:
    return _git('-C', str(path), 'rev-parse', 'HEAD').strip()


def init_repo(path) -> str:
    p = str(path)
    subprocess.run(['git', 'init', p], check=True, capture_output=True)
    subprocess.run(['git', '-C', p, 'branch', '-m', 'main'],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', p, 'commit', '--allow-empty', '-m', 'init'],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', p, 'config',
                    'receive.denyCurrentBranch', 'updateInstead'],
                   check=True, capture_output=True)
    return revparse(p)


def write_file_commit(repo, name: str, contents: str) -> None:
    (Path(str(repo)) / name).write_text(contents)
    subprocess.run(['git', '-C', str(repo), 'add', '.'],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-m', name],
                   check=True, capture_output=True)


def merge_msgs(branch: str) -> set[str]:
    return {
        f"Merge branch '{branch}'",
        f"Merge branch '{branch}' into main",
    }


def write_config(tmp_path, repos_json, *,
                 push='all_repos.push.merge_to_master',
                 push_settings=None, **extra) -> Path:
    cfg = tmp_path / 'all-repos.json'
    data = {
        'output_dir': 'output',
        'source': 'all_repos.source.json_file',
        'source_settings': {'filename': str(repos_json)},
        'push': push,
        'push_settings': push_settings or {},
    }
    data.update(extra)
    cfg.write_text(json.dumps(data))
    cfg.chmod(0o600)
    return cfg


def run_cli(*args, input=None, env=None):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True, text=True, input=input, env=env,
    )


# autofixer driven through the documented all_repos.autofix_lib API
def _no_find_repos(config):
    return []


def lower_case_f():
    contents = Path('f').read_text()
    Path('f').write_text(contents.lower())


def noop_fix():
    pass


def failing_check():
    raise AssertionError('nope!')


def autofix_via_cli(cfg, repo_paths, apply_fix, *, extra_args=(),
                    check_fix=None, branch_name='test-branch', msg='message!'):
    import argparse

    from all_repos import autofix_lib

    parser = argparse.ArgumentParser()
    autofix_lib.add_fixer_args(parser)
    argv = ['-C', str(cfg), *extra_args,
            '--repos', *[str(p) for p in repo_paths]]
    args = parser.parse_args(argv)
    repos, config, commit, settings = autofix_lib.from_cli(
        args, find_repos=_no_find_repos, msg=msg, branch_name=branch_name,
    )
    kwargs = {'check_fix': check_fix} if check_fix is not None else {}
    autofix_lib.fix(
        repos, apply_fix=apply_fix, config=config, commit=commit,
        autofix_settings=settings, **kwargs,
    )


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def repos2(tmp_path):
    dir1 = tmp_path / 'src1'
    dir2 = tmp_path / 'src2'
    rev1 = init_repo(dir1)
    rev2 = init_repo(dir2)
    repos_json = tmp_path / 'repos.json'
    repos_json.write_text(json.dumps({'repo1': str(dir1), 'repo2': str(dir2)}))
    cfg = write_config(tmp_path, repos_json)
    return SimpleNamespace(
        tmp_path=tmp_path, dir1=dir1, dir2=dir2, rev1=rev1, rev2=rev2,
        repos_json=repos_json, cfg=cfg, output_dir=tmp_path / 'output',
    )


@pytest.fixture
def cloned(repos2):
    write_file_commit(repos2.dir1, 'f', 'OHAI\n')
    write_file_commit(repos2.dir2, 'f', 'OHELLO\n')
    write_file_commit(repos2.dir2, 'f2', '')
    r = run_cli('all-repos-clone', '-C', repos2.cfg)
    assert r.returncode == 0, r.stderr
    return repos2


# --------------------------------------------------------------------------- #
# clone
# --------------------------------------------------------------------------- #
def test_clone_creates_repos_and_metadata(repos2):
    """all-repos-clone clones every source repo at its current revision and
    writes repos.json, repos_filtered.json and the .all-repos marker."""
    r = run_cli('all-repos-clone', '-C', repos2.cfg)
    assert r.returncode == 0, r.stderr

    assert (repos2.output_dir / 'repo1').is_dir()
    assert (repos2.output_dir / 'repo2').is_dir()
    assert revparse(repos2.output_dir / 'repo1') == repos2.rev1
    assert revparse(repos2.output_dir / 'repo2') == repos2.rev2

    expected = {'repo1': str(repos2.dir1), 'repo2': str(repos2.dir2)}
    assert json.loads((repos2.output_dir / 'repos.json').read_text()) == expected
    filtered = json.loads(
        (repos2.output_dir / 'repos_filtered.json').read_text(),
    )
    assert filtered == expected
    assert (repos2.output_dir / '.all-repos').exists()


def test_clone_filters_and_sorts(repos2):
    """repos_filtered.json is sorted by name and respects include/exclude
    regexes; an excluded repo is removed from the output dir."""
    # reversed source order -> repos_filtered is sorted by key
    repos2.repos_json.write_text(
        json.dumps({'repo2': str(repos2.dir2), 'repo1': str(repos2.dir1)}),
    )
    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0
    filtered = json.loads(
        (repos2.output_dir / 'repos_filtered.json').read_text(),
    )
    assert list(filtered) == ['repo1', 'repo2']

    # exclude regex drops repo2 (and removes its directory)
    data = json.loads(repos2.cfg.read_text())
    data['exclude'] = 'repo2'
    repos2.cfg.write_text(json.dumps(data))
    repos2.cfg.chmod(0o600)
    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0
    filtered = json.loads(
        (repos2.output_dir / 'repos_filtered.json').read_text(),
    )
    assert filtered == {'repo1': str(repos2.dir1)}
    assert not (repos2.output_dir / 'repo2').exists()


def test_clone_updates_and_removes(repos2):
    """Re-running clone fast-forwards existing repos, removes repos dropped
    from the source, and cleans up the now-empty parent directories."""
    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0

    # upstream advances -> clone updates the local checkout
    subprocess.run(
        ['git', '-C', str(repos2.dir1), 'commit', '--allow-empty', '-m', 'm'],
        check=True, capture_output=True,
    )
    new_rev = revparse(repos2.dir1)
    assert new_rev != repos2.rev1
    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0
    assert revparse(repos2.output_dir / 'repo1') == new_rev

    # dropping repo2 removes its directory
    repos2.repos_json.write_text(json.dumps({'repo1': str(repos2.dir1)}))
    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0
    assert not (repos2.output_dir / 'repo2').exists()
    assert (repos2.output_dir / 'repo1').is_dir()

    # a nested repo, once dropped, has its empty parent dirs cleaned up
    repos2.repos_json.write_text(json.dumps({
        'repo1': str(repos2.dir1),
        'nested/deep/repo3': str(repos2.dir2),
    }))
    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0
    assert (repos2.output_dir / 'nested/deep/repo3').is_dir()
    repos2.repos_json.write_text(json.dumps({'repo1': str(repos2.dir1)}))
    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0
    assert not (repos2.output_dir / 'nested/deep/repo3').exists()
    assert not (repos2.output_dir / 'nested').exists()


def test_clone_continues_on_unclonable(repos2):
    """An unreachable repo prints 'Error fetching <path>' but does not abort the
    run; reachable repos are still cloned."""
    repos2.repos_json.write_text(json.dumps({
        'good': str(repos2.dir1),
        'bad': '/does/not/exist',
    }))
    r = run_cli('all-repos-clone', '-C', repos2.cfg)
    assert r.returncode == 0
    assert 'Error fetching ' in r.stdout
    assert (repos2.output_dir / 'good').is_dir()
    assert revparse(repos2.output_dir / 'good') == repos2.rev1


def test_clone_all_branches(repos2):
    """By default only the default branch is fetched; with all_branches=True all
    branches become available as remote refs."""
    subprocess.run(['git', '-C', str(repos2.dir1), 'branch', 'feature'],
                   check=True, capture_output=True)

    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0
    refs = _git('-C', str(repos2.output_dir / 'repo1'), 'branch', '-r')
    assert 'origin/feature' not in refs

    data = json.loads(repos2.cfg.read_text())
    data['all_branches'] = True
    repos2.cfg.write_text(json.dumps(data))
    repos2.cfg.chmod(0o600)
    assert run_cli('all-repos-clone', '-C', repos2.cfg).returncode == 0
    refs = _git('-C', str(repos2.output_dir / 'repo1'), 'branch', '-r')
    assert 'origin/feature' in refs


# --------------------------------------------------------------------------- #
# config validation
# --------------------------------------------------------------------------- #
def test_config_validation_errors(repos2):
    """A too-permissive config file and an output dir holding unexpected files
    both fail with the documented error messages."""
    repos2.cfg.chmod(0o777)
    r = run_cli('all-repos-clone', '-C', repos2.cfg)
    assert r.returncode != 0
    assert (
        f'{repos2.cfg} has too-permissive permissions, '
        f'Expected 0o600, got 0o777'
    ) in r.stderr

    repos2.cfg.chmod(0o600)
    repos2.output_dir.mkdir(parents=True, exist_ok=True)
    (repos2.output_dir / 'stray.txt').write_text('')
    r = run_cli('all-repos-clone', '-C', repos2.cfg)
    assert r.returncode != 0
    assert (
        'output_dir should only contain repos.json, repos_filtered.json, '
        'and directories'
    ) in r.stderr


# --------------------------------------------------------------------------- #
# query commands
# --------------------------------------------------------------------------- #
def test_find_files_cli(cloned):
    """all-repos-find-files matches filenames by python regex, with
    --output-paths, --repos-with-matches and a non-zero exit on no match."""
    out = cloned.output_dir
    r = run_cli('all-repos-find-files', '-C', cloned.cfg, '--color=never', r'\d')
    assert r.returncode == 0
    assert r.stdout == f'{out / "repo2"}:f2\n'

    r = run_cli('all-repos-find-files', '-C', cloned.cfg, '--color=never',
                '--output-paths', r'\d')
    assert r.returncode == 0
    assert r.stdout == f'{out / "repo2" / "f2"}\n'

    r = run_cli('all-repos-find-files', '-C', cloned.cfg, '--color=never',
                '--repos-with-matches', r'\d')
    assert r.returncode == 0
    assert r.stdout == f'{out / "repo2"}\n'

    r = run_cli('all-repos-find-files', '-C', cloned.cfg, '--color=never', 'zzz')
    assert r.returncode != 0
    assert r.stdout == ''


def test_grep_cli(cloned):
    """all-repos-grep prints sorted repo:line matches, supports
    --repos-with-matches and pass-through git-grep options, returns 1 on no
    match and propagates git's exit 128 when no pattern is given."""
    out = cloned.output_dir
    r = run_cli('all-repos-grep', '-C', cloned.cfg, '--color=never', '^OH')
    assert r.returncode == 0
    assert r.stdout == (
        f'{out / "repo1"}:f:OHAI\n'
        f'{out / "repo2"}:f:OHELLO\n'
    )

    r = run_cli('all-repos-grep', '-C', cloned.cfg, '--color=never',
                '--repos-with-matches', '^OH')
    assert r.returncode == 0
    assert r.stdout == f'{out / "repo1"}\n{out / "repo2"}\n'

    # pass-through git grep option (-l) + path separator
    r = run_cli('all-repos-grep', '-C', cloned.cfg, '--color=never',
                '--output-paths', '-l', '^OH')
    assert r.returncode == 0
    assert r.stdout == f'{out / "repo1" / "f"}\n{out / "repo2" / "f"}\n'

    r = run_cli('all-repos-grep', '-C', cloned.cfg, '--color=never', 'zzzz')
    assert r.returncode == 1
    assert r.stdout == ''

    r = run_cli('all-repos-grep', '-C', cloned.cfg, '--color=never')
    assert r.returncode == 128


def test_list_repos_cli(cloned):
    """all-repos-list-repos prints cloned repo names, or full paths with
    --output-paths."""
    r = run_cli('all-repos-list-repos', '-C', cloned.cfg)
    assert r.returncode == 0
    assert r.stdout == 'repo1\nrepo2\n'

    r = run_cli('all-repos-list-repos', '-C', cloned.cfg, '--output-paths')
    assert r.returncode == 0
    assert r.stdout == (
        f'{cloned.output_dir / "repo1"}\n'
        f'{cloned.output_dir / "repo2"}\n'
    )


# --------------------------------------------------------------------------- #
# autofix framework
# --------------------------------------------------------------------------- #
def test_autofix_applies_commits_and_pushes(cloned):
    """A custom autofixer edits each repo, commits with the documented message
    footer + author on the all-repos_autofix_<branch> branch, and
    merge_to_master pushes the change back to the source repo's default
    branch."""
    autofix_via_cli(
        cloned.cfg,
        [cloned.output_dir / 'repo1', cloned.output_dir / 'repo2'],
        lower_case_f,
        extra_args=['--author', 'A B <a@a.a>'],
    )

    assert (cloned.dir1 / 'f').read_text() == 'ohai\n'
    assert (cloned.dir2 / 'f').read_text() == 'ohello\n'

    # the merge landed on the default branch via merge_to_master
    last = _git('-C', str(cloned.dir1), 'log',
                '--format=%s', '--first-parent', '-1').strip()
    assert last in merge_msgs('all-repos_autofix_test-branch')

    # the autofix commit carries the author and exact message footer
    commit = _git('-C', str(cloned.dir1), 'log', '--patch',
                  '--grep', 'message!', '--format=%an %ae\n%B')
    assert commit.startswith(
        'A B a@a.a\n'
        'message!\n'
        '\n'
        'Committed via https://github.com/asottile/all-repos\n',
    )
    assert commit.endswith('-OHAI\n+ohai\n')


def test_autofix_dry_run_shows_diff_without_committing(cloned, capfd):
    """--dry-run prints the would-be diff (and echoes each git command) but
    leaves the source repositories untouched; the readonly push is a no-op."""
    cfg = write_config(cloned.tmp_path, cloned.repos_json,
                       push='all_repos.push.readonly')
    rev1 = revparse(cloned.dir1)
    autofix_via_cli(
        cfg,
        [cloned.output_dir / 'repo1', cloned.output_dir / 'repo2'],
        lower_case_f,
        extra_args=['--dry-run'],
    )
    out, _ = capfd.readouterr()
    assert '-OHAI\n+ohai\n' in out
    assert '-OHELLO\n+ohello\n' in out
    assert '$ git ' in out  # autofix_lib.run echoes the commands it runs

    assert (cloned.dir1 / 'f').read_text() == 'OHAI\n'
    assert revparse(cloned.dir1) == rev1


def test_autofix_limit_processes_subset(cloned, capfd):
    """--limit caps how many repositories are processed."""
    autofix_via_cli(
        cloned.cfg,
        [cloned.output_dir / 'repo1', cloned.output_dir / 'repo2'],
        lower_case_f,
        extra_args=['--limit', '1', '--dry-run'],
    )
    out, _ = capfd.readouterr()
    assert '-OHAI\n+ohai\n' in out
    assert '-OHELLO\n+ohello\n' not in out


def test_autofix_failing_check_blocks_commit(cloned, capfd):
    """If check_fix raises, the repository is marked errored and no change is
    committed."""
    autofix_via_cli(
        cloned.cfg,
        [cloned.output_dir / 'repo1', cloned.output_dir / 'repo2'],
        lower_case_f,
        check_fix=failing_check,
    )
    out, _ = capfd.readouterr()
    # both repos are reported as errored and neither change is committed
    assert out.count('Errored') == 2
    assert (cloned.dir1 / 'f').read_text() == 'OHAI\n'
    assert (cloned.dir2 / 'f').read_text() == 'OHELLO\n'


def test_autofix_interactive_approve_deny(cloned):
    """In interactive mode answering yes commits one repo and no skips the
    other."""
    from unittest import mock

    # Feed the y/n answers over stdin (like the manual autofixer test) rather
    # than pinning the read primitive: this exercises any faithful prompt,
    # whether it calls input() or sys.stdin.readline().
    with mock.patch.object(sys, 'stdin', io.StringIO('y\nn\n')):
        autofix_via_cli(
            cloned.cfg,
            [cloned.output_dir / 'repo1', cloned.output_dir / 'repo2'],
            lower_case_f,
            extra_args=['-i'],
        )
    assert (cloned.dir1 / 'f').read_text() == 'ohai\n'
    assert (cloned.dir2 / 'f').read_text() == 'OHELLO\n'


def test_autofix_noop_makes_no_commit(cloned):
    """An autofixer that changes nothing produces no commit even with a push
    configured."""
    rev1, rev2 = revparse(cloned.dir1), revparse(cloned.dir2)
    autofix_via_cli(
        cloned.cfg,
        [cloned.output_dir / 'repo1', cloned.output_dir / 'repo2'],
        noop_fix,
    )
    assert revparse(cloned.dir1) == rev1
    assert revparse(cloned.dir2) == rev2


# --------------------------------------------------------------------------- #
# sed autofixer
# --------------------------------------------------------------------------- #
def test_sed_replaces_text_and_commits(cloned):
    """all-repos-sed runs sed over matching files and commits the result;
    repos with no match are untouched and non-text entries are ignored."""
    (cloned.dir1 / 'link').symlink_to('nonexistent')
    subprocess.run(['git', '-C', str(cloned.dir1), 'add', '.'],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', str(cloned.dir1), 'commit', '-m', 'link'],
                   check=True, capture_output=True)
    run_cli('all-repos-clone', '-C', cloned.cfg)

    before = revparse(cloned.dir1)
    r = run_cli('all-repos-sed', '-C', cloned.cfg, 's/HAI/BAI/g', '*')
    assert r.returncode == 0
    assert (cloned.dir1 / 'f').read_text() == 'OBAI\n'
    assert (cloned.dir2 / 'f').read_text() == 'OHELLO\n'
    assert revparse(cloned.dir1) != before


def test_sed_custom_glob_and_extended_regex(cloned):
    """all-repos-sed restricts edits to the filename glob and honours -r
    (extended regexes)."""
    write_file_commit(cloned.dir1, 'g', 'OHAI\n')
    run_cli('all-repos-clone', '-C', cloned.cfg)

    r = run_cli('all-repos-sed', '-C', cloned.cfg, 's/AI/IE/g', 'g')
    assert r.returncode == 0
    assert (cloned.dir1 / 'g').read_text() == 'OHIE\n'
    assert (cloned.dir1 / 'f').read_text() == 'OHAI\n'  # glob was 'g' only

    r = run_cli('all-repos-sed', '-C', cloned.cfg, '-r', 's/H(A)I/BAI/g', '*')
    assert r.returncode == 0
    assert (cloned.dir1 / 'f').read_text() == 'OBAI\n'


# --------------------------------------------------------------------------- #
# manual autofixer
# --------------------------------------------------------------------------- #
def test_manual_interactive_edit_and_commit(cloned, tmp_path):
    """all-repos-manual runs $SHELL as the edit step under interactive mode:
    the approved repo is committed, the denied one is left alone, and
    --commit-msg is required."""
    editor = tmp_path / 'editor.sh'
    editor.write_text('#!/bin/sh\nprintf "manual\\n" >> f\n')
    editor.chmod(0o755)
    env = {**os.environ, 'SHELL': str(editor)}

    r = run_cli(
        'all-repos-manual', '-C', cloned.cfg,
        '--branch-name', 'manual-test', '--commit-msg', 'manual edit',
        '--repos',
        cloned.output_dir / 'repo1', cloned.output_dir / 'repo2',
        input='y\nn\n', env=env,
    )
    assert r.returncode == 0, r.stderr
    assert (cloned.dir1 / 'f').read_text() == 'OHAI\nmanual\n'
    assert (cloned.dir2 / 'f').read_text() == 'OHELLO\n'

    # --commit-msg is required
    r = run_cli('all-repos-manual', '-C', cloned.cfg,
                '--repos', cloned.output_dir / 'repo1')
    assert r.returncode != 0


# --------------------------------------------------------------------------- #
# completion
# --------------------------------------------------------------------------- #
def test_complete_bash_and_zsh(cloned):
    """all-repos-complete emits a shell completion script that points at the
    repos_filtered.json path for both --bash and --zsh."""
    marker = f'__all_repos__repos_json={cloned.output_dir / "repos_filtered.json"}'
    r = run_cli('all-repos-complete', '-C', cloned.cfg, '--bash')
    assert r.returncode == 0
    assert marker in r.stdout
    assert 'git clone' in r.stdout

    r = run_cli('all-repos-complete', '-C', cloned.cfg, '--zsh')
    assert r.returncode == 0
    assert marker in r.stdout


# --------------------------------------------------------------------------- #
# external source adapters (github / gitlab) — exercised against a local HTTP
# server so the test contacts no real git host. The source's base_url is
# pointed at the local server; proxies are disabled so 127.0.0.1 is reached
# directly.
# --------------------------------------------------------------------------- #
import contextlib  # noqa: E402
import http.server  # noqa: E402
import threading  # noqa: E402


class _RouteHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        matches = [p for p in self.server.routes if path == p or path.startswith(p)]
        if not matches:
            self.send_response(404)
            self.end_headers()
            return
        body, link = self.server.routes[max(matches, key=len)]
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        if link is not None:
            self.send_header('Link', link)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def http_source_server(build_routes):
    """Serve JSON routes on a local port; yield the base_url. build_routes(base)
    returns {path_prefix: (body_bytes, link_header_or_None)}."""
    server = http.server.HTTPServer(('127.0.0.1', 0), _RouteHandler)
    base = f'http://127.0.0.1:{server.server_address[1]}'
    server.routes = build_routes(base)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy_vars = (
        'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
        'ALL_PROXY', 'all_proxy', 'no_proxy', 'NO_PROXY',
    )
    saved = {k: os.environ.get(k) for k in proxy_vars}
    for k in proxy_vars:
        os.environ.pop(k, None)
    os.environ['no_proxy'] = os.environ['NO_PROXY'] = '*'
    try:
        yield base
    finally:
        for k in proxy_vars:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]
        server.shutdown()


def _gh_repo(full_name, *, fork=False, private=False, admin=True, archived=False):
    return {
        'full_name': full_name,
        'ssh_url': f'git@github.com:{full_name}.git',
        'fork': fork, 'private': private, 'archived': archived,
        'permissions': {'admin': admin},
    }


def test_source_github_filter_matrix():
    """The github source returns full_name -> ssh_url, filtered by the
    forks / private / collaborator / archived flags (a non-owned repo is one
    where the admin permission is false)."""
    from all_repos.source import github

    repos = [
        _gh_repo('me/public'),
        _gh_repo('me/forked', fork=True),
        _gh_repo('me/secret', private=True),
        _gh_repo('org/contrib', admin=False),
        _gh_repo('me/archived', archived=True),
    ]

    def routes(base):
        return {'/user/repos': (json.dumps(repos).encode(), None)}

    cases = [
        ({}, {'me/public'}),
        ({'collaborator': True}, {'me/public', 'org/contrib'}),
        ({'forks': True}, {'me/public', 'me/forked'}),
        ({'private': True}, {'me/public', 'me/secret'}),
        ({'archived': True}, {'me/public', 'me/archived'}),
    ]
    with http_source_server(routes) as base:
        for extra, expected in cases:
            settings = github.Settings(
                username='u', api_key='k', base_url=base, **extra,
            )
            assert set(github.list_repos(settings)) == expected


def test_source_github_pagination_and_mapping():
    """The github source follows the Link rel="next" header across pages and
    maps full_name -> ssh_url with any trailing `.git` stripped."""
    from all_repos.source import github

    page1 = [_gh_repo('me/one'), _gh_repo('me/two')]
    page2 = [_gh_repo('me/three')]

    def routes(base):
        return {
            '/user/repos': (
                json.dumps(page1).encode(), f'<{base}/__next__>; rel="next"',
            ),
            '/__next__': (json.dumps(page2).encode(), None),
        }

    with http_source_server(routes) as base:
        ret = github.list_repos(
            github.Settings(username='u', api_key='k', base_url=base),
        )
    assert ret == {
        'me/one': 'git@github.com:me/one',
        'me/two': 'git@github.com:me/two',
        'me/three': 'git@github.com:me/three',
    }


def test_source_github_api_key_env(monkeypatch):
    """The github source resolves the token from api_key_env, and requires
    exactly one of api_key / api_key_env (else ValueError)."""
    from all_repos.source import github

    def routes(base):
        return {'/user/repos': (json.dumps([_gh_repo('me/x')]).encode(), None)}

    with http_source_server(routes) as base:
        monkeypatch.setenv('GH_TOKEN', 'secret')
        ok = github.Settings(username='u', api_key_env='GH_TOKEN', base_url=base)
        assert set(github.list_repos(ok)) == {'me/x'}

        neither = github.Settings(username='u', base_url=base)
        with pytest.raises(ValueError):
            github.list_repos(neither)


def test_source_gitlab_org():
    """The gitlab_org source maps path_with_namespace -> ssh_url_to_repo, drops
    archived projects unless archived=True, and follows pagination."""
    from all_repos.source import gitlab_org

    def _gl(path, *, archived=False):
        return {
            'path_with_namespace': path,
            'ssh_url_to_repo': f'git@gitlab.com:{path}.git',
            'archived': archived,
        }

    page1 = [_gl('grp/a'), _gl('grp/old', archived=True)]
    page2 = [_gl('grp/sub/b')]

    def routes(base):
        return {
            '/groups': (
                json.dumps(page1).encode(), f'<{base}/__next__>; rel="next"',
            ),
            '/__next__': (json.dumps(page2).encode(), None),
        }

    with http_source_server(routes) as base:
        ret = gitlab_org.list_repos(
            gitlab_org.Settings(org='grp', api_key='k', base_url=base),
        )
        assert ret == {
            'grp/a': 'git@gitlab.com:grp/a.git',
            'grp/sub/b': 'git@gitlab.com:grp/sub/b.git',
        }
        with_archived = gitlab_org.list_repos(
            gitlab_org.Settings(
                org='grp', api_key='k', base_url=base, archived=True,
            ),
        )
        assert set(with_archived) == {'grp/a', 'grp/old', 'grp/sub/b'}


# --------------------------------------------------------------------------- #
# pull-request push modules (github / gitlab) — the push branch is sent to a
# local git remote and the create-PR request hits a local HTTP server that
# records the POST body.
# --------------------------------------------------------------------------- #
class _ApiHandler(http.server.BaseHTTPRequestHandler):
    def _handle(self, method):
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length).decode() if length else ''
        self.server.recorded.append(
            {'method': method, 'path': self.path, 'body': body},
        )
        path = self.path.split('?', 1)[0]
        matches = [p for p in self.server.responses if path == p or path.startswith(p)]
        if not matches:
            self.send_response(404)
            self.end_headers()
            return
        payload = self.server.responses[max(matches, key=len)]
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def http_api_server(build_responses):
    """Serve (and record) JSON API requests on a local port; yield
    (base_url, recorded_requests)."""
    server = http.server.HTTPServer(('127.0.0.1', 0), _ApiHandler)
    base = f'http://127.0.0.1:{server.server_address[1]}'
    server.responses = build_responses(base)
    server.recorded = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy_vars = (
        'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
        'ALL_PROXY', 'all_proxy', 'no_proxy', 'NO_PROXY',
    )
    saved = {k: os.environ.get(k) for k in proxy_vars}
    for k in proxy_vars:
        os.environ.pop(k, None)
    os.environ['no_proxy'] = os.environ['NO_PROXY'] = '*'
    try:
        yield base, server.recorded
    finally:
        for k in proxy_vars:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]
        server.shutdown()


@contextlib.contextmanager
def _chdir(path):
    old = os.getcwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(old)


def _pr_repo(tmp_path, slug='user/slug'):
    """Make a local 'remote' whose path ends with :<slug> plus a working clone
    on a 'feature' branch with one commit ('Title' / 'Body line')."""
    src = tmp_path / f'repo:{slug}'
    init_repo(src)
    dest = tmp_path / 'dest'
    subprocess.run(['git', 'clone', str(src), str(dest)],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', str(dest), 'checkout', 'origin/HEAD', '-b', 'feature'],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', str(dest), 'commit', '--allow-empty',
                    '-m', 'Title\n\nBody line'], check=True, capture_output=True)
    return src, dest


def test_push_github_pull_request(tmp_path):
    """github_pull_request pushes the branch to origin and POSTs a create-PR
    request with the commit subject/body, base, head and draft fields."""
    from all_repos.push import github_pull_request

    src, dest = _pr_repo(tmp_path)

    def responses(base):
        return {'/repos/user/slug/pulls': json.dumps({'html_url': 'http://pr/1'}).encode()}

    with http_api_server(responses) as (base, reqs):
        with _chdir(dest):
            github_pull_request.push(
                github_pull_request.Settings(username='user', api_key='k', base_url=base),
                'feature',
            )
    assert 'feature' in _git('-C', str(src), 'branch')  # pushed to origin
    posts = [r for r in reqs if r['method'] == 'POST']
    assert len(posts) == 1
    assert posts[0]['path'] == '/repos/user/slug/pulls'
    assert json.loads(posts[0]['body']) == {
        'title': 'Title', 'body': 'Body line',
        'base': 'main', 'head': 'feature', 'draft': False,
    }


def test_push_gitlab_pull_request(tmp_path):
    """gitlab_pull_request pushes the branch and POSTs a merge-request to the
    url-escaped project slug with source/target branch + title/description."""
    from all_repos.push import gitlab_pull_request

    src, dest = _pr_repo(tmp_path)

    def responses(base):
        return {'/projects': json.dumps({'web_url': 'http://mr/1'}).encode()}

    with http_api_server(responses) as (base, reqs):
        with _chdir(dest):
            gitlab_pull_request.push(
                gitlab_pull_request.Settings(api_key='k', base_url=base),
                'feature',
            )
    assert 'feature' in _git('-C', str(src), 'branch')
    posts = [r for r in reqs if r['method'] == 'POST']
    assert len(posts) == 1
    assert 'user%2Fslug' in posts[0]['path']  # url-escaped slug
    assert posts[0]['path'].endswith('/merge_requests')
    assert json.loads(posts[0]['body']) == {
        'source_branch': 'feature', 'target_branch': 'main',
        'title': 'Title', 'description': 'Body line',
        'remove_source_branch': True,
    }


def test_push_github_pull_request_fork(tmp_path):
    """With fork=True, github_pull_request forks (POST /forks), pushes the
    branch to the fork remote (not origin), and opens the PR with a
    namespaced head."""
    from all_repos.push import github_pull_request

    src, dest = _pr_repo(tmp_path)
    fork = tmp_path / 'repo:u2/slug'  # the fork remote (origin path with slug swapped)
    subprocess.run(['git', 'clone', str(src), str(fork)],
                   check=True, capture_output=True)

    def responses(base):
        return {
            '/repos/user/slug/forks': json.dumps({'full_name': 'u2/slug'}).encode(),
            '/repos/user/slug/pulls': json.dumps({'html_url': 'http://pr/2'}).encode(),
        }

    with http_api_server(responses) as (base, reqs):
        with _chdir(dest):
            github_pull_request.push(
                github_pull_request.Settings(
                    username='u2', api_key='k', base_url=base, fork=True,
                ),
                'feature',
            )
    assert 'feature' in _git('-C', str(fork), 'branch')      # pushed to the fork
    assert 'feature' not in _git('-C', str(src), 'branch')   # not to origin
    posts = {r['path'] for r in reqs if r['method'] == 'POST'}
    assert '/repos/user/slug/forks' in posts
    assert '/repos/user/slug/pulls' in posts
    pulls = [r for r in reqs if r['path'] == '/repos/user/slug/pulls'][0]
    assert json.loads(pulls['body'])['head'] == 'u2:feature'

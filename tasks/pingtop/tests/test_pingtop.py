"""Tests for pingtop, a multi-host ICMP ping monitor with a Textual TUI.

Each test exercises a distinct user-facing behavior through the public API:
the data/statistics models, the session manager, the exit summary, snapshot
exporters, the trend visualizations, the Click CLI, the Textual app shell, and
the ICMP engine's resolution contract.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner
from rich.text import Text
from textual.widgets import Button, DataTable, Input

from pingtop import cli
from pingtop.exporters import export_snapshot
from pingtop.models import (
    MAX_HISTORY,
    TIMEOUT_MARKER,
    TREND_BLOCKS,
    ExportFormat,
    HostState,
    HostStats,
    PingResult,
    SessionConfig,
    SortKey,
    build_trend,
    trend_cells,
)
from pingtop.session import PingSession, infer_export_format
from pingtop.summary import render_summary

# pingtop.app, pingtop.engine.icmp, and the pingtop.widgets.* modules are imported
# lazily inside the individual tests that use them. An implementation may legitimately
# organise the TUI/engine internals into different modules than the reference repo;
# importing those internal paths at module scope would turn one missing module into a
# whole-suite collection error instead of a single failing test.

WHEN = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def build_session(*targets: str) -> PingSession:
    """Construct a session with default config and the given targets."""
    return PingSession(SessionConfig(), targets)


class TestHostStats:
    """Per-host statistics accumulation, reset, and serialization."""

    def test_success_sequence_computes_rtt_statistics(self) -> None:
        """Three successful replies populate seq, last/min/max/avg/stddev, resolved IP,
        a non-empty trend, and a RUNNING state."""
        stats = HostStats()
        for rtt in (10.0, 20.0, 30.0):
            stats.register_success(rtt, "1.1.1.1", WHEN)

        assert stats.seq == 3
        assert stats.lost == 0
        assert stats.last_rtt_ms == 30.0
        assert stats.min_rtt_ms == 10.0
        assert stats.max_rtt_ms == 30.0
        assert stats.avg_rtt_ms == 20.0
        assert stats.stddev_ms == 10.0
        assert stats.loss_percent == 0.0
        assert stats.resolved_ip == "1.1.1.1"
        assert stats.state.value == "running"
        assert stats.history_ms == [10.0, 20.0, 30.0]
        assert stats.trend != ""

    def test_timeout_and_error_tracking(self) -> None:
        """A success/timeout/success sequence tracks loss, keeps the first resolved IP,
        and a later error flips to ERROR without advancing the sequence counter."""
        stats = HostStats()
        stats.register_success(10.0, "1.1.1.1", WHEN)
        stats.register_timeout(WHEN)
        stats.register_success(20.0, None, WHEN)

        assert stats.seq == 3
        assert stats.lost == 1
        assert stats.last_rtt_ms == 20.0
        assert stats.avg_rtt_ms == 15.0
        assert stats.min_rtt_ms == 10.0
        assert stats.max_rtt_ms == 20.0
        assert stats.loss_percent == pytest.approx(100 / 3)
        assert stats.resolved_ip == "1.1.1.1"
        assert stats.history_ms == [10.0, None, 20.0]
        assert stats.last_error is None

        stats.register_error("network unreachable", WHEN)
        assert stats.state.value == "error"
        assert stats.last_error == "network unreachable"
        assert stats.seq == 3

    def test_reset_clears_statistics(self) -> None:
        """reset() returns every counter to its initial state and clears history/trend."""
        stats = HostStats()
        stats.register_success(12.0, "1.1.1.1", WHEN)
        stats.register_timeout(WHEN)

        stats.reset()

        assert stats.seq == 0
        assert stats.lost == 0
        assert stats.loss_percent == 0.0
        assert stats.last_rtt_ms is None
        assert stats.avg_rtt_ms is None
        assert stats.history_ms == []
        assert stats.trend == ""
        assert stats.last_error is None
        assert stats.state.value == "pending"

    def test_snapshot_serializes_state_and_timestamp(self) -> None:
        """snapshot() emits the state as its string value and the timestamp as an
        ISO-8601 UTC string (None before any update)."""
        fresh = HostStats().snapshot()
        assert fresh["state"] == "pending"
        assert fresh["last_updated_at"] is None

        stats = HostStats()
        stats.register_success(12.5, "1.1.1.1", WHEN)
        snap = stats.snapshot()
        assert snap["state"] == "running"
        assert snap["seq"] == 1
        assert snap["last_rtt_ms"] == 12.5
        assert snap["resolved_ip"] == "1.1.1.1"
        assert snap["last_updated_at"] == "2026-01-01T12:00:00+00:00"
        assert snap["history_ms"] == [12.5]

    def test_history_is_capped_at_max_history(self) -> None:
        """History never grows beyond MAX_HISTORY even as the sequence count rises."""
        stats = HostStats()
        for index in range(MAX_HISTORY + 10):
            stats.register_success(float(index), "1.1.1.1", WHEN)

        assert stats.seq == MAX_HISTORY + 10
        assert len(stats.history_ms) == MAX_HISTORY

    def test_state_transition_helpers(self) -> None:
        """mark_paused / mark_pending / mark_deleted move the host into the matching
        lifecycle state, and the deleted state serializes in the snapshot."""
        stats = HostStats()
        stats.mark_paused()
        assert stats.state is HostState.PAUSED
        stats.mark_pending()
        assert stats.state is HostState.PENDING
        stats.mark_deleted()
        assert stats.state is HostState.DELETED
        assert stats.snapshot()["state"] == "deleted"


class TestTrendModel:
    """Sparkline trend computation in the model layer."""

    def test_trend_computation_buckets_and_timeout_marker(self) -> None:
        """trend_cells maps samples to bucketed unicode blocks (low->high) and marks
        timeouts; build_trend joins the block characters."""
        assert trend_cells([]) == []
        assert trend_cells([None, None]) == [
            (TIMEOUT_MARKER, None),
            (TIMEOUT_MARKER, None),
        ]

        cells = trend_cells([10.0, 20.0])
        assert cells[0][1] == 0
        assert cells[-1][1] == len(TREND_BLOCKS) - 1

        # A single distinct value lands every sample in the lowest bucket.
        assert all(bucket == 0 for _, bucket in trend_cells([5.0, 5.0, 5.0]))

        trend = build_trend([10.0, 15.0, 30.0, None])
        assert len(trend) == 4
        assert trend.endswith(TIMEOUT_MARKER)
        assert all(char in TREND_BLOCKS for char in trend[:-1])
        assert build_trend([]) == ""


class TestPingSession:
    """The session manager: host lifecycle, result application, sorting, aggregates."""

    def test_add_edit_delete_select_lifecycle(self) -> None:
        """Adding, editing (which resets stats), selecting, and deleting hosts updates
        membership and selection; duplicates are rejected case-insensitively."""
        session = build_session("1.1.1.1")
        first_id = next(iter(session.hosts))

        added_id = session.add_host("example.com")
        assert added_id in session.hosts
        assert session.selected_host_id == first_id

        with pytest.raises(ValueError):
            session.add_host("EXAMPLE.COM")  # case-insensitive duplicate

        # Edit reassigns the target and clears accumulated stats.
        session.apply_result(added_id, PingResult(success=True, rtt_ms=5.0, resolved_ip="93.0.0.1"))
        assert session.hosts[added_id].stats.seq == 1
        session.edit_host(added_id, "9.9.9.9")
        assert session.hosts[added_id].config.target == "9.9.9.9"
        assert session.hosts[added_id].stats.seq == 0

        session.select(added_id)
        assert session.current_host() is session.hosts[added_id]

        session.delete_host(added_id)
        assert added_id not in session.hosts
        # Selection falls back to a remaining host.
        assert session.selected_host_id == first_id

    def test_apply_result_success_timeout_error_and_paused(self) -> None:
        """apply_result routes success/timeout/error into the right stat transitions and
        ignores results for a paused host."""
        session = build_session("1.1.1.1")
        host_id = next(iter(session.hosts))

        session.apply_result(host_id, PingResult(success=True, rtt_ms=11.5, resolved_ip="1.1.1.1"))
        session.apply_result(host_id, PingResult(success=False, resolved_ip="1.1.1.1"))
        row = session.host_snapshot(host_id)
        assert row["seq"] == 2
        assert row["lost"] == 1
        assert row["last_rtt_ms"] == 11.5
        assert row["trend"]

        session.apply_result(host_id, PingResult(success=False, error_message="down", resolved_ip="2.2.2.2"))
        row = session.host_snapshot(host_id)
        assert row["state"] == "error"
        assert row["last_error"] == "down"
        assert row["resolved_ip"] == "2.2.2.2"
        assert row["seq"] == 2  # an error does not advance the sequence counter

        session.pause_host(host_id)
        session.apply_result(host_id, PingResult(success=True, rtt_ms=99.0, resolved_ip="1.1.1.1"))
        assert session.host_snapshot(host_id)["seq"] == 2  # paused host ignores results

    def test_pause_resume_toggle_single_and_all(self) -> None:
        """Single-host and all-host pause/resume/toggle helpers update the paused flag."""
        session = build_session("1.1.1.1", "8.8.8.8")
        a, b = list(session.hosts)

        session.pause_host(a)
        assert session.hosts[a].paused is True
        session.resume_host(a)
        assert session.hosts[a].paused is False

        session.toggle_host_pause(a)
        assert session.hosts[a].paused is True
        session.toggle_host_pause(a)
        assert session.hosts[a].paused is False

        session.pause_all()
        assert all(record.paused for record in session.hosts.values())
        session.resume_all()
        assert all(not record.paused for record in session.hosts.values())

        session.toggle_all_pause()  # any unpaused -> pause everything
        assert all(record.paused for record in session.hosts.values())
        session.toggle_all_pause()  # all paused -> resume everything
        assert all(not record.paused for record in session.hosts.values())
        assert {a, b} == set(session.hosts)

    def test_reset_single_and_all_preserve_pause(self) -> None:
        """Resetting clears stats; a paused host stays paused after reset."""
        session = build_session("1.1.1.1", "8.8.8.8")
        a, b = list(session.hosts)
        for host_id in (a, b):
            session.apply_result(host_id, PingResult(success=True, rtt_ms=10.0, resolved_ip="1.1.1.1"))

        session.pause_host(a)
        session.reset_host(a)
        assert session.hosts[a].stats.seq == 0
        assert session.hosts[a].paused is True
        assert session.hosts[a].stats.state.value == "paused"

        session.reset_all()
        assert all(record.stats.seq == 0 for record in session.hosts.values())

    def test_sorting_dotted_numeric_cycle_and_toggle(self) -> None:
        """Host/IP columns sort by numeric segments; cycle_sort advances the key and
        toggle/set control direction; numeric columns place missing values last."""
        session = build_session("1.1.1.10", "1.1.1.6", "1.1.1.9", "1.1.1.7")
        assert [row["target"] for row in session.host_snapshots()] == [
            "1.1.1.6",
            "1.1.1.7",
            "1.1.1.9",
            "1.1.1.10",
        ]
        session.set_sort(SortKey.HOST, reverse=True)
        assert [row["target"] for row in session.host_snapshots()] == [
            "1.1.1.10",
            "1.1.1.9",
            "1.1.1.7",
            "1.1.1.6",
        ]

        assert session.sort_key == SortKey.HOST
        session.cycle_sort()
        assert session.sort_key == SortKey.IP
        session.toggle_sort_order()
        assert session.sort_reverse is False  # was True from set_sort above

        # Sorting by a numeric stat puts a host with no samples last (ascending).
        numeric = build_session("10.0.0.1", "10.0.0.2", "10.0.0.3")
        h1, h2, _h3 = list(numeric.hosts)
        numeric.apply_result(h1, PingResult(success=True, rtt_ms=30.0, resolved_ip="10.0.0.1"))
        numeric.apply_result(h2, PingResult(success=True, rtt_ms=10.0, resolved_ip="10.0.0.2"))
        numeric.set_sort(SortKey.RTT)
        assert [row["target"] for row in numeric.host_snapshots()] == [
            "10.0.0.2",
            "10.0.0.1",
            "10.0.0.3",
        ]

    def test_aggregates_and_snapshot(self) -> None:
        """aggregates() rolls up host/active/paused/error counts and loss; snapshot()
        bundles config, per-host rows, and the aggregates."""
        session = build_session("1.1.1.1", "8.8.8.8", "bad-host")
        a, b, c = list(session.hosts)
        session.apply_result(a, PingResult(success=True, rtt_ms=10.0, resolved_ip="1.1.1.1"))
        session.pause_host(a)
        session.apply_result(b, PingResult(success=False, resolved_ip="8.8.8.8"))
        session.apply_result(c, PingResult(success=False, error_message="Unknown host"))

        aggregates = session.aggregates()
        assert aggregates["total_hosts"] == 3
        assert aggregates["active_hosts"] == 2
        assert aggregates["paused_hosts"] == 1
        assert aggregates["error_hosts"] == 1
        assert aggregates["total_sent"] == 2
        assert aggregates["total_lost"] == 1
        assert aggregates["loss_percent"] == 50.0

        snapshot = session.snapshot()
        assert snapshot.config is session.config
        assert len(snapshot.hosts) == 3
        assert snapshot.aggregates == aggregates

    def test_infer_export_format_from_suffix_and_explicit(self) -> None:
        """Export format is inferred from the file suffix unless overridden; an
        unknown suffix without an explicit format raises ValueError."""
        assert infer_export_format("out.json", None) == ExportFormat.JSON
        assert infer_export_format("out.csv", None) == ExportFormat.CSV
        assert infer_export_format("out.data", "json") == ExportFormat.JSON
        with pytest.raises(ValueError):
            infer_export_format("out.data", None)

    def test_session_validation_errors(self) -> None:
        """Empty targets and unknown host ids raise the documented exceptions."""
        session = build_session("1.1.1.1")
        with pytest.raises(ValueError):
            session.add_host("   ")
        with pytest.raises(KeyError):
            session.require_host("does-not-exist")
        with pytest.raises(KeyError):
            session.host_snapshot("does-not-exist")

    def test_host_snapshots_handles_mixed_states(self) -> None:
        """Sorting snapshots by any column copes with a mix of running, timed-out, and
        errored hosts (mixed populated/None fields) without raising."""
        session = build_session("1.1.1.1", "8.8.8.8", "bad-host")
        a, b, c = list(session.hosts)
        session.apply_result(a, PingResult(success=True, rtt_ms=10.0, resolved_ip="1.1.1.1"))
        session.apply_result(b, PingResult(success=False, resolved_ip="8.8.8.8"))
        session.apply_result(c, PingResult(success=False, error_message="down"))
        for key in SortKey:
            session.set_sort(key)
            assert len(session.host_snapshots()) == 3
        assert len(session.snapshot().hosts) == 3


class TestSummary:
    """The colored exit summary rendered from a session snapshot."""

    def test_summary_reports_status_loss_and_issue_lines(self) -> None:
        """A mix of loss and an unreachable host yields an ERR header line plus per-host
        issue lines describing the error and the loss ratio."""
        session = build_session("1.1.1.1", "bad-host")
        a, b = list(session.hosts)
        session.apply_result(a, PingResult(success=True, rtt_ms=10.0, resolved_ip="1.1.1.1"))
        session.apply_result(a, PingResult(success=False, resolved_ip="1.1.1.1"))
        session.apply_result(b, PingResult(success=False, error_message="Unknown host"))

        summary = render_summary(session.snapshot())
        assert summary.splitlines()[0] == "ERR | 2 hosts | tx 2 | rx 1 | loss 50.0% | err 1 | lossy 1"
        assert "ERR bad-host Unknown host" in summary
        assert "LOSS 1.1.1.1 50.0% loss (1/2), avg 10.0 ms" in summary

    def test_summary_is_single_line_when_healthy(self) -> None:
        """All-healthy hosts collapse to a one-line OK summary with no issue lines."""
        session = build_session("1.1.1.1", "8.8.8.8")
        for host_id, ip in zip(session.hosts, ["1.1.1.1", "8.8.8.8"], strict=True):
            session.apply_result(host_id, PingResult(success=True, rtt_ms=10.0, resolved_ip=ip))

        assert render_summary(session.snapshot()) == "OK | 2 hosts | tx 2 | rx 2 | loss 0.0%"

    def test_summary_limits_issue_lines(self) -> None:
        """The number of issue lines is capped, with a trailing '+N more issues' line."""
        session = build_session("b1", "b2", "b3", "b4", "b5", "b6", "b7")
        for host_id in session.hosts:
            session.apply_result(host_id, PingResult(success=False, error_message="Unknown host"))

        summary = render_summary(session.snapshot(), max_issues=5)
        assert summary.count("\n") == 6  # 1 header + 5 issues + 1 "more" line
        assert "MORE +2 more issues" in summary

    def test_summary_color_toggles_ansi_styling(self) -> None:
        """color=True wraps fields in ANSI escapes; color=False stays plain text."""
        session = build_session("1.1.1.1")
        host_id = next(iter(session.hosts))
        session.apply_result(host_id, PingResult(success=True, rtt_ms=10.0, resolved_ip="1.1.1.1"))
        snapshot = session.snapshot()

        assert "\x1b[" in render_summary(snapshot, color=True)
        assert "\x1b[" not in render_summary(snapshot, color=False)


class TestExporters:
    """Snapshot serialization to JSON and CSV files."""

    def test_export_json_payload_structure(self, tmp_path) -> None:
        """JSON export nests generated_at, config (with a serialized export format),
        aggregates, and per-host rows."""
        session = build_session("1.1.1.1")
        host_id = next(iter(session.hosts))
        session.apply_result(host_id, PingResult(success=True, rtt_ms=12.5, resolved_ip="1.1.1.1"))
        session.config.export_format = ExportFormat.JSON
        snapshot = session.snapshot()

        path = export_snapshot(snapshot, str(tmp_path / "snap.json"), ExportFormat.JSON)
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert set(payload) == {"generated_at", "config", "aggregates", "hosts"}
        assert payload["config"]["export_format"] == "json"
        assert payload["aggregates"]["total_hosts"] == 1
        assert payload["hosts"][0]["target"] == "1.1.1.1"
        assert payload["hosts"][0]["last_rtt_ms"] == 12.5

    def test_export_csv_columns_and_values(self, tmp_path) -> None:
        """CSV export writes the fixed per-host column header and one row per host."""
        session = build_session("1.1.1.1")
        host_id = next(iter(session.hosts))
        session.apply_result(host_id, PingResult(success=True, rtt_ms=12.5, resolved_ip="1.1.1.1"))

        path = export_snapshot(session.snapshot(), str(tmp_path / "snap.csv"), ExportFormat.CSV)
        with path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        assert reader.fieldnames == [
            "id",
            "target",
            "enabled",
            "resolved_ip",
            "seq",
            "last_rtt_ms",
            "min_rtt_ms",
            "avg_rtt_ms",
            "max_rtt_ms",
            "stddev_ms",
            "lost",
            "loss_percent",
            "trend",
            "last_error",
            "state",
            "last_updated_at",
        ]
        assert rows[0]["target"] == "1.1.1.1"
        assert rows[0]["resolved_ip"] == "1.1.1.1"
        assert rows[0]["seq"] == "1"

    def test_export_creates_missing_parent_directories(self, tmp_path) -> None:
        """Exporting to a nested path creates intermediate directories and returns it."""
        session = build_session("1.1.1.1")
        destination = tmp_path / "deep" / "nested" / "snap.json"

        path = export_snapshot(session.snapshot(), str(destination), ExportFormat.JSON)

        assert path == destination
        assert destination.exists()


class TestTrendWidgets:
    """The rich-text trend visualizations: the inline sparkline, the multi-row bar
    chart, the details-panel RTT graph, and the gradient legend.

    The sparkline test is scoped to what the widget layer adds on top of the model's
    sample->block bucketing (which `TestTrendModel::test_trend_computation_buckets_and_timeout_marker`
    already owns): the per-cell foreground colouring, the empty-history dash, and
    width-clipping to the most recent samples. The remaining renderers each own a
    distinct layout contract (column filling, scaled axis rows, ordered gradient) that
    no other test exercises."""

    def test_render_trend_colours_and_clips_cells(self) -> None:
        """render_trend turns the bucketed history into a `Text` whose cells carry a
        foreground-only colour per sample (a distinct style for a timeout), renders a
        dash for empty/None history, and keeps the latest samples when width-limited."""
        from pingtop.widgets.trend import render_trend

        trend = render_trend([10.0, 15.0, 30.0, None])
        assert isinstance(trend, Text)
        assert len(trend.plain) == 4
        # The widget layer's own job: colour each cell. Assert only the observable
        # contract -- one styled span per sample, the timeout cell styled distinctly
        # from the RTT cells, and foreground-only colours (no "on" background) -- without
        # importing the module's private palette constants, which a correct alternative
        # implementation (e.g. inline per-cell colours) need not expose.
        assert len(trend.spans) == len(trend.plain), "expected one styled cell per sample"
        rtt_styles = [str(span.style) for span in trend.spans[:-1]]
        timeout_style = str(trend.spans[-1].style)
        assert timeout_style not in rtt_styles, "timeout cell must be styled distinctly from RTT cells"
        assert all(" on " not in str(span.style) for span in trend.spans), "colours are foreground-only"

        # Empty / missing history is a dash, not an empty sparkline.
        assert render_trend([]).plain == "-"
        assert render_trend(None).plain == "-"

        # A positive width keeps only the most recent cells.
        full = render_trend([10.0, 12.0, 14.0, 16.0])
        clipped = render_trend([10.0, 12.0, 14.0, 16.0], width=2)
        assert len(clipped.plain) == 2
        assert clipped.plain == full.plain[-2:]

    def test_render_trend_graph_is_multiline(self) -> None:
        """render_trend_graph builds a height-row chart with bars, empty cells, and
        timeout markers; empty history collapses to a dash."""
        from pingtop.widgets.trend import render_trend_graph

        graph = render_trend_graph([10.0, 15.0, 30.0, None], width=4, height=4)
        assert isinstance(graph, Text)
        assert graph.plain.count("\n") == 3
        assert "·" in graph.plain
        # A timed-out column shows the marker in every one of the `height` rows.
        assert graph.plain.count(TIMEOUT_MARKER) == 4
        assert render_trend_graph([]).plain == "-"

    def test_render_detailed_trend_graph_branches(self) -> None:
        """The detailed graph shows a titled, axis-labelled chart with RTT scale values;
        all-timeout and empty histories fall back to their own layouts."""
        from pingtop.widgets.trend import render_detailed_trend_graph

        # As many samples as `width`, so the graph width is unambiguous however the
        # renderer treats a history shorter than the requested width.
        lines = render_detailed_trend_graph([10.0, 15.0, 20.0, 30.0], width=4, height=4)
        joined = "\n".join(line.plain for line in lines)
        assert lines[0].plain.startswith("RTT Graph")
        assert "30.0" in joined and "10.0" in joined
        assert "└" in joined
        assert "█" in joined
        # The bottom axis underline spans the full graph width. Find the axis by its
        # "└" marker rather than by list position -- the layout may carry a caption
        # below the axis.
        axis_lines = [line.plain for line in lines if "└" in line.plain]
        assert axis_lines, "expected a bottom axis line containing '└'"
        assert "────" in axis_lines[-1]

        timeouts = render_detailed_trend_graph([None, None], width=2, height=4)
        timeout_text = "\n".join(line.plain for line in timeouts)
        assert "oldest -> newest" in timeout_text
        assert TIMEOUT_MARKER in timeout_text
        # The all-timeout layout is labelled "timeouts".
        assert "timeouts" in timeout_text

        empty = render_detailed_trend_graph([])
        assert empty[0].plain.startswith("RTT Graph")
        assert "waiting for samples" in empty[1].plain

    def test_render_trend_legend(self) -> None:
        """The legend names the low/high RTT gradient and the timeout marker, and lays
        out every TREND_BLOCKS glyph in low->high order between the two RTT anchors."""
        from pingtop.widgets.trend import render_trend_legend

        legend = render_trend_legend().plain
        assert "Trend Legend" in legend
        assert "low RTT" in legend
        assert "high RTT" in legend
        assert TIMEOUT_MARKER in legend

        # The gradient itself must be rendered: every TREND_BLOCKS glyph appears, in
        # low->high order, between the "low RTT" and "high RTT" anchors. A legend that
        # hard-codes the labels without iterating the gradient would not satisfy this.
        low_anchor = legend.index("low RTT")
        high_anchor = legend.index("high RTT")
        assert low_anchor < high_anchor
        gradient_region = legend[low_anchor:high_anchor]
        positions = [gradient_region.find(block) for block in TREND_BLOCKS]
        assert all(pos >= 0 for pos in positions), positions
        assert positions == sorted(positions)


def _fake_app_factory(recorded: dict, *, apply_success: bool = False):
    """Build a drop-in for PingTopApp that records the session and skips the TUI."""

    class FakeApp:
        def __init__(self, session, engine) -> None:
            recorded["session"] = session
            recorded["engine"] = engine

        def run(self) -> None:
            if apply_success and recorded["session"].hosts:
                host_id = next(iter(recorded["session"].hosts))
                recorded["session"].apply_result(
                    host_id,
                    PingResult(success=True, rtt_ms=9.5, resolved_ip="1.1.1.1"),
                )

    return FakeApp


class TestCli:
    """The Click entry point: argument handling, host expansion, export, validation."""

    def test_requires_at_least_one_host(self) -> None:
        """Running with no hosts and no --hosts-file is an error."""
        result = CliRunner().invoke(cli.main, [])
        assert result.exit_code != 0
        assert "Provide at least one host" in result.output

    def test_merges_args_with_hosts_file_and_deduplicates(self, tmp_path, monkeypatch) -> None:
        """CLI args and --hosts-file are merged in order, blank/'#' lines are dropped,
        and duplicates are removed case-insensitively."""
        hosts_file = tmp_path / "hosts.txt"
        hosts_file.write_text("1.1.1.1\n# a comment\n\n8.8.8.8\n1.1.1.1\n", encoding="utf-8")
        recorded: dict = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded))

        result = CliRunner().invoke(cli.main, ["1.1.1.1", "--hosts-file", str(hosts_file), "--no-summary"])

        assert result.exit_code == 0
        targets = [record.config.target for record in recorded["session"].hosts.values()]
        assert targets == ["1.1.1.1", "8.8.8.8"]

    def test_expands_cidr_to_usable_hosts(self, monkeypatch) -> None:
        """A CIDR argument expands to its usable host addresses."""
        recorded: dict = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded))

        result = CliRunner().invoke(cli.main, ["10.22.76.19/30", "--no-summary"])

        assert result.exit_code == 0
        targets = [record.config.target for record in recorded["session"].hosts.values()]
        assert targets == ["10.22.76.17", "10.22.76.18"]

    def test_rejects_invalid_cidr(self, monkeypatch) -> None:
        """An out-of-range prefix produces a clear error."""
        recorded: dict = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded))

        result = CliRunner().invoke(cli.main, ["10.22.76.19/99"])

        assert result.exit_code != 0
        assert "Invalid network or host" in result.output

    def test_exports_json_and_csv_on_exit(self, tmp_path, monkeypatch) -> None:
        """After the TUI exits, the final snapshot is written in the inferred format."""
        json_path = tmp_path / "out.json"
        recorded: dict = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded, apply_success=True))
        result = CliRunner().invoke(cli.main, ["1.1.1.1", "--export", str(json_path), "--no-summary"])
        assert result.exit_code == 0
        assert json.loads(json_path.read_text(encoding="utf-8"))["hosts"][0]["target"] == "1.1.1.1"

        csv_path = tmp_path / "out.csv"
        recorded = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded, apply_success=True))
        result = CliRunner().invoke(cli.main, ["1.1.1.1", "--export", str(csv_path), "--no-summary"])
        assert result.exit_code == 0
        assert csv_path.exists()
        with csv_path.open(encoding="utf-8") as handle:
            assert list(csv.DictReader(handle))[0]["target"] == "1.1.1.1"

    def test_requires_explicit_format_for_ambiguous_extension(self, tmp_path, monkeypatch) -> None:
        """An unknown export extension without --export-format is rejected."""
        recorded: dict = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded))

        result = CliRunner().invoke(cli.main, ["1.1.1.1", "--export", str(tmp_path / "out.data")])

        assert result.exit_code != 0
        assert "Unable to infer export format" in result.output

    def test_export_format_requires_export(self, monkeypatch) -> None:
        """--export-format without --export is rejected."""
        recorded: dict = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded))

        result = CliRunner().invoke(cli.main, ["1.1.1.1", "--export-format", "json"])

        assert result.exit_code != 0
        assert "--export-format requires --export" in result.output

    def test_rejects_nonpositive_numeric_options(self, monkeypatch) -> None:
        """Interval, timeout, and packet size must all be greater than zero."""
        recorded: dict = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded))

        for flag in (["--interval", "0"], ["--timeout", "0"], ["--packet-size", "0"]):
            result = CliRunner().invoke(cli.main, ["1.1.1.1", *flag])
            assert result.exit_code != 0
            assert "greater than zero" in result.output

    def test_log_file_and_level_propagate_to_session(self, tmp_path, monkeypatch) -> None:
        """--log-file and --log-level flow through to the session's config; omitting
        --log-level leaves the documented 'info' default."""
        log_path = tmp_path / "pingtop.log"
        recorded: dict = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded))
        result = CliRunner().invoke(
            cli.main,
            ["1.1.1.1", "--log-file", str(log_path), "--log-level", "debug", "--no-summary"],
        )
        assert result.exit_code == 0
        config = recorded["session"].config
        assert config.log_file == str(log_path)
        assert config.log_level == "debug"

        recorded = {}
        monkeypatch.setattr(cli, "PingTopApp", _fake_app_factory(recorded))
        result = CliRunner().invoke(cli.main, ["1.1.1.1", "--no-summary"])
        assert result.exit_code == 0
        assert recorded["session"].config.log_file is None
        assert recorded["session"].config.log_level == "info"


class _FakeEngine:
    """A network-free PingEngine: mostly successful with occasional timeouts."""

    def __init__(self) -> None:
        self._counts: defaultdict[str, int] = defaultdict(int)

    async def ping_once(self, target: str, timeout: float, packet_size: int, flag: int) -> PingResult:
        self._counts[target] += 1
        count = self._counts[target]
        if target == "bad-host":
            return PingResult(success=False, error_message="Unknown host")
        if count % 4 == 0:
            return PingResult(success=False, resolved_ip="127.0.0.1")
        return PingResult(success=True, rtt_ms=10.0 + count, resolved_ip="127.0.0.1")


def _make_app(session):
    """Lazily import PingTopApp so a relocated app module fails only the app tests."""
    from pingtop.app import PingTopApp

    return PingTopApp(session=session, engine=_FakeEngine())


def _collect_rendered_text(app) -> str:
    """Concatenate every widget's rendered text on the current screen, so the
    details-panel assertions can find the content wherever the agent placed the
    panel without importing the concrete widget class."""
    parts: list[str] = []
    for widget in app.screen.query("*"):
        if getattr(widget, "render", None) is None:
            continue
        try:
            rendered = widget.render()
        except Exception:  # noqa: BLE001 - not all widgets render in isolation
            continue
        parts.append(rendered.plain if isinstance(rendered, Text) else str(rendered))
    return "\n".join(parts)


class TestApp:
    """The Textual application shell, driven headlessly via run_test()."""

    async def test_boots_polls_and_populates_table(self) -> None:
        """Booting the app starts per-host ping loops that advance stats, and the table
        shows one row per host."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1", "8.8.8.8"])
        app = _make_app(session)

        async with app.run_test(size=(160, 40)) as pilot:
            # Pause longer than the app's result-flush cadence so polled samples
            # have been applied to the session before we assert on them.
            await pilot.pause(0.6)
            assert all(record.stats.seq >= 1 for record in session.hosts.values())
            assert app.query_one(DataTable).row_count == len(session.hosts)
            await pilot.press("q")

    async def test_sort_hotkey_sets_and_reverses_order(self) -> None:
        """Pressing a sort hotkey selects that column; pressing it again reverses it."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1", "8.8.8.8"])
        app = _make_app(session)

        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            await pilot.press("S")
            await pilot.pause(0.05)
            assert session.sort_key == SortKey.SEQ
            assert session.sort_reverse is False
            await pilot.press("S")
            await pilot.pause(0.05)
            assert session.sort_reverse is True
            await pilot.press("q")

    async def test_pause_all_and_resume_all_bindings(self) -> None:
        """The pause-all hotkey toggles every host between paused and running."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1", "8.8.8.8"])
        app = _make_app(session)

        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            await pilot.press("p")
            assert all(record.paused for record in session.hosts.values())
            await pilot.press("p")
            assert all(not record.paused for record in session.hosts.values())
            await pilot.press("q")

    async def test_selected_pause_and_reset_all_bindings(self) -> None:
        """Space pauses the selected host; reset-all clears every host's statistics."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1", "8.8.8.8"])
        app = _make_app(session)

        async with app.run_test() as pilot:
            # Pause longer than the app's result-flush cadence so the selected
            # host has accumulated samples before we reset them.
            await pilot.pause(0.6)
            selected = session.selected_host_id
            assert selected is not None
            assert session.hosts[selected].stats.seq > 0

            await pilot.press("space")
            assert session.hosts[selected].paused is True

            await pilot.press("p")  # freeze every host so reset is race-free
            assert all(record.paused for record in session.hosts.values())
            await pilot.press("ctrl+r")
            assert all(record.stats.seq == 0 for record in session.hosts.values())
            await pilot.press("q")

    async def test_details_panel_shows_selected_host(self) -> None:
        """Toggling the details panel (i) renders the selected host's fields and RTT graph."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1"])
        app = _make_app(session)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("i")
            await pilot.pause(0.15)
            text = _collect_rendered_text(app)
            assert "Host:" in text
            assert "1.1.1.1" in text
            assert "RTT Graph" in text
            await pilot.press("q")

    async def test_host_table_formats_cell_values(self) -> None:
        """Live table cells render RTT with one decimal place and loss as a percentage."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1"])
        app = _make_app(session)

        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause(0.6)  # accumulate samples past the flush cadence
            table = app.query_one(DataTable)
            row_id = next(iter(session.hosts))
            rtt_cell = str(table.get_cell(row_id, "last_rtt_ms")).strip()
            loss_cell = str(table.get_cell(row_id, "loss_percent")).strip()
            assert re.fullmatch(r"\d+\.\d", rtt_cell), rtt_cell
            assert re.fullmatch(r"\d+\.\d%", loss_cell), loss_cell
            await pilot.press("q")

    async def test_add_edit_delete_via_modal(self) -> None:
        """The a/e/d bindings open modal dialogs whose results add, edit, and delete hosts."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1"])
        app = _make_app(session)

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)

            # Add: open the form, fill the host input, submit with Enter.
            await pilot.press("a")
            await pilot.pause(0.15)
            add_input = app.screen.query_one(Input)
            add_input.focus()
            await pilot.pause(0.05)
            add_input.value = "8.8.8.8"
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert "8.8.8.8" in [r.config.target for r in session.hosts.values()]
            assert len(session.hosts) == 2

            # Edit the selected host through the pre-filled form.
            selected = session.selected_host_id
            assert selected is not None
            await pilot.press("e")
            await pilot.pause(0.15)
            edit_input = app.screen.query_one(Input)
            edit_input.focus()
            await pilot.pause(0.05)
            edit_input.value = "9.9.9.9"
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert session.hosts[selected].config.target == "9.9.9.9"

            # Delete the selected host by confirming in the dialog.
            selected = session.selected_host_id
            before = len(session.hosts)
            await pilot.press("d")
            await pilot.pause(0.15)
            confirm = [button for button in app.screen.query(Button) if button.variant == "error"]
            assert confirm, "expected a destructive confirm button in the delete dialog"
            confirm[0].press()
            await pilot.pause(0.2)
            assert selected not in session.hosts
            assert len(session.hosts) == before - 1
            # No terminal `pilot.press("q")` here: after stacking three modal
            # push/dismiss cycles, forcing the harness to drain the message pump
            # (`pilot.press` -> `_wait_for_screen`) can time out while the
            # spec-mandated per-host ping loop keeps re-queuing refreshes. All
            # behavioral assertions are already complete, and the `q` quit binding
            # is covered by the other TestApp tests, so let `run_test()` tear the
            # app down on context exit instead.

    async def test_responsive_column_profiles(self) -> None:
        """The table shows a width-dependent column set: the full 12 columns at >=150
        cols, a reduced 8 in the 105-149 band, and a minimal 6 below 105."""
        counts: dict[str, int] = {}
        for size, name in [((160, 40), "wide"), ((120, 30), "medium"), ((90, 24), "narrow")]:
            session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1"])
            app = _make_app(session)
            async with app.run_test(size=size) as pilot:
                await pilot.pause(0.2)
                counts[name] = len(app.query_one(DataTable).ordered_columns)
                await pilot.press("q")
        assert counts == {"wide": 12, "medium": 8, "narrow": 6}

    async def test_sort_indicator_marks_active_column(self) -> None:
        """Selecting a sort column marks its header with an ascending/descending indicator."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1", "8.8.8.8"])
        app = _make_app(session)

        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("R")
            await pilot.pause(0.1)
            headers = "".join(str(column.label) for column in app.query_one(DataTable).ordered_columns)
            assert "▲" in headers
            await pilot.press("R")
            await pilot.pause(0.1)
            headers = "".join(str(column.label) for column in app.query_one(DataTable).ordered_columns)
            assert "▼" in headers
            await pilot.press("q")

    async def test_status_strip_reports_session_state(self) -> None:
        """The status strip reports host counts (active/paused/errors), traffic, and sort state."""
        session = PingSession(SessionConfig(interval=0.05, timeout=0.01), ["1.1.1.1"])
        app = _make_app(session)

        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause(0.6)
            text = _collect_rendered_text(app)
            # The single host is unpaused and the fake engine never errors it, so the
            # active/paused/error counts are fully determined: assert the resolved values,
            # not just the bare labels, so a mis-wired aggregate is caught.
            assert "Active 1" in text
            assert "Paused 0" in text
            assert "Errors 0" in text
            # The session starts sorted on the HOST column (field "target"), ascending.
            assert "Sort target" in text
            assert "ASC" in text
            # Sent/Lost depend on how many polls landed in the pause window, so only their
            # labels are deterministic.
            for token in ("Sent", "Lost"):
                assert token in text, token
            await pilot.press("q")


class TestIcmpEngine:
    """The default raw-ICMP engine's resolution contract."""

    async def test_resolution_failure_returns_error_result(self) -> None:
        """A name that cannot be resolved yields an unsuccessful result carrying the
        resolver error message rather than raising."""
        from pingtop.engine.icmp import IcmpEngine

        result = await IcmpEngine().ping_once(
            "nonexistent.invalid", timeout=0.5, packet_size=56, flag=1
        )
        assert result.success is False
        assert result.rtt_ms is None
        assert result.error_message

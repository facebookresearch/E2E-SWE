"""Behavioral tests for SAPP's taint-analysis output parsers (Pysa + Mariana Trench).

Each test feeds an inline taint-output document and asserts the exact parsed result
(issues + pre/postcondition trace frames). The arbitrary hashed issue `handle` is not
asserted (normalized out), so tests measure parsing/normalization behavior, not the
hash. Public parser API only.
"""

import io
import sys
import unittest
from typing import Iterable, Union

from sapp.analysis_output import AnalysisOutput, Metadata, Rule
from sapp.pipeline import (
    ParseConditionTuple,
    ParseError,
    ParseIssueConditionTuple,
    ParseIssueTuple,
    ParseTraceAnnotation,
    ParseTraceAnnotationSubtrace,
    ParseTraceFeature,
    ParseTypeInterval,
    SourceLocation,
)
from sapp.pipeline.base_parser import ParseType
from sapp.pipeline.pysa_taint_parser import Parser as PysaParser
from sapp.pipeline.mariana_trench_parser import Parser as MarianaParser


class TestPysaParser(unittest.TestCase):
    def assertParsed(
        self,
        version: int,
        input: str,
        expected: Iterable[Union[ParseConditionTuple, ParseIssueTuple]],
    ) -> None:
        input = "".join(input.split("\n"))  # Flatten json-line.
        input = '{"file_version":%d}\n%s' % (version, input)  # Add version header.
        parser = PysaParser()
        analysis_output = AnalysisOutput(
            directory="/output/directory",
            filename_specs=["taint-output.json"],
            file_handle=io.StringIO(input),
            metadata=Metadata(
                repo_roots={"/analysis/root"},
                rules={1: Rule(name="TestRule", description="Test Rule Description")},
            ),
        )

        def sort_entry(e: Union[ParseConditionTuple, ParseIssueTuple]) -> str:
            if isinstance(e, ParseConditionTuple):
                return e.caller
            else:
                return e.callable

        issues_and_frames = parser.parse_analysis_output(analysis_output)
        entries = (
            issues_and_frames.issues
            + list(issues_and_frames.preconditions.all_frames())
            + list(issues_and_frames.postconditions.all_frames())
        )
        self.assertEqual(
            [
                (_e._replace(handle="") if isinstance(_e, ParseIssueTuple) else _e)
                for _e in sorted(entries, key=sort_entry)
            ],
            [
                (_x._replace(handle="") if isinstance(_x, ParseIssueTuple) else _x)
                for _x in expected
            ],
        )

    def testEmptyModelV3(self) -> None:
        # A model with no taint-producing keys yields no frames, whether it is
        # bare, carries only `modes`, or carries only a `global_sanitizer`.
        for data in (
            '{"callable": "foo.bar"}',
            '{"callable": "foo.bar", "modes": [ "Obscure" ]}',
            '{"callable": "foo.bar", "global_sanitizer": { "sources": "All" }}',
        ):
            self.assertParsed(
                version=3,
                input="""
                    {
                      "kind": "model",
                      "data": %s
                    }
                    """
                % data,
                expected=[],
            )

    def testIssueV3_indirectSourceToIndirectSink(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "issue",
                  "data": {
                    "callable": "foo.bar",
                    "callable_line": 10,
                    "code": 1,
                    "line": 11,
                    "start": 12,
                    "end": 13,
                    "filename": "foo.py",
                    "message": "[UserControlled] to [RCE]",
                    "sink_handle": {
                      "kind": "Call",
                      "callee": "foo.sink",
                      "index": 0,
                      "parameter": "formal(x)"
                    },
                    "master_handle": "foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    "traces": [
                      {
                        "name": "forward",
                        "roots": [
                          {
                            "receiver_interval": [{ "lower": 23, "upper": 24 }],
                            "is_self_call": false,
                            "call": {
                              "position": {
                                "line": 14,
                                "start": 15,
                                "end": 16
                              },
                              "resolves_to": [
                                "foo.source"
                              ],
                              "port": "result"
                            },
                            "tito_positions": [ { "line": 17, "start": 18, "end": 19 } ],
                            "local_features": [ { "always-via": "source-local" } ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 1,
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "source-feature" } ],
                                "extra_traces": [
                                  {
                                    "call": {
                                      "position": {
                                        "line": 117,
                                        "start": 22,
                                        "end": 24
                                      },
                                      "resolves_to": [
                                        "extra_trace.transform_yz"
                                      ],
                                      "port": "formal(arg)"
                                    },
                                    "kind": "TransformY:TransformZ:ExtraTraceSink"
                                  }
                                ]
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "name": "backward",
                        "roots": [
                          {
                            "caller_interval": [{
                              "lower": 10,
                              "upper": 11
                            }],
                            "is_self_call": true,
                            "call": {
                              "position": {
                                "line": 20,
                                "start": 21,
                                "end": 22
                              },
                              "resolves_to": [
                                "foo.sink"
                              ],
                              "port": "formal(x)[parameter]"
                            },
                            "tito_positions": [ { "line": 23, "start": 24, "end": 25 } ],
                            "local_features": [ { "always-via": "sink-local" } ],
                            "kinds": [
                              {
                                "kind": "RCE",
                                "length": 2,
                                "leaves": [ { "name": "_remote_code_execution" } ],
                                "features": [ { "always-via": "sink-feature" } ],
                                "extra_traces": [
                                  {
                                    "call": {
                                      "position": {
                                        "line": 117,
                                        "start": 22,
                                        "end": 24
                                      },
                                      "resolves_to": [
                                        "extra_trace.transform_yz"
                                      ],
                                      "port": "formal(arg)"
                                    },
                                    "leaf_kind": "TransformY:TransformZ:ExtraTraceSink",
                                    "trace_kind": "sink"
                                  }
                                ]
                              }
                            ]
                          }
                        ]
                      }
                    ],
                    "features": [
                      { "always-via": "foo" },
                      { "via": "bar" }
                    ]
                  }
                }
                """,
            expected=[
                ParseIssueTuple(
                    code=1,
                    message="[UserControlled] to [RCE]",
                    callable="foo.bar",
                    handle="foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    filename="foo.py",
                    callable_line=10,
                    line=11,
                    start=13,
                    end=13,
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="foo.source",
                            port="result",
                            location=SourceLocation(
                                line_no=14,
                                begin_column=16,
                                end_column=16,
                            ),
                            leaves=[("UserControlled", 1)],
                            titos=[
                                SourceLocation(
                                    line_no=17, begin_column=19, end_column=19
                                ),
                            ],
                            features=[ParseTraceFeature("always-via:source-local", [])],
                            type_interval=ParseTypeInterval(
                                start=23,
                                finish=24,
                                preserves_type_context=False,
                            ),
                            annotations=[
                                ParseTraceAnnotation(
                                    location=SourceLocation(
                                        line_no=117, begin_column=23, end_column=24
                                    ),
                                    kind="tito_transform",
                                    msg="",
                                    leaf_kind="TransformY:TransformZ:ExtraTraceSink",
                                    leaf_depth=0,
                                    type_interval=None,
                                    link=None,
                                    trace_key=None,
                                    titos=[],
                                    subtraces=[
                                        ParseTraceAnnotationSubtrace(
                                            callee="extra_trace.transform_yz",
                                            port="formal(arg)",
                                            position=SourceLocation(
                                                line_no=117,
                                                begin_column=23,
                                                end_column=24,
                                            ),
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="foo.sink",
                            port="formal(x)[parameter]",
                            location=SourceLocation(
                                line_no=20,
                                begin_column=22,
                                end_column=22,
                            ),
                            leaves=[("RCE", 2)],
                            titos=[
                                SourceLocation(
                                    line_no=23, begin_column=25, end_column=25
                                )
                            ],
                            features=[ParseTraceFeature("always-via:sink-local", [])],
                            type_interval=ParseTypeInterval(
                                start=0, finish=sys.maxsize, preserves_type_context=True
                            ),
                            annotations=[
                                ParseTraceAnnotation(
                                    location=SourceLocation(
                                        line_no=117, begin_column=23, end_column=24
                                    ),
                                    kind="sink",
                                    msg="",
                                    leaf_kind="TransformY:TransformZ:ExtraTraceSink",
                                    leaf_depth=0,
                                    type_interval=None,
                                    link=None,
                                    trace_key=None,
                                    titos=[],
                                    subtraces=[
                                        ParseTraceAnnotationSubtrace(
                                            callee="extra_trace.transform_yz",
                                            port="formal(arg)",
                                            position=SourceLocation(
                                                line_no=117,
                                                begin_column=23,
                                                end_column=24,
                                            ),
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                    initial_sources={("_user_controlled", "UserControlled", 1)},
                    final_sinks={("_remote_code_execution", "RCE", 2)},
                    features=["always-via:foo", "via:bar"],
                    fix_info=None,
                )
            ],
        )

    def testIssueV3_directAndIndirectSourceToDirectAndIndirectSink(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "issue",
                  "data": {
                    "callable": "foo.bar",
                    "callable_line": 10,
                    "code": 1,
                    "line": 11,
                    "start": 12,
                    "end": 13,
                    "filename": "foo.py",
                    "message": "[UserControlled] to [RCE]",
                    "sink_handle": {
                      "kind": "Call",
                      "callee": "foo.sink",
                      "index": 0,
                      "parameter": "formal(x)"
                    },
                    "master_handle": "foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    "traces": [
                      {
                        "name": "forward",
                        "roots": [
                          {
                            "receiver_interval": [
                              { "lower": 20, "upper": 21 },
                              { "lower": 30, "upper": 41 }
                            ],
                            "origin": {
                              "line": 100,
                              "start": 101,
                              "end": 102
                            },
                            "tito_positions": [
                              { "line": 110, "start": 111, "end": 112 },
                              { "line": 113, "start": 114, "end": 115 }
                            ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "via": "source-direct" } ]
                              }
                            ]
                          },
                          {
                            "receiver_interval": [{ "lower": 22, "upper": 23 }],
                            "call": {
                              "position": {
                                "line": 120,
                                "start": 121,
                                "end": 122
                              },
                              "resolves_to": [
                                "foo.source"
                              ],
                              "port": "result"
                            },
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 2,
                                "leaves": [ { "name": "_other_user_controlled" } ],
                                "features": [ { "always-via": "source-indirect" } ]
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "name": "backward",
                        "roots": [
                          {
                            "receiver_interval": [{ "lower": 30, "upper": 31 }],
                            "origin": {
                              "line": 200,
                              "start": 201,
                              "end": 202
                            },
                            "tito_positions": [ { "line": 210, "start": 211, "end": 212 } ],
                            "kinds": [
                              {
                                "kind": "RCE",
                                "leaves": [ { "name": "_other_remote_code_execution" } ],
                                "features": [ { "always-via": "sink-direct" } ]
                              }
                            ]
                          },
                          {
                            "receiver_interval": [{ "lower": 32, "upper": 33 }],
                            "call": {
                              "position": {
                                "line": 220,
                                "start": 221,
                                "end": 222
                              },
                              "resolves_to": [
                                "foo.sink"
                              ],
                              "port": "formal(y)"
                            },
                            "kinds": [
                              {
                                "kind": "RCE",
                                "length": 5,
                                "leaves": [ { "name": "_remote_code_execution" } ],
                                "features": [ { "via": "sink-indirect" } ]
                              }
                            ]
                          }
                        ]
                      }
                    ],
                    "features": [
                      { "always-via": "foo" },
                      { "via": "bar" }
                    ]
                  }
                }
                """,
            expected=[
                ParseIssueTuple(
                    code=1,
                    message="[UserControlled] to [RCE]",
                    callable="foo.bar",
                    handle="foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    filename="foo.py",
                    callable_line=10,
                    line=11,
                    start=13,
                    end=13,
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="_user_controlled",
                            port="source",
                            location=SourceLocation(
                                line_no=100,
                                begin_column=102,
                                end_column=102,
                            ),
                            leaves=[("UserControlled", 0)],
                            titos=[
                                SourceLocation(
                                    line_no=110, begin_column=112, end_column=112
                                ),
                                SourceLocation(
                                    line_no=113, begin_column=115, end_column=115
                                ),
                            ],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=20,
                                finish=41,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                        ParseIssueConditionTuple(
                            callee="foo.source",
                            port="result",
                            location=SourceLocation(
                                line_no=120,
                                begin_column=122,
                                end_column=122,
                            ),
                            leaves=[("UserControlled", 2)],
                            titos=[],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=22,
                                finish=23,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                    ],
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="_other_remote_code_execution",
                            port="sink",
                            location=SourceLocation(
                                line_no=200,
                                begin_column=202,
                                end_column=202,
                            ),
                            leaves=[("RCE", 0)],
                            titos=[
                                SourceLocation(
                                    line_no=210, begin_column=212, end_column=212
                                )
                            ],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=30,
                                finish=31,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                        ParseIssueConditionTuple(
                            callee="foo.sink",
                            port="formal(y)",
                            location=SourceLocation(
                                line_no=220,
                                begin_column=222,
                                end_column=222,
                            ),
                            leaves=[("RCE", 5)],
                            titos=[],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=32,
                                finish=33,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                    ],
                    initial_sources={
                        ("_user_controlled", "UserControlled", 0),
                        ("_other_user_controlled", "UserControlled", 2),
                    },
                    final_sinks={
                        ("_other_remote_code_execution", "RCE", 0),
                        ("_remote_code_execution", "RCE", 5),
                    },
                    features=["always-via:foo", "via:bar"],
                    fix_info=None,
                )
            ],
        )

    def testIssueV3_indirectWithMultipleKinds(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "issue",
                  "data": {
                    "callable": "foo.bar",
                    "callable_line": 10,
                    "code": 1,
                    "line": 11,
                    "start": 12,
                    "end": 13,
                    "filename": "foo.py",
                    "message": "[UserControlled, Header] to [RCE, SQL]",
                    "sink_handle": {
                      "kind": "Call",
                      "callee": "foo.sink",
                      "index": 0,
                      "parameter": "formal(x)"
                    },
                    "master_handle": "foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    "traces": [
                      {
                        "name": "forward",
                        "roots": [
                          {
                            "receiver_interval": [
                              { "lower": 50, "upper": 51 },
                              { "lower": 60, "upper": 71 }
                            ],
                            "call": {
                              "position": {
                                "line": 14,
                                "start": 15,
                                "end": 16
                              },
                              "resolves_to": ["foo.source"],
                              "port": "result"
                            },
                            "tito_positions": [ { "line": 17, "start": 18, "end": 19 } ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 1,
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "source-feature" } ]
                              },
                              {
                                "kind": "Header",
                                "length": 2,
                                "leaves": [ { "name": "_header" } ],
                                "features": [ { "always-via": "source-other-feature" } ]
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "name": "backward",
                        "roots": [
                          {
                            "call": {
                              "position": {
                                "line": 20,
                                "start": 21,
                                "end": 22
                              },
                              "resolves_to": ["foo.sink"],
                              "port": "formal(x)[parameter]"
                            },
                            "tito_positions": [ { "line": 23, "start": 24, "end": 25 } ],
                            "kinds": [
                              {
                                "kind": "RCE",
                                "length": 3,
                                "leaves": [ { "name": "_remote_code_execution" } ],
                                "features": [ { "always-via": "sink-feature" } ]
                              },
                              {
                                "kind": "SQL",
                                "length": 2,
                                "leaves": [ { "name": "_sql" } ],
                                "features": [ { "always-via": "sink-other-feature" } ]
                              }
                            ]
                          }
                        ]
                      }
                    ],
                    "features": [
                      { "always-via": "foo" },
                      { "via": "bar" }
                    ]
                  }
                }
                """,
            expected=[
                ParseIssueTuple(
                    code=1,
                    message="[UserControlled, Header] to [RCE, SQL]",
                    callable="foo.bar",
                    handle="foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    filename="foo.py",
                    callable_line=10,
                    line=11,
                    start=13,
                    end=13,
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="foo.source",
                            port="result",
                            location=SourceLocation(
                                line_no=14,
                                begin_column=16,
                                end_column=16,
                            ),
                            leaves=[
                                ("Header", 2),
                                ("UserControlled", 1),
                            ],
                            titos=[
                                SourceLocation(
                                    line_no=17, begin_column=19, end_column=19
                                ),
                            ],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=50,
                                finish=71,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                    ],
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="foo.sink",
                            port="formal(x)[parameter]",
                            location=SourceLocation(
                                line_no=20,
                                begin_column=22,
                                end_column=22,
                            ),
                            leaves=[
                                ("RCE", 3),
                                ("SQL", 2),
                            ],
                            titos=[
                                SourceLocation(
                                    line_no=23, begin_column=25, end_column=25
                                )
                            ],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=0,
                                finish=sys.maxsize,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                    ],
                    initial_sources={
                        ("_user_controlled", "UserControlled", 1),
                        ("_header", "Header", 2),
                    },
                    final_sinks={
                        ("_remote_code_execution", "RCE", 3),
                        ("_sql", "SQL", 2),
                    },
                    features=["always-via:foo", "via:bar"],
                    fix_info=None,
                )
            ],
        )

    def testIssueV3_indirectSourceToReturnSink(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "issue",
                  "data": {
                    "callable": "foo.bar",
                    "callable_line": 10,
                    "code": 1,
                    "line": 11,
                    "start": 12,
                    "end": 13,
                    "filename": "foo.py",
                    "message": "[UserControlled] to [RCE]",
                    "sink_handle": {
                      "kind": "Call",
                      "callee": "foo.sink",
                      "index": 0,
                      "parameter": "formal(x)"
                    },
                    "master_handle": "foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    "traces": [
                      {
                        "name": "forward",
                        "roots": [
                          {
                            "origin": {
                              "line": 20,
                              "start": 21,
                              "end": 22
                            },
                            "tito_positions": [ { "line": 30, "start": 31, "end": 32 } ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [
                                  { "has": "first-index" },
                                  { "first-index": "payload" },
                                  { "always-via": "tito" }
                                ]
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "name": "backward",
                        "roots": [
                          {
                            "origin": {
                              "line": 100,
                              "start": 101,
                              "end": 102
                            },
                            "kinds": [ { "kind": "RCE" } ]
                          }
                        ]
                      }
                    ],
                    "features": [
                      { "has": "first-index" },
                      { "first-index": "payload" },
                      { "always-via": "tito" }
                    ]
                  }
                }
                """,
            expected=[
                ParseIssueTuple(
                    code=1,
                    message="[UserControlled] to [RCE]",
                    callable="foo.bar",
                    handle="foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    filename="foo.py",
                    callable_line=10,
                    line=11,
                    start=13,
                    end=13,
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="_user_controlled",
                            port="source",
                            location=SourceLocation(
                                line_no=20,
                                begin_column=22,
                                end_column=22,
                            ),
                            leaves=[("UserControlled", 0)],
                            titos=[
                                SourceLocation(
                                    line_no=30, begin_column=32, end_column=32
                                ),
                            ],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=0,
                                finish=sys.maxsize,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                    ],
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="leaf",
                            port="sink",
                            location=SourceLocation(
                                line_no=100,
                                begin_column=102,
                                end_column=102,
                            ),
                            leaves=[("RCE", 0)],
                            titos=[],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=0,
                                finish=sys.maxsize,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                    ],
                    initial_sources={("_user_controlled", "UserControlled", 0)},
                    final_sinks={(None, "RCE", 0)},
                    features=[
                        "always-via:tito",
                        "first-index:payload",
                        "has:first-index",
                    ],
                    fix_info=None,
                )
            ],
        )

    def testIssueV3_duplicateLeaves(self) -> None:
        # Duplicate leaves with the same (port, kind) should be merged and sorted
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "issue",
                  "data": {
                    "callable": "foo.bar",
                    "callable_line": 10,
                    "code": 1,
                    "line": 11,
                    "start": 12,
                    "end": 13,
                    "filename": "foo.py",
                    "message": "[UserControlled, Header] to [RCE, SQL]",
                    "sink_handle": {
                      "kind": "Call",
                      "callee": "foo.sink",
                      "index": 0,
                      "parameter": "formal(x)"
                    },
                    "master_handle": "foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    "traces": [
                      {
                        "name": "forward",
                        "roots": [
                          {
                            "receiver_interval": [
                              { "lower": 50, "upper": 51 },
                              { "lower": 60, "upper": 71 }
                            ],
                            "call": {
                              "position": {
                                "line": 14,
                                "start": 15,
                                "end": 16
                              },
                              "resolves_to": ["foo.source"],
                              "port": "result"
                            },
                            "tito_positions": [ { "line": 17, "start": 18, "end": 19 } ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 1,
                                "leaves": [ { "name": "_user_controlled_a" } ],
                                "features": [ { "always-via": "source-feature" } ]
                              },
                              {
                                "kind": "UserControlled",
                                "length": 1,
                                "leaves": [ { "name": "_user_controlled_b" } ],
                                "features": [ { "always-via": "source-feature" } ]
                              },
                              {
                                "kind": "Header",
                                "length": 2,
                                "leaves": [ { "name": "_header" } ],
                                "features": [ { "always-via": "source-other-feature" } ]
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "name": "backward",
                        "roots": [
                          {
                            "call": {
                              "position": {
                                "line": 20,
                                "start": 21,
                                "end": 22
                              },
                              "resolves_to": ["foo.sink"],
                              "port": "formal(x)[parameter]"
                            },
                            "tito_positions": [ { "line": 23, "start": 24, "end": 25 } ],
                            "kinds": [
                              {
                                "kind": "SQL",
                                "length": 2,
                                "leaves": [ { "name": "_sql" } ],
                                "features": [ { "always-via": "sink-other-feature" } ]
                              },
                              {
                                "kind": "RCE",
                                "length": 1,
                                "leaves": [ { "name": "_remote_code_execution_a" } ],
                                "features": [ { "always-via": "sink-feature" } ]
                              },
                              {
                                "kind": "RCE",
                                "length": 1,
                                "leaves": [ { "name": "_remote_code_execution_b" } ],
                                "features": [ { "always-via": "sink-feature" } ]
                              }
                            ]
                          }
                        ]
                      }
                    ],
                    "features": [
                      { "always-via": "foo" },
                      { "via": "bar" }
                    ]
                  }
                }
                """,
            expected=[
                ParseIssueTuple(
                    code=1,
                    message="[UserControlled, Header] to [RCE, SQL]",
                    callable="foo.bar",
                    handle="foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    filename="foo.py",
                    callable_line=10,
                    line=11,
                    start=13,
                    end=13,
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="foo.source",
                            port="result",
                            location=SourceLocation(
                                line_no=14,
                                begin_column=16,
                                end_column=16,
                            ),
                            leaves=[
                                ("Header", 2),
                                ("UserControlled", 1),
                            ],
                            titos=[
                                SourceLocation(
                                    line_no=17, begin_column=19, end_column=19
                                ),
                            ],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=50,
                                finish=71,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                    ],
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="foo.sink",
                            port="formal(x)[parameter]",
                            location=SourceLocation(
                                line_no=20,
                                begin_column=22,
                                end_column=22,
                            ),
                            leaves=[
                                ("RCE", 1),
                                ("SQL", 2),
                            ],
                            titos=[
                                SourceLocation(
                                    line_no=23, begin_column=25, end_column=25
                                )
                            ],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=0,
                                finish=sys.maxsize,
                                preserves_type_context=False,
                            ),
                            annotations=[],
                        ),
                    ],
                    initial_sources={
                        ("_user_controlled_a", "UserControlled", 1),
                        ("_user_controlled_b", "UserControlled", 1),
                        ("_header", "Header", 2),
                    },
                    final_sinks={
                        ("_remote_code_execution_a", "RCE", 1),
                        ("_remote_code_execution_b", "RCE", 1),
                        ("_sql", "SQL", 2),
                    },
                    features=["always-via:foo", "via:bar"],
                    fix_info=None,
                )
            ],
        )

    def testIssueV3_duplicateTitos(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "issue",
                  "data": {
                    "callable": "foo.bar",
                    "callable_line": 10,
                    "code": 1,
                    "line": 11,
                    "start": 12,
                    "end": 13,
                    "filename": "foo.py",
                    "message": "[UserControlled] to [RCE]",
                    "sink_handle": {
                      "kind": "Call",
                      "callee": "foo.sink",
                      "index": 0,
                      "parameter": "formal(x)"
                    },
                    "master_handle": "foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    "traces": [
                      {
                        "name": "forward",
                        "roots": [
                          {
                            "receiver_interval": [{ "lower": 23, "upper": 24 }],
                            "is_self_call": false,
                            "call": {
                              "position": {
                                "line": 14,
                                "start": 15,
                                "end": 16
                              },
                              "resolves_to": [
                                "foo.source"
                              ],
                              "port": "result"
                            },
                            "tito_positions": [
                              { "line": 17, "start": 18, "end": 19 },
                              { "line": 17, "start": 18, "end": 19 }
                            ],
                            "local_features": [ { "always-via": "source-local" } ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 1,
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "source-feature" } ],
                                "extra_traces": [
                                  {
                                    "call": {
                                      "position": {
                                        "line": 117,
                                        "start": 22,
                                        "end": 24
                                      },
                                      "resolves_to": [
                                        "extra_trace.transform_yz"
                                      ],
                                      "port": "formal(arg)"
                                    },
                                    "kind": "TransformY:TransformZ:ExtraTraceSink"
                                  }
                                ]
                              }
                            ]
                          }
                        ]
                      },
                      {
                        "name": "backward",
                        "roots": [
                          {
                            "caller_interval": [{
                              "lower": 10,
                              "upper": 11
                            }],
                            "is_self_call": true,
                            "call": {
                              "position": {
                                "line": 20,
                                "start": 21,
                                "end": 22
                              },
                              "resolves_to": [
                                "foo.sink"
                              ],
                              "port": "formal(x)[parameter]"
                            },
                            "tito_positions": [
                              { "line": 23, "start": 24, "end": 25 },
                              { "line": 23, "start": 24, "end": 25 }
                            ],
                            "local_features": [ { "always-via": "sink-local" } ],
                            "kinds": [
                              {
                                "kind": "RCE",
                                "length": 2,
                                "leaves": [ { "name": "_remote_code_execution" } ],
                                "features": [ { "always-via": "sink-feature" } ],
                                "extra_traces": [
                                  {
                                    "call": {
                                      "position": {
                                        "line": 117,
                                        "start": 22,
                                        "end": 24
                                      },
                                      "resolves_to": [
                                        "extra_trace.transform_yz"
                                      ],
                                      "port": "formal(arg)"
                                    },
                                    "leaf_kind": "TransformY:TransformZ:ExtraTraceSink",
                                    "trace_kind": "sink"
                                  }
                                ]
                              }
                            ]
                          }
                        ]
                      }
                    ],
                    "features": [
                      { "always-via": "foo" },
                      { "via": "bar" }
                    ]
                  }
                }
                """,
            expected=[
                ParseIssueTuple(
                    code=1,
                    message="[UserControlled] to [RCE]",
                    callable="foo.bar",
                    handle="foo.bar:1:0:Call|foo.sink|0|formal(x)",
                    filename="foo.py",
                    callable_line=10,
                    line=11,
                    start=13,
                    end=13,
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="foo.source",
                            port="result",
                            location=SourceLocation(
                                line_no=14,
                                begin_column=16,
                                end_column=16,
                            ),
                            leaves=[("UserControlled", 1)],
                            titos=[
                                SourceLocation(
                                    line_no=17, begin_column=19, end_column=19
                                ),
                            ],
                            features=[ParseTraceFeature("always-via:source-local", [])],
                            type_interval=ParseTypeInterval(
                                start=23,
                                finish=24,
                                preserves_type_context=False,
                            ),
                            annotations=[
                                ParseTraceAnnotation(
                                    location=SourceLocation(
                                        line_no=117, begin_column=23, end_column=24
                                    ),
                                    kind="tito_transform",
                                    msg="",
                                    leaf_kind="TransformY:TransformZ:ExtraTraceSink",
                                    leaf_depth=0,
                                    type_interval=None,
                                    link=None,
                                    trace_key=None,
                                    titos=[],
                                    subtraces=[
                                        ParseTraceAnnotationSubtrace(
                                            callee="extra_trace.transform_yz",
                                            port="formal(arg)",
                                            position=SourceLocation(
                                                line_no=117,
                                                begin_column=23,
                                                end_column=24,
                                            ),
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="foo.sink",
                            port="formal(x)[parameter]",
                            location=SourceLocation(
                                line_no=20,
                                begin_column=22,
                                end_column=22,
                            ),
                            leaves=[("RCE", 2)],
                            titos=[
                                SourceLocation(
                                    line_no=23, begin_column=25, end_column=25
                                )
                            ],
                            features=[ParseTraceFeature("always-via:sink-local", [])],
                            type_interval=ParseTypeInterval(
                                start=0, finish=sys.maxsize, preserves_type_context=True
                            ),
                            annotations=[
                                ParseTraceAnnotation(
                                    location=SourceLocation(
                                        line_no=117, begin_column=23, end_column=24
                                    ),
                                    kind="sink",
                                    msg="",
                                    leaf_kind="TransformY:TransformZ:ExtraTraceSink",
                                    leaf_depth=0,
                                    type_interval=None,
                                    link=None,
                                    trace_key=None,
                                    titos=[],
                                    subtraces=[
                                        ParseTraceAnnotationSubtrace(
                                            callee="extra_trace.transform_yz",
                                            port="formal(arg)",
                                            position=SourceLocation(
                                                line_no=117,
                                                begin_column=23,
                                                end_column=24,
                                            ),
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                    initial_sources={("_user_controlled", "UserControlled", 1)},
                    final_sinks={("_remote_code_execution", "RCE", 2)},
                    features=["always-via:foo", "via:bar"],
                    fix_info=None,
                )
            ],
        )

    def testSourceModelV3_userDeclared(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "sources": [
                      {
                        "port": "result",
                        "taint": [
                          {
                            "declaration": null,
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "features": [ { "always-via": "user-declared" } ]
                              }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[],
        )

    def testSourceModelV3_direct(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "filename": "foo.py",
                    "sources": [
                      {
                        "port": "result",
                        "taint": [
                          {
                            "origin": {
                              "line": 1,
                              "start": 2,
                              "end": 3
                            },
                            "tito_positions": [
                              { "line": 10, "start": 11, "end": 12 },
                              { "line": 13, "start": 14, "end": 15 }
                            ],
                            "local_features": [ { "always-via": "source-local" } ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "direct-source" } ]
                              },
                              {
                                "kind": "Header",
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "other-direct-source" } ]
                              }
                            ],
                            "caller_interval": [{
                              "lower": 10,
                              "upper": 11
                            }],
                            "receiver_interval": [
                              { "lower": 25, "upper": 30 },
                              { "lower": 35, "upper": 40 }
                            ],
                            "is_self_call": false
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="_user_controlled",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[
                        ("Header", 0),
                        ("UserControlled", 0),
                    ],
                    caller_port="result",
                    callee_port="source",
                    type_interval=ParseTypeInterval(
                        start=25, finish=40, preserves_type_context=False
                    ),
                    features=[ParseTraceFeature("always-via:source-local", [])],
                    annotations=[],
                )
            ],
        )

    def testSourceModelV3_directWithPortsOnLeaves(self) -> None:
        # (e.g, cross-repo),
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "filename": "foo.py",
                    "sources": [
                      {
                        "port": "result",
                        "taint": [
                          {
                            "origin": {
                              "line": 1,
                              "start": 2,
                              "end": 3
                            },
                            "tito_positions": [
                              { "line": 10, "start": 11, "end": 12 },
                              { "line": 13, "start": 14, "end": 15 }
                            ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "leaves": [
                                  {
                                    "name": "_user_controlled"
                                  },
                                  {
                                    "name": "_cross_repo",
                                    "port": "producer:1:result"
                                  },
                                  {
                                    "name": "_cross_repo_other",
                                    "port": "producer:1:result"
                                  },
                                  {
                                    "name": "_cross_repo",
                                    "port": "producer:2:result"
                                  }
                                ],
                                "features": [ { "always-via": "direct-source" } ],
                                "extra_traces": [
                                  {
                                    "call": {
                                      "position": { "line": 59, "start": 32, "end": 34 },
                                      "resolves_to": [ "extra_trace.nested_transform_x" ],
                                      "port": "formal(arg)"
                                    },
                                    "leaf_kind": "TransformX:ExtraTraceSink",
                                    "trace_kind": "tito_transform"
                                  }
                                ]
                              },
                              {
                                "kind": "Header",
                                "leaves": [
                                  {
                                    "kind": "Header",
                                    "name": "_cross_repo",
                                    "port": "producer:1:result"
                                  }
                                ],
                                "features": [ { "always-via": "cross-repo-source" } ],
                                "extra_traces": [
                                  {
                                    "call": {
                                      "position": { "line": 59, "start": 32, "end": 34 },
                                      "resolves_to": [ "extra_trace.nested_transform_x" ],
                                      "port": "formal(arg)"
                                    },
                                    "leaf_kind": "TransformX:ExtraTraceSink",
                                    "trace_kind": "tito_transform"
                                  }
                                ]
                              }
                            ],
                            "receiver_interval": [{ "lower": 26, "upper": 31 }],
                            "is_self_call": true
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="_user_controlled",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("UserControlled", 0)],
                    caller_port="result",
                    callee_port="source",
                    type_interval=ParseTypeInterval(
                        start=26, finish=31, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=59, begin_column=33, end_column=34
                            ),
                            kind="tito_transform",
                            msg="",
                            leaf_kind="TransformX:ExtraTraceSink",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[
                                ParseTraceAnnotationSubtrace(
                                    callee="extra_trace.nested_transform_x",
                                    port="formal(arg)",
                                    position=SourceLocation(
                                        line_no=59, begin_column=33, end_column=34
                                    ),
                                )
                            ],
                        )
                    ],
                ),
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="_cross_repo",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[
                        ("Header", 0),
                        ("UserControlled", 0),
                    ],
                    caller_port="result",
                    callee_port="producer:1:result",
                    type_interval=ParseTypeInterval(
                        start=26, finish=31, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=59, begin_column=33, end_column=34
                            ),
                            kind="tito_transform",
                            msg="",
                            leaf_kind="TransformX:ExtraTraceSink",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[
                                ParseTraceAnnotationSubtrace(
                                    callee="extra_trace.nested_transform_x",
                                    port="formal(arg)",
                                    position=SourceLocation(
                                        line_no=59, begin_column=33, end_column=34
                                    ),
                                )
                            ],
                        )
                    ],
                ),
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="_cross_repo_other",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("UserControlled", 0)],
                    caller_port="result",
                    callee_port="producer:1:result",
                    type_interval=ParseTypeInterval(
                        start=26, finish=31, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=59, begin_column=33, end_column=34
                            ),
                            kind="tito_transform",
                            msg="",
                            leaf_kind="TransformX:ExtraTraceSink",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[
                                ParseTraceAnnotationSubtrace(
                                    callee="extra_trace.nested_transform_x",
                                    port="formal(arg)",
                                    position=SourceLocation(
                                        line_no=59, begin_column=33, end_column=34
                                    ),
                                ),
                            ],
                        )
                    ],
                ),
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="_cross_repo",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("UserControlled", 0)],
                    caller_port="result",
                    callee_port="producer:2:result",
                    type_interval=ParseTypeInterval(
                        start=26, finish=31, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=59, begin_column=33, end_column=34
                            ),
                            kind="tito_transform",
                            msg="",
                            leaf_kind="TransformX:ExtraTraceSink",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[
                                ParseTraceAnnotationSubtrace(
                                    callee="extra_trace.nested_transform_x",
                                    port="formal(arg)",
                                    position=SourceLocation(
                                        line_no=59, begin_column=33, end_column=34
                                    ),
                                )
                            ],
                        )
                    ],
                ),
            ],
        )

    def testSourceModelV3_indirect(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "filename": "foo.py",
                    "sources": [
                      {
                        "port": "result[field]",
                        "taint": [
                          {
                            "call": {
                              "position": {
                                "line": 1,
                                "start": 2,
                                "end": 3
                              },
                              "resolves_to": [
                                "foo.source"
                              ],
                              "port": "result[attribute]"
                            },
                            "tito_positions": [
                              { "line": 10, "start": 11, "end": 12 },
                              { "line": 13, "start": 14, "end": 15 }
                            ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 2,
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "direct-source" } ]
                              },
                              {
                                "kind": "Header",
                                "length": 3,
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "direct-source" } ]
                              }
                            ],
                            "caller_interval": [
                              {
                                "lower": 11,
                                "upper": 12
                              },
                              {
                                "lower": 15,
                                "upper": 20
                              }
                            ],
                            "is_self_call": false
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="foo.source",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[
                        ("Header", 3),
                        ("UserControlled", 2),
                    ],
                    caller_port="result[field]",
                    callee_port="result[attribute]",
                    type_interval=ParseTypeInterval(
                        start=0, finish=sys.maxsize, preserves_type_context=False
                    ),
                    features=[],
                    annotations=[],
                )
            ],
        )

    def testSourceModelV3_indirectWithMultipleCallees(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "filename": "foo.py",
                    "sources": [
                      {
                        "port": "result",
                        "taint": [
                          {
                            "call": {
                              "position": {
                                "line": 1,
                                "start": 2,
                                "end": 3
                              },
                              "resolves_to": [
                                "foo.source",
                                "foo.other_source"
                              ],
                              "port": "result[attribute]"
                            },
                            "tito_positions": [
                              { "line": 10, "start": 11, "end": 12 },
                              { "line": 13, "start": 14, "end": 15 }
                            ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 2,
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "direct-source" } ]
                              }
                            ],
                            "caller_interval": [
                              {
                                "lower": 12,
                                "upper": 13
                              }
                            ],
                            "is_self_call": true
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="foo.source",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("UserControlled", 2)],
                    caller_port="result",
                    callee_port="result[attribute]",
                    type_interval=ParseTypeInterval(
                        start=0, finish=sys.maxsize, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[],
                ),
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="foo.other_source",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("UserControlled", 2)],
                    caller_port="result",
                    callee_port="result[attribute]",
                    type_interval=ParseTypeInterval(
                        start=0, finish=sys.maxsize, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[],
                ),
            ],
        )

    def testSourceModelV3_combinedOldAndNewSubtraceSyntax(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "filename": "foo.py",
                    "sources": [
                      {
                        "port": "result",
                        "taint": [
                          {
                            "call": {
                              "position": {
                                "line": 1,
                                "start": 2,
                                "end": 3
                              },
                              "resolves_to": [
                                "foo.source"
                              ],
                              "port": "result"
                            },
                            "tito_positions": [
                              { "line": 10, "start": 11, "end": 12 },
                              { "line": 13, "start": 14, "end": 15 }
                            ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 1,
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "indirect-source" } ]
                              },
                              {
                                "kind": "Header",
                                "length": 2,
                                "leaves": [ { "name": "_header" } ],
                                "features": [ { "always-via": "indirect-source" } ],
                                "extra_traces": [
                                  {
                                    "call": {
                                      "position": { "line": 19, "start": 20, "end": 21 },
                                      "resolves_to": [ "extra_trace.nested_transform_y" ],
                                      "port": "formal(arg)"
                                    },
                                    "leaf_kind": "TransformY:ExtraTraceSink",
                                    "trace_kind": "tito_transform"
                                  }
                                ]
                              }
                            ],
                            "is_self_call": false,
                            "extra_traces": [
                              {
                                "call": {
                                  "position": { "line": 16, "start": 17, "end": 18 },
                                  "resolves_to": [ "extra_trace.nested_transform_x" ],
                                  "port": "formal(arg)"
                                },
                                "leaf_kind": "TransformX:ExtraTraceSink",
                                "trace_kind": "tito_transform"
                              }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="foo.source",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("UserControlled", 1)],
                    caller_port="result",
                    callee_port="result",
                    type_interval=ParseTypeInterval(
                        start=0,
                        finish=sys.maxsize,
                        preserves_type_context=False,
                    ),
                    features=[],
                    annotations=[
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=16, begin_column=18, end_column=18
                            ),
                            kind="tito_transform",
                            msg="",
                            leaf_kind="TransformX:ExtraTraceSink",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[
                                ParseTraceAnnotationSubtrace(
                                    callee="extra_trace.nested_transform_x",
                                    port="formal(arg)",
                                    position=SourceLocation(
                                        line_no=16,
                                        begin_column=18,
                                        end_column=18,
                                    ),
                                )
                            ],
                        )
                    ],
                ),
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="foo.source",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("Header", 2)],
                    caller_port="result",
                    callee_port="result",
                    type_interval=ParseTypeInterval(
                        start=0,
                        finish=sys.maxsize,
                        preserves_type_context=False,
                    ),
                    features=[],
                    annotations=[
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=16, begin_column=18, end_column=18
                            ),
                            kind="tito_transform",
                            msg="",
                            leaf_kind="TransformX:ExtraTraceSink",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[
                                ParseTraceAnnotationSubtrace(
                                    callee="extra_trace.nested_transform_x",
                                    port="formal(arg)",
                                    position=SourceLocation(
                                        line_no=16,
                                        begin_column=18,
                                        end_column=18,
                                    ),
                                )
                            ],
                        ),
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=19, begin_column=21, end_column=21
                            ),
                            kind="tito_transform",
                            msg="",
                            leaf_kind="TransformY:ExtraTraceSink",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[
                                ParseTraceAnnotationSubtrace(
                                    callee="extra_trace.nested_transform_y",
                                    port="formal(arg)",
                                    position=SourceLocation(
                                        line_no=19,
                                        begin_column=21,
                                        end_column=21,
                                    ),
                                )
                            ],
                        ),
                    ],
                ),
            ],
        )

    def testSourceModelV3_kindSpecificBreadcrumbs(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "filename": "foo.py",
                    "sources": [
                      {
                        "port": "result",
                        "taint": [
                          {
                            "call": {
                              "position": {
                                "line": 1,
                                "start": 2,
                                "end": 3
                              },
                              "resolves_to": [
                                "foo.source"
                              ],
                              "port": "result"
                            },
                            "tito_positions": [
                              { "line": 10, "start": 11, "end": 12 },
                              { "line": 13, "start": 14, "end": 15 }
                            ],
                            "local_features": [
                                { "always-via": "shared-breadcrumb" },
                                { "always-via": "other-shared-breadcrumb" }
                            ],
                            "kinds": [
                              {
                                "kind": "UserControlled",
                                "length": 1,
                                "leaves": [ { "name": "_user_controlled" } ],
                                "features": [ { "always-via": "indirect-source" } ],
                                "local_features": [ { "always-via": "user-controlled-breadcrumb" } ]
                              },
                              {
                                "kind": "Header",
                                "length": 2,
                                "leaves": [ { "name": "_header" } ],
                                "features": [ { "always-via": "indirect-source" } ],
                                "local_features": [ { "always-via": "header-breadcrumb" } ]
                              }
                            ],
                            "is_self_call": false
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="foo.source",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("UserControlled", 1)],
                    caller_port="result",
                    callee_port="result",
                    type_interval=ParseTypeInterval(
                        start=0,
                        finish=sys.maxsize,
                        preserves_type_context=False,
                    ),
                    features=[
                        ParseTraceFeature("always-via:other-shared-breadcrumb", []),
                        ParseTraceFeature("always-via:shared-breadcrumb", []),
                        ParseTraceFeature("always-via:user-controlled-breadcrumb", []),
                    ],
                    annotations=[],
                ),
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="foo.bar",
                    callee="foo.source",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("Header", 2)],
                    caller_port="result",
                    callee_port="result",
                    type_interval=ParseTypeInterval(
                        start=0,
                        finish=sys.maxsize,
                        preserves_type_context=False,
                    ),
                    features=[
                        ParseTraceFeature("always-via:header-breadcrumb", []),
                        ParseTraceFeature("always-via:other-shared-breadcrumb", []),
                        ParseTraceFeature("always-via:shared-breadcrumb", []),
                    ],
                    annotations=[],
                ),
            ],
        )

    def testSinkModelV3_direct(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "filename": "foo.py",
                    "sinks": [
                      {
                        "port": "formal(x)",
                        "taint": [
                          {
                            "origin": {
                              "line": 1,
                              "start": 2,
                              "end": 3
                            },
                            "tito_positions": [
                              { "line": 10, "start": 11, "end": 12 },
                              { "line": 13, "start": 14, "end": 15 }
                            ],
                            "local_features": [ { "always-via": "local-sink" } ],
                            "kinds": [
                              {
                                "kind": "SQL",
                                "leaves": [ { "name": "_sql" } ],
                                "features": [ { "always-via": "direct-sink" } ]
                              },
                              {
                                "kind": "RCE",
                                "leaves": [ { "name": "_sql" } ],
                                "features": [ { "always-via": "other-direct-sink" } ]
                              }
                            ],
                            "caller_interval": [
                              {
                                "lower": 13,
                                "upper": 14
                              }
                            ],
                            "receiver_interval": [{ "lower": 27, "upper": 32 }],
                            "is_self_call": false
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="foo.bar",
                    callee="_sql",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[
                        ("RCE", 0),
                        ("SQL", 0),
                    ],
                    caller_port="formal(x)",
                    callee_port="sink",
                    type_interval=ParseTypeInterval(
                        start=27, finish=32, preserves_type_context=False
                    ),
                    features=[ParseTraceFeature("always-via:local-sink", [])],
                    annotations=[],
                )
            ],
        )

    def testSinkModelV3_indirect(self) -> None:
        self.assertParsed(
            version=3,
            input="""
                {
                  "kind": "model",
                  "data": {
                    "callable": "foo.bar",
                    "filename": "foo.py",
                    "sinks": [
                      {
                        "port": "formal(x)",
                        "taint": [
                          {
                            "call": {
                              "position": {
                                "line": 1,
                                "start": 2,
                                "end": 3
                              },
                              "resolves_to": [
                                "foo.sink"
                              ],
                              "port": "formal(y)[attribute]"
                            },
                            "tito_positions": [
                              { "line": 10, "start": 11, "end": 12 },
                              { "line": 13, "start": 14, "end": 15 }
                            ],
                            "kinds": [
                              {
                                "kind": "RCE",
                                "length": 2,
                                "leaves": [ { "name": "_sink_leaf" } ],
                                "features": [ { "always-via": "direct-sink" } ]
                              },
                              {
                                "kind": "SQL",
                                "length": 3,
                                "leaves": [ { "name": "_sink_leaf" } ],
                                "features": [ { "always-via": "direct-sink" } ]
                              }
                            ],
                            "caller_interval": [
                              {
                                "lower": 17,
                                "upper": 18
                              },
                              {
                                "lower": 20,
                                "upper": 28
                              }
                            ],
                            "is_self_call": false
                          }
                        ]
                      }
                    ]
                  }
                }
                """,
            expected=[
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="foo.bar",
                    callee="foo.sink",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=3,
                        end_column=3,
                    ),
                    filename="foo.py",
                    titos=[
                        SourceLocation(line_no=10, begin_column=12, end_column=12),
                        SourceLocation(line_no=13, begin_column=15, end_column=15),
                    ],
                    leaves=[("RCE", 2), ("SQL", 3)],
                    caller_port="formal(x)",
                    callee_port="formal(y)[attribute]",
                    type_interval=ParseTypeInterval(
                        start=0,
                        finish=sys.maxsize,
                        preserves_type_context=False,
                    ),
                    features=[],
                    annotations=[],
                )
            ],
        )

    def _parse(self, version, body):
        document = '{"file_version":%d}\n%s' % (version, "".join(body.split("\n")))
        analysis_output = AnalysisOutput(
            directory="/output/directory",
            filename_specs=["taint-output.json"],
            file_handle=io.StringIO(document),
            metadata=Metadata(
                repo_roots={"/analysis/root"},
                rules={1: Rule(name="TestRule", description="Test Rule Description")},
            ),
        )
        return PysaParser().parse_analysis_output(analysis_output)

    def testUnsupportedFileVersionRaises(self) -> None:
        with self.assertRaises(ParseError):
            self._parse(2, "")
        with self.assertRaises(ParseError):
            self._parse(4, "")


class TestMarianaTrenchParser(unittest.TestCase):
    class ParseError(Exception):
        """Exception thrown by assertParsed when parsing fails. Used to assert errors"""

        pass

    def assertParsed(
        self,
        output: str,
        expected: Iterable[Union[ParseConditionTuple, ParseIssueTuple]],
    ) -> None:
        output = "".join(output.split("\n"))  # Flatten json-line.
        parser = MarianaParser()
        analysis_output = AnalysisOutput(
            directory="/output/directory",
            filename_specs=["models.json"],
            file_handle=io.StringIO(output),
            metadata=Metadata(
                repo_roots={"/analysis/root"},
                analysis_tool_version="0.2",
                rules={1: Rule(name="TestRule", description="Test Rule Description")},
            ),
        )

        def sort_entry(e: Union[ParseConditionTuple, ParseIssueTuple]) -> str:
            if isinstance(e, ParseConditionTuple):
                return e.caller
            else:
                return e.callable

        try:
            issues_and_frames = parser.parse_analysis_output(analysis_output)
        except Exception as e:
            raise TestMarianaTrenchParser.ParseError() from e
        entries = (
            issues_and_frames.issues
            + list(issues_and_frames.preconditions.all_frames())
            + list(issues_and_frames.postconditions.all_frames())
        )
        self.assertEqual(
            [
                (_e._replace(handle="") if isinstance(_e, ParseIssueTuple) else _e)
                for _e in sorted(entries, key=sort_entry)
            ],
            [
                (_x._replace(handle="") if isinstance(_x, ParseIssueTuple) else _x)
                for _x in expected
            ],
        )

    def testEmptyModels(self) -> None:
        self.assertParsed(
            """
                {
                  "method": "LClass;.method:()V",
                  "position": {
                    "line": 1,
                    "path": "Class.java"
                  }
                }
                """,
            [],
        )
        self.assertParsed(
            """
                {
                  "fields": "LClass;.field",
                  "sources": "some field model sources",
                  "sinks": "some field model sinks"
                }
                """,
            [],
        )

    def testParseErrors(self) -> None:
        with self.assertRaises(TestMarianaTrenchParser.ParseError):
            # Many fields missing from "issue", like "position"
            self.assertParsed(
                """
                    {
                      "method": "LClass;.method:()V",
                      "position": {
                        "line": 1,
                        "path": "Class.java"
                      },
                      "issues": [
                        {
                          "rule": 1
                        }
                      ]
                    }
                    """,
                [],
            )

        with self.assertRaises(TestMarianaTrenchParser.ParseError):
            # Invalid json (note missing closing brackets)
            self.assertParsed(
                """
                    {
                      "method": {"name": "LClass;.method:()V"},
                      "position": {
                        "line": 1,
                        "path": "Class.java"
                      }
                    """,
                [],
            )

        with self.assertRaises(TestMarianaTrenchParser.ParseError):
            # Invalid json on field model (note trailing comma)
            self.assertParsed(
                """
                    {
                      "fields": "LClass;.field",
                      "sources": "some field model sources",
                      "sinks": "some field model sinks",
                    }
                    """,
                [],
            )

    def testModelWithIssue(self) -> None:
        self.assertParsed(
            """
                {
                  "method": "LClass;.flow:()V",
                  "issues": [
                    {
                      "rule": 1,
                      "position": {
                        "path": "Flow.java",
                        "line": 10,
                        "start": 11,
                        "end": 12
                      },
                      "callee": "LSink;.sink:(LData;)V",
                      "sink_index": "0",
                      "sinks": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Flow.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 2,
                              "always_features": ["via-parameter-field"],
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 13, "start": 14, "end": 15}],
                          "local_features": { "always_features": ["via-parameter-field"] }
                        }
                      ],
                      "sources": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Flow.java",
                              "line": 20,
                              "start": 21,
                              "end": 22
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 3,
                              "may_features": ["via-obscure"],
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [
                            {"line": 23, "start": 24, "end": 25},
                            {"line": 26, "start": 27, "end": 28}
                          ]
                        }
                      ],
                      "may_features": ["via-obscure"],
                      "always_features": ["via-parameter-field"]
                    }
                  ],
                  "position": {
                    "line": 2,
                    "path": "Flow.java"
                  }
                }
                """,
            [
                ParseIssueTuple(
                    code=1,
                    message="TestRule: Test Rule Description",
                    callable="LClass;.flow:()V",
                    handle="LClass;.flow:()V:LSink;.sink:(LData;)V:0:1:1ef9022f932a64d0",
                    filename="Flow.java",
                    callable_line=2,
                    line=10,
                    start=12,
                    end=13,
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="LSink;.sink:(LData;)V",
                            port="argument(1)",
                            location=SourceLocation(
                                line_no=10,
                                begin_column=12,
                                end_column=13,
                            ),
                            leaves=[("TestSink", 2)],
                            titos=[
                                SourceLocation(
                                    line_no=13, begin_column=15, end_column=16
                                )
                            ],
                            features=[
                                ParseTraceFeature("always-via-parameter-field", []),
                            ],
                            type_interval=None,
                            annotations=[],
                        )
                    ],
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="LSource;.source:()LData;",
                            port="result",
                            location=SourceLocation(
                                line_no=20,
                                begin_column=22,
                                end_column=23,
                            ),
                            leaves=[("TestSource", 3)],
                            titos=[
                                SourceLocation(
                                    line_no=23, begin_column=25, end_column=26
                                ),
                                SourceLocation(
                                    line_no=26, begin_column=28, end_column=29
                                ),
                            ],
                            features=[],
                            type_interval=None,
                            annotations=[],
                        )
                    ],
                    initial_sources={("LSource;.source:(LData;)V", "TestSource", 3)},
                    final_sinks={("LSink;.sink:(LData;)V", "TestSink", 2)},
                    features=[
                        "always-via-parameter-field",
                        "via-obscure",
                    ],
                    fix_info=None,
                )
            ],
        )
        self.assertParsed(
            """
                {
                  "method": "LClass;.flow:()V",
                  "issues": [
                    {
                      "rule": 1,
                      "position": {
                        "path": "Flow.java",
                        "line": 10,
                        "start": 11,
                        "end": 12
                      },
                      "callee": "LSink;.sink:(LData;)V",
                      "sink_index": "1",
                      "sinks": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Flow.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 2,
                              "always_features": ["via-parameter-field"],
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 13, "start": 14, "end": 15}]
                        },
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Flow.java",
                              "line": 20,
                              "start": 21,
                              "end": 22
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 3,
                              "always_features": ["via-obscure"],
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.other_sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ]
                        }
                      ],
                      "sources": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Flow.java",
                              "line": 30,
                              "start": 31,
                              "end": 32
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 3,
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 33, "start": 34, "end": 35}],
                          "local_features": {"always_features": ["via-obscure"]}
                       }
                      ],
                      "may_features": ["via-obscure", "via-parameter-field"]
                    }
                  ],
                  "position": {
                    "line": 2,
                    "path": "Flow.java"
                  }
                }
                """,
            [
                ParseIssueTuple(
                    code=1,
                    message="TestRule: Test Rule Description",
                    callable="LClass;.flow:()V",
                    handle="LClass;.flow:()V:LSink;.sink:(LData;)V:1:1:e7653955345a4ce9",
                    filename="Flow.java",
                    callable_line=2,
                    line=10,
                    start=12,
                    end=13,
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="LSink;.sink:(LData;)V",
                            port="argument(1)",
                            location=SourceLocation(
                                line_no=10,
                                begin_column=12,
                                end_column=13,
                            ),
                            leaves=[("TestSink", 2)],
                            titos=[
                                SourceLocation(
                                    line_no=13, begin_column=15, end_column=16
                                )
                            ],
                            features=[],
                            type_interval=None,
                            annotations=[],
                        ),
                        ParseIssueConditionTuple(
                            callee="LSink;.sink:(LData;)V",
                            port="argument(1)",
                            location=SourceLocation(
                                line_no=20,
                                begin_column=22,
                                end_column=23,
                            ),
                            leaves=[("TestSink", 3)],
                            titos=[],
                            features=[],
                            type_interval=None,
                            annotations=[],
                        ),
                    ],
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="LSource;.source:()LData;",
                            port="result",
                            location=SourceLocation(
                                line_no=30,
                                begin_column=32,
                                end_column=33,
                            ),
                            leaves=[("TestSource", 3)],
                            titos=[
                                SourceLocation(
                                    line_no=33, begin_column=35, end_column=36
                                )
                            ],
                            features=[ParseTraceFeature("always-via-obscure", [])],
                            type_interval=None,
                            annotations=[],
                        )
                    ],
                    initial_sources={("LSource;.source:(LData;)V", "TestSource", 3)},
                    final_sinks={
                        ("LSink;.sink:(LData;)V", "TestSink", 2),
                        ("LSink;.other_sink:(LData;)V", "TestSink", 3),
                    },
                    features=["via-obscure", "via-parameter-field"],
                    fix_info=None,
                )
            ],
        )
        self.assertParsed(
            """
                {
                  "method": "LClass;.flow:()V",
                  "issues": [
                    {
                      "rule": 1,
                      "position": {
                        "path": "Flow.java",
                        "line": 10,
                        "start": 11,
                        "end": 12
                      },
                      "callee": "LSink;.sink:(LData;)V",
                      "sink_index": "2",
                      "sinks": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Flow.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 2,
                              "always_features": ["via-parameter-field"],
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 13, "start": 14, "end": 15}]
                      }
                      ],
                      "sources": [
                        {
                          "call_info": {
                            "call_kind": "Origin"
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "distance": 0,
                              "kind": "TestSource",
                              "origins": [
                                { "field": "LSource;.sourceField:LData;" }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 33, "start": 34, "end": 35}]
                        }
                      ],
                      "may_features": ["via-obscure", "via-parameter-field"]
                    }
                  ],
                  "position": {
                    "line": 2,
                    "path": "Flow.java"
                  }
                }
                """,
            [
                ParseIssueTuple(
                    code=1,
                    message="TestRule: Test Rule Description",
                    callable="LClass;.flow:()V",
                    handle="LClass;.flow:()V:LSink;.sink:(LData;)V:2:1:4a78c3ad238e0bf7",
                    filename="Flow.java",
                    callable_line=2,
                    line=10,
                    start=12,
                    end=13,
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="LSink;.sink:(LData;)V",
                            port="argument(1)",
                            location=SourceLocation(
                                line_no=10,
                                begin_column=12,
                                end_column=13,
                            ),
                            leaves=[("TestSink", 2)],
                            titos=[
                                SourceLocation(
                                    line_no=13, begin_column=15, end_column=16
                                )
                            ],
                            features=[],
                            type_interval=None,
                            annotations=[],
                        )
                    ],
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="LSource;.sourceField:LData;",
                            port="source",
                            location=SourceLocation(
                                line_no=2,
                                begin_column=1,
                                end_column=1,
                            ),
                            leaves=[("TestSource", 0)],
                            titos=[
                                SourceLocation(
                                    line_no=33, begin_column=35, end_column=36
                                )
                            ],
                            features=[],
                            type_interval=None,
                            annotations=[],
                        )
                    ],
                    initial_sources={("LSource;.sourceField:LData;", "TestSource", 0)},
                    final_sinks={
                        ("LSink;.sink:(LData;)V", "TestSink", 2),
                    },
                    features=["via-obscure", "via-parameter-field"],
                    fix_info=None,
                )
            ],
        )

        # Multiple callees, local_positions/features and kinds
        # (and origins within kinds)
        self.assertParsed(
            """
                {
                  "method": "LClass;.flow:()V",
                  "issues": [
                    {
                      "rule": 1,
                      "position": {
                        "path": "Flow.java",
                        "line": 10,
                        "start": 11,
                        "end": 12
                      },
                      "callee": "LSink;.sink:(LData;)V",
                      "sink_index": "3",
                      "sinks": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Flow.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 2,
                              "always_features": ["via-parameter-field"],
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 13, "start": 14, "end": 15}]
                        },
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink2:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Flow.java",
                              "line": 11,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 3,
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            },
                            {
                              "call_kind": "CallSite",
                              "distance": 1,
                              "kind": "TestSink2",
                              "origins": [
                                {
                                  "method": "LSink;.sink3:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 14, "start": 14, "end": 15}]
                        }
                      ],
                      "sources": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Flow.java",
                              "line": 30,
                              "start": 31,
                              "end": 32
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 3,
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 33, "start": 34, "end": 35}],
                          "local_features": {"always_features": ["via-obscure"]}
                        },
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source2:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Flow.java",
                              "line": 31,
                              "start": 31,
                              "end": 32
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 4,
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            },
                            {
                              "call_kind": "CallSite",
                              "distance": 5,
                              "kind": "TestSource2",
                              "origins": [
                                {
                                  "method": "LSource;.source3:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ]
                        }
                      ],
                      "may_features": ["via-obscure", "via-parameter-field"]
                    }
                  ],
                  "position": {
                    "line": 2,
                    "path": "Flow.java"
                  }
                }
                """,
            [
                ParseIssueTuple(
                    code=1,
                    message="TestRule: Test Rule Description",
                    callable="LClass;.flow:()V",
                    handle="LClass;.flow:()V:LSink;.sink:(LData;)V:3:1:4172bb4962984471",
                    filename="Flow.java",
                    callable_line=2,
                    line=10,
                    start=12,
                    end=13,
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="LSink;.sink:(LData;)V",
                            port="argument(1)",
                            location=SourceLocation(
                                line_no=10,
                                begin_column=12,
                                end_column=13,
                            ),
                            leaves=[("TestSink", 2)],
                            titos=[
                                SourceLocation(
                                    line_no=13, begin_column=15, end_column=16
                                )
                            ],
                            features=[],
                            type_interval=None,
                            annotations=[],
                        ),
                        ParseIssueConditionTuple(
                            callee="LSink;.sink2:(LData;)V",
                            port="argument(1)",
                            location=SourceLocation(
                                line_no=11,
                                begin_column=12,
                                end_column=13,
                            ),
                            leaves=[("TestSink", 3), ("TestSink2", 1)],
                            titos=[
                                SourceLocation(
                                    line_no=14, begin_column=15, end_column=16
                                )
                            ],
                            features=[],
                            type_interval=None,
                            annotations=[],
                        ),
                    ],
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="LSource;.source:()LData;",
                            port="result",
                            location=SourceLocation(
                                line_no=30,
                                begin_column=32,
                                end_column=33,
                            ),
                            leaves=[("TestSource", 3)],
                            titos=[
                                SourceLocation(
                                    line_no=33, begin_column=35, end_column=36
                                )
                            ],
                            features=[ParseTraceFeature("always-via-obscure", [])],
                            type_interval=None,
                            annotations=[],
                        ),
                        ParseIssueConditionTuple(
                            callee="LSource;.source2:()LData;",
                            port="result",
                            location=SourceLocation(
                                line_no=31,
                                begin_column=32,
                                end_column=33,
                            ),
                            leaves=[("TestSource", 4), ("TestSource2", 5)],
                            titos=[],
                            features=[],
                            type_interval=None,
                            annotations=[],
                        ),
                    ],
                    initial_sources={
                        ("LSource;.source:(LData;)V", "TestSource", 3),
                        ("LSource;.source:(LData;)V", "TestSource", 4),
                        ("LSource;.source3:(LData;)V", "TestSource2", 5),
                    },
                    final_sinks={
                        ("LSink;.sink:(LData;)V", "TestSink", 2),
                        ("LSink;.sink:(LData;)V", "TestSink", 3),
                        ("LSink;.sink3:(LData;)V", "TestSink2", 1),
                    },
                    features=["via-obscure", "via-parameter-field"],
                    fix_info=None,
                )
            ],
        )

    def testModelPostconditions(self) -> None:
        # Leaf case.
        self.assertParsed(
            """
                {
                  "method": "LSource;.source:()V",
                  "generations": [
                    {
                      "port": "Return",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Declaration"
                          },
                          "kinds": [
                            {
                              "call_kind": "Declaration",
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:()V",
                                  "port": "Return"
                                }
                              ]
                            }
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Source.java"
                  }
                }
                """,
            [],
        )

        # Origin case.
        self.assertParsed(
            """
                {
                  "method": "LClass;.indirect_source:()V",
                  "generations": [
                    {
                      "port": "Return",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "always_features": ["via-parameter-field"],
                              "distance": 0,
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:()V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_features": {
                            "always_features": ["via-obscure"],
                            "may_features": ["via-taint-in-taint-out"]
                          },
                          "local_positions": [
                            {"line": 13, "start": 14, "end": 15},
                            {"line": 16, "start": 17, "end": 18}
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Class.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="LClass;.indirect_source:()V",
                    callee="LSource;.source:()V",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Class.java",
                    titos=[
                        SourceLocation(line_no=13, begin_column=15, end_column=16),
                        SourceLocation(line_no=16, begin_column=18, end_column=19),
                    ],
                    leaves=[("TestSource", 0)],
                    caller_port="result",
                    callee_port="source:argument(1)",
                    type_interval=None,
                    features=[
                        ParseTraceFeature("always-via-obscure", []),
                        ParseTraceFeature("via-taint-in-taint-out", []),
                    ],
                    annotations=[],
                )
            ],
        )

        # Origin with parameter type overrides.
        self.assertParsed(
            """
                {
                  "method": "LClass;.indirect_source:()V",
                  "generations": [
                    {
                      "port": "Return",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "distance": 1,
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": {
                                    "name": "LSource;.source:()V",
                                    "parameter_type_overrides": [
                                      {
                                        "parameter": 0,
                                        "type": "LAnonymous$0;"
                                      },
                                      {
                                        "parameter": 1,
                                        "type": "LAnonymous$1;"
                                      }
                                    ]
                                  },
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [
                            {"line": 13, "start": 14, "end": 15},
                            {"line": 16, "start": 17, "end": 18}
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Class.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="LClass;.indirect_source:()V",
                    callee="LSource;.source:()V[0: LAnonymous$0;, 1: LAnonymous$1;]",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Class.java",
                    titos=[
                        SourceLocation(line_no=13, begin_column=15, end_column=16),
                        SourceLocation(line_no=16, begin_column=18, end_column=19),
                    ],
                    leaves=[("TestSource", 1)],
                    caller_port="result",
                    callee_port="source:argument(1)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                )
            ],
        )

        # CallSite case.
        self.assertParsed(
            """
                {
                  "method": "LClass;.indirect_source:()V",
                  "generations": [
                    {
                      "port": "Return",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 1,
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:()V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [
                            {"line": 13, "start": 14, "end": 15},
                            {"line": 16, "start": 17, "end": 18}
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Class.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="LClass;.indirect_source:()V",
                    callee="LSource;.source:()LData;",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Class.java",
                    titos=[
                        SourceLocation(line_no=13, begin_column=15, end_column=16),
                        SourceLocation(line_no=16, begin_column=18, end_column=19),
                    ],
                    leaves=[("TestSource", 1)],
                    caller_port="result",
                    callee_port="result",
                    type_interval=None,
                    features=[],
                    annotations=[],
                )
            ],
        )

        # Test with a complex port.
        self.assertParsed(
            """
                {
                  "method": "LSource;.source_wrapper:()V",
                  "generations": [
                    {
                      "port": "Return.x.y",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin"
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:()V",
                                  "port": "Return"
                                }
                              ]
                            }
                          ],
                          "local_features": {
                            "may_features": ["via-source"]
                          }
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Source.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="LSource;.source_wrapper:()V",
                    callee="LSource;.source:()V",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="Source.java",
                    titos=[],
                    leaves=[("TestSource", 0)],
                    caller_port="result.x.y",
                    callee_port="source:result",
                    type_interval=None,
                    features=[ParseTraceFeature("via-source", [])],
                    annotations=[],
                )
            ],
        )

        # Test multiple caller ports, callees and kinds (leaves)
        self.assertParsed(
            """
                {
                  "method": "LSource;.source_wrapper:(I)V",
                  "generations": [
                    {
                      "port": "Return",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin"
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:(I)V",
                                  "port": "Return"
                                }
                              ]
                            },
                            {
                              "call_kind": "Origin",
                              "kind": "TestSource2",
                              "origins": [
                                {
                                  "method": "LSource;.source:(I)V",
                                  "port": "Return"
                                }
                              ]
                            }
                          ]
                        },
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source1:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "kind": "TestSource",
                              "distance": 1
                            },
                            {
                              "call_kind": "CallSite",
                              "kind": "TestSource2",
                              "distance": 2
                            }
                          ]
                        }
                      ]
                    },
                    {
                      "port": "Argument(1)",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source2:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "kind": "TestSource",
                              "distance": 3
                            }
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Source.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="LSource;.source_wrapper:(I)V",
                    callee="LSource;.source:(I)V",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="Source.java",
                    titos=[],
                    leaves=[("TestSource", 0), ("TestSource2", 0)],
                    caller_port="result",
                    callee_port="source:result",
                    type_interval=None,
                    features=[],
                    annotations=[],
                ),
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="LSource;.source_wrapper:(I)V",
                    callee="LSource;.source1:()LData;",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Source.java",
                    titos=[],
                    leaves=[("TestSource", 1), ("TestSource2", 2)],
                    caller_port="result",
                    callee_port="result",
                    type_interval=None,
                    features=[],
                    annotations=[],
                ),
                ParseConditionTuple(
                    type=ParseType.POSTCONDITION,
                    caller="LSource;.source_wrapper:(I)V",
                    callee="LSource;.source2:()LData;",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Source.java",
                    titos=[],
                    leaves=[("TestSource", 3)],
                    caller_port="argument(1)",
                    callee_port="result",
                    type_interval=None,
                    features=[],
                    annotations=[],
                ),
            ],
        )

    def testModelPreconditions(self) -> None:
        # Origin case.
        self.assertParsed(
            """
                {
                  "method": "LSink;.sink_wrapper:(LData;)V",
                  "sinks": [
                    {
                      "port": "Argument(1)",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin"
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ],
                              "may_features": ["via-obscure"]
                            }
                          ],
                          "local_features": {"always_features": ["via-taint-in-taint-out"]}
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Sink.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LSink;.sink_wrapper:(LData;)V",
                    callee="LSink;.sink:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="Sink.java",
                    titos=[],
                    leaves=[("TestSink", 0)],
                    caller_port="argument(1)",
                    callee_port="sink:argument(1)",
                    type_interval=None,
                    features=[ParseTraceFeature("always-via-taint-in-taint-out", [])],
                    annotations=[],
                )
            ],
        )

        # CallSite case.
        self.assertParsed(
            """
                {
                  "method": "LClass;.indirect_sink:(LData;LData;)V",
                  "sinks": [
                    {
                      "port": "Argument(2)",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 1,
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [
                            {"line": 13, "start": 14, "end": 15},
                            {"line": 16, "start": 17, "end": 18}
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Class.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LClass;.indirect_sink:(LData;LData;)V",
                    callee="LSink;.sink:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Class.java",
                    titos=[
                        SourceLocation(line_no=13, begin_column=15, end_column=16),
                        SourceLocation(line_no=16, begin_column=18, end_column=19),
                    ],
                    leaves=[("TestSink", 1)],
                    caller_port="argument(2)",
                    callee_port="argument(1)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                )
            ],
        )

        # Test with a complex port.
        self.assertParsed(
            """
                {
                  "method": "LSink;.sink_wrapper:(LData;)V",
                  "sinks": [
                    {
                      "port": "Argument(1).x.y",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin"
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Sink.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LSink;.sink_wrapper:(LData;)V",
                    callee="LSink;.sink:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="Sink.java",
                    titos=[],
                    leaves=[("TestSink", 0)],
                    caller_port="argument(1).x.y",
                    callee_port="sink:argument(1)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                )
            ],
        )

        # Test multiple caller ports, callees and kinds (leaves)
        self.assertParsed(
            """
                {
                  "method": "LSink;.sink_wrapper:(LData;LData;)V",
                  "sinks": [
                    {
                      "port": "Argument(2)",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin"
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            },
                            {
                              "call_kind": "Origin",
                              "kind": "TestSink2",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ]
                        },
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink2:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "kind": "TestSink",
                              "distance": 1
                            },
                            {
                              "call_kind": "CallSite",
                              "kind": "TestSink2",
                              "distance": 2
                            }
                          ]
                        }
                      ]
                    },
                    {
                      "port": "Argument(1)",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink3:(LData;)V",
                            "port": "Argument(0)",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 5,
                              "end": 7
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "kind": "TestSink",
                              "distance": 3
                            }
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Sink.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LSink;.sink_wrapper:(LData;LData;)V",
                    callee="LSink;.sink:(LData;LData;)V",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="Sink.java",
                    titos=[],
                    leaves=[("TestSink", 0), ("TestSink2", 0)],
                    caller_port="argument(2)",
                    callee_port="sink:argument(1)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                ),
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LSink;.sink_wrapper:(LData;LData;)V",
                    callee="LSink;.sink2:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Sink.java",
                    titos=[],
                    leaves=[("TestSink", 1), ("TestSink2", 2)],
                    caller_port="argument(2)",
                    callee_port="argument(1)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                ),
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LSink;.sink_wrapper:(LData;LData;)V",
                    callee="LSink;.sink3:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=6,
                        end_column=8,
                    ),
                    filename="Sink.java",
                    titos=[],
                    leaves=[("TestSink", 3)],
                    caller_port="argument(1)",
                    callee_port="argument(0)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                ),
            ],
        )

    def testModelParameterTypeOverrides(self) -> None:
        self.assertParsed(
            """
                {
                  "method": {
                    "name": "LSink;.sink:(LData;)V",
                    "parameter_type_overrides": [
                      {
                        "parameter": 0,
                        "type": "LAnonymous$0;"
                      },
                      {
                        "parameter": 1,
                        "type": "LAnonymous$1;"
                      }
                    ]
                  },
                  "sinks": [
                    {
                      "port": "Argument(1)",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin"
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": {
                                    "name": "LSink;.sink:(LData;)V",
                                    "parameter_type_overrides": [
                                      {
                                        "parameter": 0,
                                        "type": "LAnonymous$0;"
                                      },
                                      {
                                        "parameter": 1,
                                        "type": "LAnonymous$1;"
                                      }
                                    ]
                                  },
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Sink.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LSink;.sink:(LData;)V[0: LAnonymous$0;, 1: LAnonymous$1;]",
                    callee="LSink;.sink:(LData;)V[0: LAnonymous$0;, 1: LAnonymous$1;]",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="Sink.java",
                    titos=[],
                    leaves=[("TestSink", 0)],
                    caller_port="argument(1)",
                    callee_port="sink:argument(1)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                )
            ],
        )

    def testModelPropagations(self) -> None:
        # Parse Propagation and PropagationWithTrace:Declaration
        # These should be ignored
        self.assertParsed(
            """
                {
                  "method" : "LClass;.transformT1:(I)I",
                  "position" : { "line" : 29, "path" : "TaintTransforms.java" },
                  "propagation" :
                  [
                    {
                      "input" : "Argument(0)",
                      "output" :
                      [
                        {
                          "call_info" :
                          {
                            "call_kind" : "PropagationWithTrace:Declaration"
                          },
                          "kinds" :
                          [
                            {
                              "call_kind" : "PropagationWithTrace:Declaration",
                              "kind" : "T1@LocalReturn",
                              "origins" :
                              [
                                {
                                  "method" : "LClass;.transformT1:(I)I",
                                  "port" : "Argument(0)"
                                }
                              ],
                              "output_paths" : { "" : 0 }
                            }
                          ]
                        },
                        {
                          "call_info" :
                          {
                            "call_kind" : "Propagation",
                            "port" : "Return"
                          },
                          "kinds" :
                          [
                            {
                              "call_kind" : "Propagation",
                              "kind" : "LocalReturn",
                              "output_paths" : { "" : 4 }
                            }
                          ]
                        }
                      ]
                    }
                  ]
                }
                """,
            [],
        )

        # Parse PropagationWithTrace:Origin
        self.assertParsed(
            """
                {
                  "method" : "LClass;.hopPropagation2:(I)I",
                  "position" : { "line" : 43, "path" : "ExtraTraces.java" },
                  "propagation" :
                  [
                    {
                      "input" : "Argument(0)",
                      "output" :
                      [
                        {
                          "call_info" :
                          {
                            "call_kind" : "PropagationWithTrace:Origin",
                            "port" : "Argument(0)",
                            "position" : { "line" : 44, "path" : "ExtraTraces.java" }
                          },
                          "kinds" :
                          [
                            {
                              "call_kind" : "PropagationWithTrace:Origin",
                              "kind" : "T2:LocalReturn",
                              "origins" :
                              [
                                {
                                  "method" : "LClass;.transformT2:(I)I",
                                  "port" : "Argument(0)"
                                }
                              ],
                              "output_paths" : { "" : 0 }
                            }
                          ]
                        }
                      ]
                    }
                  ]
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LClass;.hopPropagation2:(I)I",
                    callee="LClass;.transformT2:(I)I",
                    callee_location=SourceLocation(
                        line_no=44,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="ExtraTraces.java",
                    titos=[],
                    leaves=[("T2:LocalReturn", 0)],
                    caller_port="argument(0)",
                    callee_port="sink:argument(0)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                )
            ],
        )

        # Parse PropagationWithTrace:CallSite
        self.assertParsed(
            """
                {
                  "method" : "LClass;.hopPropagation1:(I)I",
                  "position" : { "line" : 38, "path" : "ExtraTraces.java" },
                  "propagation" :
                  [
                    {
                      "input" : "Argument(0)",
                      "output" :
                      [
                        {
                          "call_info" :
                          {
                            "call_kind" : "PropagationWithTrace:CallSite",
                            "port" : "Argument(0)",
                            "position" : { "line" : 39, "path" : "ExtraTraces.java" },
                            "resolves_to" : "LClass;.hopPropagation2:(I)I"
                          },
                          "kinds" :
                          [
                            {
                              "call_kind" : "PropagationWithTrace:CallSite",
                              "distance" : 1,
                              "kind" : "T2:LocalReturn",
                              "origins" :
                              [
                                {
                                  "method" : "LClass;.transformT2:(I)I",
                                  "port" : "Argument(0)"
                                }
                              ],
                              "output_paths" : { "" : 0 }
                            }
                          ]
                        }
                      ]
                    }
                  ]
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LClass;.hopPropagation1:(I)I",
                    callee="LClass;.hopPropagation2:(I)I",
                    callee_location=SourceLocation(
                        line_no=39,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="ExtraTraces.java",
                    titos=[],
                    leaves=[("T2:LocalReturn", 1)],
                    caller_port="argument(0)",
                    callee_port="argument(0)",
                    type_interval=None,
                    features=[],
                    annotations=[],
                )
            ],
        )

        # Parse propagation with extra traces
        self.assertParsed(
            """
                {
                  "method" : "LClass;.hopPropagation2:(I)I",
                  "position" : { "line" : 43, "path" : "ExtraTraces.java" },
                  "propagation" :
                  [
                    {
                      "input" : "Argument(0)",
                      "output" :
                      [
                        {
                          "call_info" :
                          {
                            "call_kind" : "PropagationWithTrace:CallSite",
                            "port" : "Argument(0)",
                            "position" : { "line" : 45, "path" : "ExtraTraces.java" },
                            "resolves_to" : "LClass;.hopPropagation3:(I)I"
                          },
                          "kinds" :
                          [
                            {
                              "call_kind" : "PropagationWithTrace:CallSite",
                              "distance" : 2,
                              "extra_traces" :
                              [
                                {
                                  "call_info" :
                                  {
                                    "call_kind" : "PropagationWithTrace:Origin",
                                    "port" : "Argument(0)",
                                    "position" : {
                                      "line" : 44,
                                      "path" : "ExtraTraces.java"
                                    }
                                  },
                                  "frame_type": "sink",
                                  "kind" :
                                  {
                                    "base" : "LocalReturn",
                                    "global" : "T2"
                                  }
                                }
                              ],
                              "kind" :
                              {
                                "base" : "LocalReturn",
                                "global" : "T1",
                                "local" : "T2"
                              },
                              "origins" :
                              [
                                {
                                  "method" : "LClass;.transformT1:(I)I",
                                  "port" : "Argument(0)"
                                }
                              ],
                              "output_paths" : { "" : 0 }
                            }
                          ]
                        }
                      ]
                    }
                  ]
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LClass;.hopPropagation2:(I)I",
                    callee="LClass;.hopPropagation3:(I)I",
                    callee_location=SourceLocation(
                        line_no=45,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="ExtraTraces.java",
                    titos=[],
                    leaves=[("T2@T1:LocalReturn", 2)],
                    caller_port="argument(0)",
                    callee_port="argument(0)",
                    type_interval=None,
                    features=[],
                    annotations=[
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=44,
                                begin_column=1,
                                end_column=1,
                            ),
                            kind="sink",
                            msg="Propagation through T2:LocalReturn",
                            leaf_kind="T2:LocalReturn",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[],
                        )
                    ],
                )
            ],
        )

        # Parse callsite with source extra traces
        self.assertParsed(
            """
                {
                  "method" : "LClass;.rootCallable:(I)I",
                  "position" : { "line" : 42, "path" : "ExtraTraces.java" },
                  "effect_sinks" :
                  [
                    {
                      "port" : "call-chain",
                      "taint" :
                      [
                        {
                          "call_info" :
                          {
                            "call_kind" : "Origin",
                            "port" : "Argument(0)",
                            "position" :
                            {
                              "line" : 42,
                              "path" : "ExtraTraces.java"
                            }
                          },
                          "kinds" :
                          [
                            {
                              "extra_traces" :
                              [
                                {
                                  "call_info" :
                                  {
                                    "call_kind" : "Origin",
                                    "port" : "Return",
                                    "position" :
                                    {
                                      "line" : 42,
                                      "path" : "ExtraTraces.java"
                                    }
                                  },
                                  "frame_type" : "source",
                                  "kind" : "TestSource"
                                }
                              ],
                              "kind" : "TestSource@TestSink",
                              "origins" :
                              [
                                {
                                  "method" : "LClass;.toSink:(I)V",
                                  "port" : "Argument(0)"
                                }
                              ]
                            }
                          ]
                        }
                      ]
                    }
                  ]
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LClass;.rootCallable:(I)I",
                    callee="LClass;.toSink:(I)V",
                    callee_location=SourceLocation(
                        line_no=42,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="ExtraTraces.java",
                    titos=[],
                    leaves=[("TestSource@TestSink", 0)],
                    caller_port="call-chain",
                    callee_port="sink:argument(0)",
                    type_interval=None,
                    features=[],
                    annotations=[
                        ParseTraceAnnotation(
                            location=SourceLocation(
                                line_no=42,
                                begin_column=1,
                                end_column=1,
                            ),
                            kind="source",
                            msg="To source kind: TestSource",
                            leaf_kind="TestSource",
                            leaf_depth=0,
                            type_interval=None,
                            link=None,
                            trace_key=None,
                            titos=[],
                            subtraces=[],
                        )
                    ],
                )
            ],
        )

    def testClassIntervals(self) -> None:
        # Intervals at origin
        self.assertParsed(
            """
                {
                  "method": "LSink;.sink_wrapper:(LData;)V",
                  "sinks": [
                    {
                      "port": "Argument(1)",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "Origin"
                          },
                          "kinds": [
                            {
                              "call_kind": "Origin",
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ],
                              "callee_interval": [1, 2],
                              "preserves_type_context": true
                            },
                            {
                              "call_kind": "Origin",
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ],
                              "callee_interval": [3, 4],
                              "preserves_type_context": true
                            }
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Sink.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LSink;.sink_wrapper:(LData;)V",
                    callee="LSink;.sink:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="Sink.java",
                    titos=[],
                    leaves=[("TestSink", 0)],
                    caller_port="argument(1)",
                    callee_port="sink:argument(1)",
                    type_interval=ParseTypeInterval(
                        start=1, finish=2, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[],
                ),
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LSink;.sink_wrapper:(LData;)V",
                    callee="LSink;.sink:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=1,
                        begin_column=1,
                        end_column=1,
                    ),
                    filename="Sink.java",
                    titos=[],
                    leaves=[("TestSink", 0)],
                    caller_port="argument(1)",
                    callee_port="sink:argument(1)",
                    type_interval=ParseTypeInterval(
                        start=3, finish=4, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[],
                ),
            ],
        )

        # Intervals at call site
        self.assertParsed(
            """
                {
                  "method": "LClass;.indirect_sink:(LData;LData;)V",
                  "sinks": [
                    {
                      "port": "Argument(2)",
                      "taint": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Class.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 1,
                              "kind": "TestSink",
                              "callee_interval": [10, 20],
                              "preserves_type_context": false
                            },
                            {
                              "call_kind": "CallSite",
                              "distance": 2,
                              "kind": "TestSink2",
                              "callee_interval": [10, 20],
                              "preserves_type_context": false
                            },
                            {
                              "call_kind": "CallSite",
                              "distance": 1,
                              "kind": "TestSink",
                              "callee_interval": [21, 30],
                              "preserves_type_context": true
                            }
                          ],
                          "local_positions": [
                            {"line": 13, "start": 14, "end": 15},
                            {"line": 16, "start": 17, "end": 18}
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 1,
                    "path": "Class.java"
                  }
                }
                """,
            [
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LClass;.indirect_sink:(LData;LData;)V",
                    callee="LSink;.sink:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Class.java",
                    titos=[
                        SourceLocation(line_no=13, begin_column=15, end_column=16),
                        SourceLocation(line_no=16, begin_column=18, end_column=19),
                    ],
                    leaves=[("TestSink", 1), ("TestSink2", 2)],
                    caller_port="argument(2)",
                    callee_port="argument(1)",
                    type_interval=ParseTypeInterval(
                        start=10, finish=20, preserves_type_context=False
                    ),
                    features=[],
                    annotations=[],
                ),
                ParseConditionTuple(
                    type=ParseType.PRECONDITION,
                    caller="LClass;.indirect_sink:(LData;LData;)V",
                    callee="LSink;.sink:(LData;)V",
                    callee_location=SourceLocation(
                        line_no=10,
                        begin_column=12,
                        end_column=13,
                    ),
                    filename="Class.java",
                    titos=[
                        SourceLocation(line_no=13, begin_column=15, end_column=16),
                        SourceLocation(line_no=16, begin_column=18, end_column=19),
                    ],
                    leaves=[("TestSink", 1)],
                    caller_port="argument(2)",
                    callee_port="argument(1)",
                    type_interval=ParseTypeInterval(
                        start=21, finish=30, preserves_type_context=True
                    ),
                    features=[],
                    annotations=[],
                ),
            ],
        )

        # Intervals in issue condition
        self.assertParsed(
            """
                {
                  "method": "LClass;.flow:()V",
                  "issues": [
                    {
                      "rule": 1,
                      "position": {
                        "path": "Flow.java",
                        "line": 10,
                        "start": 11,
                        "end": 12
                      },
                      "callee": "LSink;.sink:(LData;)V",
                      "sink_index": "0",
                      "sinks": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Flow.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 2,
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ],
                              "callee_interval": [123, 456],
                              "preserves_type_context": true
                            }
                          ]
                        }
                      ],
                      "sources": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Flow.java",
                              "line": 20,
                              "start": 21,
                              "end": 22
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 3,
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ],
                              "callee_interval": [234, 345],
                              "preserves_type_context": true
                            }
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 2,
                    "path": "Flow.java"
                  }
                }
                """,
            [
                ParseIssueTuple(
                    code=1,
                    message="TestRule: Test Rule Description",
                    callable="LClass;.flow:()V",
                    handle="LClass;.flow:()V:LSink;.sink:(LData;)V:0:1:1ef9022f932a64d0",
                    filename="Flow.java",
                    callable_line=2,
                    line=10,
                    start=12,
                    end=13,
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="LSink;.sink:(LData;)V",
                            port="argument(1)",
                            location=SourceLocation(
                                line_no=10,
                                begin_column=12,
                                end_column=13,
                            ),
                            leaves=[("TestSink", 2)],
                            titos=[],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=123, finish=456, preserves_type_context=True
                            ),
                            annotations=[],
                        )
                    ],
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="LSource;.source:()LData;",
                            port="result",
                            location=SourceLocation(
                                line_no=20,
                                begin_column=22,
                                end_column=23,
                            ),
                            leaves=[("TestSource", 3)],
                            titos=[],
                            features=[],
                            type_interval=ParseTypeInterval(
                                start=234, finish=345, preserves_type_context=True
                            ),
                            annotations=[],
                        )
                    ],
                    initial_sources={("LSource;.source:(LData;)V", "TestSource", 3)},
                    final_sinks={("LSink;.sink:(LData;)V", "TestSink", 2)},
                    features=[],
                    fix_info=None,
                )
            ],
        )

    def testExpoitabilityOriginAsObject(self) -> None:
        # Ensure we handle the case where "exploitability_origin" has
        # "parameter_overrides" and is not just a string
        self.assertParsed(
            """
                {
                  "method": "LClass;.flow:()V",
                  "issues": [
                    {
                      "rule": 1,
                      "always_features": [
                        "exploitability-root-callable"
                      ],
                      "exploitability_origin": {
                        "callee": "LSink;.sink:(LData;)V",
                        "exploitability_root": {
                          "name": "LSink;.sink:(LData;)V",
                          "parameter_type_overrides": [
                            {
                              "parameter": 4,
                              "type": "LParameterTypeOverride"
                            }
                          ]
                        },
                        "position": {
                          "line": 10,
                          "path": "Flow.java"
                        }
                      },
                      "sink_index": "0",
                      "position": {
                        "line": 50,
                        "path": "Flow.java"
                      },
                      "sinks": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSink;.sink:(LData;)V",
                            "port": "Argument(1)",
                            "position": {
                              "path": "Flow.java",
                              "line": 10,
                              "start": 11,
                              "end": 12
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 2,
                              "always_features": ["via-parameter-field"],
                              "kind": "TestSink",
                              "origins": [
                                {
                                  "method": "LSink;.sink:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [{"line": 13, "start": 14, "end": 15}],
                          "local_features": { "always_features": ["via-parameter-field"] }
                        }
                      ],
                      "sources": [
                        {
                          "call_info": {
                            "call_kind": "CallSite",
                            "resolves_to": "LSource;.source:()LData;",
                            "port": "Return",
                            "position": {
                              "path": "Flow.java",
                              "line": 20,
                              "start": 21,
                              "end": 22
                            }
                          },
                          "kinds": [
                            {
                              "call_kind": "CallSite",
                              "distance": 3,
                              "may_features": ["via-obscure"],
                              "kind": "TestSource",
                              "origins": [
                                {
                                  "method": "LSource;.source:(LData;)V",
                                  "port": "Argument(1)"
                                }
                              ]
                            }
                          ],
                          "local_positions": [
                            {"line": 23, "start": 24, "end": 25},
                            {"line": 26, "start": 27, "end": 28}
                          ]
                        }
                      ]
                    }
                  ],
                  "position": {
                    "line": 2,
                    "path": "Flow.java"
                  }
                }
                """,
            [
                ParseIssueTuple(
                    code=1,
                    message="TestRule: Test Rule Description",
                    callable="LClass;.flow:()V",
                    handle="LSink;.sink:(LData;)V[4: LParameterTypeOverride]:LSink;.sink:(LData;)V:0:1:24e90f4aea117982",
                    filename="Flow.java",
                    line=50,
                    start=1,
                    end=1,
                    preconditions=[
                        ParseIssueConditionTuple(
                            callee="LSink;.sink:(LData;)V",
                            port="argument(1)",
                            location=SourceLocation(
                                line_no=10, begin_column=12, end_column=13
                            ),
                            leaves=[("TestSink", 2)],
                            titos=[
                                SourceLocation(
                                    line_no=13, begin_column=15, end_column=16
                                )
                            ],
                            features=[
                                ParseTraceFeature(
                                    name="always-via-parameter-field", locations=[]
                                )
                            ],
                            type_interval=None,
                            annotations=[],
                            root_port=None,
                        )
                    ],
                    postconditions=[
                        ParseIssueConditionTuple(
                            callee="LSource;.source:()LData;",
                            port="result",
                            location=SourceLocation(
                                line_no=20, begin_column=22, end_column=23
                            ),
                            leaves=[("TestSource", 3)],
                            titos=[
                                SourceLocation(
                                    line_no=23, begin_column=25, end_column=26
                                ),
                                SourceLocation(
                                    line_no=26, begin_column=28, end_column=29
                                ),
                            ],
                            features=[],
                            type_interval=None,
                            annotations=[],
                            root_port=None,
                        )
                    ],
                    initial_sources={("LSource;.source:(LData;)V", "TestSource", 3)},
                    final_sinks={("LSink;.sink:(LData;)V", "TestSink", 2)},
                    features=["always-exploitability-root-callable"],
                    callable_line=2,
                    fix_info=None,
                )
            ],
        )

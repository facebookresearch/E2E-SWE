"""Tests for pydantic-ai agent framework infrastructure.

Tests focus on framework mechanics: agent lifecycle, tool registration,
dependency injection, structured output, result validation, TestModel,
pydantic_graph DAG execution, messages, retries, and usage tracking.

No actual LLM API calls are made -- all tests use TestModel or FunctionModel.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Union

import pytest


# ---------------------------------------------------------------------------
# 1. Agent creation and basic run with TestModel
# ---------------------------------------------------------------------------

class TestAgentBasicRun:
    """Test that an Agent can be created and run with TestModel to produce results."""

    def test_agent_simple_text_response(self):
        """A user creates an Agent with TestModel that returns custom text and verifies the result."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(custom_output_text="Hello world"), system_prompt="You are helpful.")
        result = agent.run_sync("Hi")
        assert result.output == "Hello world"
        assert result.all_messages() is not None
        assert len(result.all_messages()) >= 2  # request + response

    def test_agent_structured_output_with_pydantic_model(self):
        """A user defines a Pydantic model as the output type and the agent returns structured data."""
        from pydantic import BaseModel
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        class CityInfo(BaseModel):
            name: str
            population: int

        agent = Agent(
            TestModel(custom_output_args={"name": "Paris", "population": 2161000}),
            output_type=CityInfo,
        )
        result = agent.run_sync("Tell me about Paris")
        assert isinstance(result.output, CityInfo)
        assert result.output.name == "Paris"
        assert result.output.population == 2161000

    def test_agent_with_system_prompt_decorator(self):
        """A user registers a dynamic system prompt via the decorator and it is included in the run."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(custom_output_text="ok"))

        @agent.system_prompt
        def my_prompt() -> str:
            return "Always respond with ok"

        result = agent.run_sync("test")
        assert result.output == "ok"
        # Verify the system prompt was passed in messages
        messages = result.all_messages()
        request_msg = messages[0]
        parts_text = [p.content for p in request_msg.parts if hasattr(p, 'content') and isinstance(p.content, str)]
        assert any("Always respond with ok" in t for t in parts_text)


# ---------------------------------------------------------------------------
# 2. Tool registration and invocation
# ---------------------------------------------------------------------------

class TestToolRegistration:
    """Test tool registration via decorators and manual methods with the Agent."""

    def test_tool_decorator_plain(self):
        """A user registers a plain tool via decorator and the TestModel calls it automatically."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(), output_type=str)

        @agent.tool_plain
        def get_greeting(name: str) -> str:
            """Return a greeting for the given name."""
            return f"Hello, {name}!"

        result = agent.run_sync("greet Alice")
        # TestModel calls all tools by default, so the tool should have been called
        messages = result.all_messages()
        tool_returns = [
            p for msg in messages for p in msg.parts
            if hasattr(p, 'tool_name') and hasattr(p, 'content')
            and p.__class__.__name__ == 'ToolReturnPart'
        ]
        # The tool ran and produced its concrete return value following the body's template.
        # Assert the value matches the "Hello, <name>!" template the tool body emits -- a wrong
        # tool body would still emit a ToolReturnPart -- without pinning the exact <name> string
        # TestModel synthesizes for the parameter (an arbitrary internal placeholder).
        greeting_returns = [p for p in tool_returns if p.tool_name == 'get_greeting']
        assert greeting_returns
        assert all(
            isinstance(p.content, str) and p.content.startswith("Hello, ") and p.content.endswith("!")
            for p in greeting_returns
        )

    def test_tool_decorator_with_context(self):
        """A user registers a tool that receives RunContext for dependency injection."""
        from pydantic_ai import Agent, RunContext
        from pydantic_ai.models.test import TestModel

        @dataclass
        class MyDeps:
            api_key: str

        agent = Agent(TestModel(), deps_type=MyDeps, output_type=str)

        @agent.tool
        def check_key(ctx: RunContext[MyDeps], prefix: str) -> str:
            """Check the API key from dependencies.

            Args:
                prefix: A prefix to prepend.
            """
            return f"{prefix}key={ctx.deps.api_key}"

        result = agent.run_sync("check", deps=MyDeps(api_key="secret123"))
        messages = result.all_messages()
        tool_returns = [
            p for msg in messages for p in msg.parts
            if p.__class__.__name__ == 'ToolReturnPart'
        ]
        assert any("key=secret123" in str(p.content) for p in tool_returns)

    def test_multiple_tools_all_called(self):
        """A user registers multiple tools and TestModel with call_tools='all' invokes each one."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        called = []
        agent = Agent(TestModel(call_tools='all'), output_type=str)

        @agent.tool_plain
        def tool_a() -> str:
            """First tool."""
            called.append('a')
            return "a_result"

        @agent.tool_plain
        def tool_b() -> str:
            """Second tool."""
            called.append('b')
            return "b_result"

        agent.run_sync("run both")
        assert 'a' in called
        assert 'b' in called

    def test_selective_tool_calling(self):
        """A user configures TestModel to only call specific tools by name."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        called = []
        agent = Agent(TestModel(call_tools=['tool_x']), output_type=str)

        @agent.tool_plain
        def tool_x() -> str:
            """Tool X."""
            called.append('x')
            return "x"

        @agent.tool_plain
        def tool_y() -> str:
            """Tool Y."""
            called.append('y')
            return "y"

        agent.run_sync("run")
        assert 'x' in called
        assert 'y' not in called


# ---------------------------------------------------------------------------
# 3. Dependency injection via RunContext
# ---------------------------------------------------------------------------

class TestDependencyInjection:
    """Test the dependency injection system through RunContext."""

    def test_deps_passed_to_system_prompt(self):
        """A user accesses deps in a dynamic system prompt via RunContext."""
        from pydantic_ai import Agent, RunContext
        from pydantic_ai.models.test import TestModel

        @dataclass
        class Config:
            language: str

        agent = Agent(TestModel(custom_output_text="hola"), deps_type=Config)

        @agent.system_prompt
        def language_prompt(ctx: RunContext[Config]) -> str:
            return f"Respond in {ctx.deps.language}"

        result = agent.run_sync("hello", deps=Config(language="Spanish"))
        messages = result.all_messages()
        request_parts = [
            p.content for p in messages[0].parts
            if hasattr(p, 'content') and isinstance(p.content, str)
        ]
        assert any("Respond in Spanish" in t for t in request_parts)


# ---------------------------------------------------------------------------
# 4. Structured output with union types and output validators
# ---------------------------------------------------------------------------

class TestStructuredOutput:
    """Test structured output: union types, validators, and multiple output types."""

    def test_union_output_type(self):
        """A user uses a union of Pydantic models as output type and receives the correct variant."""
        from pydantic import BaseModel
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        class Success(BaseModel):
            value: int

        class Error(BaseModel):
            message: str

        agent = Agent(
            TestModel(custom_output_args={"value": 42}),
            output_type=Union[Success, Error],  # noqa: UP007
        )
        result = agent.run_sync("compute")
        assert isinstance(result.output, Success)
        assert result.output.value == 42

    def test_output_validator(self):
        """A user adds an output validator that rejects a result, forcing the model to retry."""
        from pydantic_ai import Agent, ModelRetry, RunContext
        from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        # The model returns an invalid output first, then a corrected one on the retry, so the
        # validator's reject branch is actually taken (not a no-op as it would be if the model
        # never produced a rejectable value).
        call_count = 0

        def my_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ModelResponse(parts=[TextPart(content="invalid output")])
            return ModelResponse(parts=[TextPart(content="corrected output")])

        agent = Agent(FunctionModel(my_model))

        retry_count = 0

        @agent.output_validator
        def validate_output(ctx: RunContext[None], output: str) -> str:
            nonlocal retry_count
            if "invalid" in output:
                retry_count += 1
                raise ModelRetry("Output contains 'invalid', try again")
            return output

        result = agent.run_sync("give me output")
        # The validator rejected once (driving a retry) and the run recovered with the corrected
        # value -- assert the concrete output, not merely that it is a str.
        assert retry_count == 1
        assert call_count == 2
        assert result.output == "corrected output"


# ---------------------------------------------------------------------------
# 5. Message types and conversation history
# ---------------------------------------------------------------------------

class TestMessages:
    """Test message construction, serialization, and conversation history management."""

    def test_response_carries_model_text_output(self):
        """A user inspects the response message and finds the model's text output as a TextPart."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(custom_output_text="response"))
        result = agent.run_sync("hello")
        messages = result.all_messages()

        assert len(messages) >= 2
        assert isinstance(messages[0], ModelRequest)
        response = messages[1]
        assert isinstance(response, ModelResponse)
        # Beyond the request/response shape: the response must actually carry the model's text
        # output as a TextPart with the exact produced content -- a behavior no other test rewards
        # (test_message_parts_user_prompt only checks the request-side UserPromptPart, and
        # test_agent_simple_text_response only checks result.output / the message count).
        text_parts = [p for p in response.parts if isinstance(p, TextPart)]
        assert any(p.content == "response" for p in text_parts)

    def test_message_parts_user_prompt(self):
        """A user checks that the user prompt appears as a UserPromptPart in the request."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import UserPromptPart
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(custom_output_text="ok"))
        result = agent.run_sync("my question")
        messages = result.all_messages()

        request = messages[0]
        user_parts = [p for p in request.parts if isinstance(p, UserPromptPart)]
        assert len(user_parts) == 1
        assert user_parts[0].content == "my question"

    def test_tool_call_and_return_in_messages(self):
        """A user verifies that tool calls and returns appear in the message history."""
        import json

        from pydantic_ai import Agent
        from pydantic_ai.messages import ToolCallPart, ToolReturnPart
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(), output_type=str)

        @agent.tool_plain
        def echo(text: str, times: int) -> str:
            """Echo the input alongside a repeat count.

            Args:
                text: The text to echo.
                times: How many times the caller wants it repeated.
            """
            return f"{text}:{times}"

        result = agent.run_sync("echo hello")
        messages = result.all_messages()

        # Find tool call parts in responses
        echo_calls = [
            p for msg in messages for p in msg.parts
            if isinstance(p, ToolCallPart) and p.tool_name == 'echo'
        ]
        # The model called the registered tool by name, not just "some" tool.
        assert echo_calls
        # Capture the arguments the model passed to the echo tool (TestModel synthesizes some
        # placeholder value for each -- the exact values are an arbitrary internal choice). The
        # framework allows ToolCallPart.args to be either a dict keyed by parameter name or a
        # JSON-encoded string, so normalize to a dict before reading them rather than pinning
        # whichever representation TestModel happens to use.
        call_args = echo_calls[0].args
        if isinstance(call_args, str):
            call_args = json.loads(call_args)
        assert isinstance(call_args, dict)
        echoed_text = call_args['text']
        echoed_times = call_args['times']

        # `times` is a required parameter whose declared type is NOT a string, so the placeholder
        # supplied for it must be an int -- reusing the string placeholder for every parameter
        # fails the tool's argument validation and the call never reaches the body. The value
        # itself stays unpinned (it is an arbitrary internal choice).
        assert isinstance(echoed_times, int) and not isinstance(echoed_times, bool)

        # Find tool return parts in requests
        echo_returns = [
            p for msg in messages for p in msg.parts
            if isinstance(p, ToolReturnPart) and p.tool_name == 'echo'
        ]
        # The echo tool renders its two arguments verbatim, so the round-tripped ToolReturnPart
        # content must equal exactly what the model called it with -- asserting the real
        # round-trip (not just that a part exists, and without hard-coding the synthesized
        # placeholders). A tool that ran but returned garbage would fail this.
        assert echo_returns
        assert echoed_text is not None
        assert any(str(p.content) == f"{echoed_text}:{echoed_times}" for p in echo_returns)

    def test_continued_run_model_sees_prior_response(self):
        """A continued run feeds the prior conversation (including the model's earlier reply) to
        the model, not just into the result's message list."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import (
            ModelMessage,
            ModelResponse,
            TextPart,
            UserPromptPart,
        )
        from pydantic_ai.models.function import AgentInfo, FunctionModel
        from pydantic_ai.models.test import TestModel

        # First run produces a known assistant reply via TestModel.
        result1 = Agent(TestModel(custom_output_text="first reply")).run_sync("first query")

        # Second run is driven by a FunctionModel so we can capture exactly what the model
        # receives. The continued history must reach the model invocation itself -- the prior
        # user prompt AND the prior assistant TextPart -- not merely be spliced into
        # result.all_messages() afterwards (the new/all split is covered by
        # test_new_messages_excludes_prior_history).
        seen: dict[str, list[str]] = {}

        def capture_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen["user"] = [
                p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart)
            ]
            seen["assistant"] = [
                p.content
                for m in messages
                if isinstance(m, ModelResponse)
                for p in m.parts
                if isinstance(p, TextPart)
            ]
            return ModelResponse(parts=[TextPart(content="second reply")])

        result2 = Agent(FunctionModel(capture_model)).run_sync(
            "second query", message_history=result1.all_messages()
        )

        assert result2.output == "second reply"
        # The model saw the first run's prompt and reply before the new prompt.
        assert "first query" in seen["user"]
        assert "second query" in seen["user"]
        assert seen["user"].index("first query") < seen["user"].index("second query")
        assert "first reply" in seen["assistant"]


# ---------------------------------------------------------------------------
# 6. FunctionModel for custom model behavior
# ---------------------------------------------------------------------------

class TestFunctionModel:
    """Test FunctionModel for programmatic control over model responses."""

    def test_function_model_basic(self):
        """A user creates a FunctionModel to control exactly what the model returns."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, TextPart, ModelMessage
        from pydantic_ai.models.function import FunctionModel, AgentInfo

        def my_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="function model output")])

        agent = Agent(FunctionModel(my_model))
        result = agent.run_sync("test")
        assert result.output == "function model output"

    def test_function_model_with_tool_calls(self):
        """A user uses FunctionModel to simulate a model that calls tools then returns text."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import (
            ModelMessage,
            ModelResponse,
            TextPart,
            ToolCallPart,
        )
        from pydantic_ai.models.function import FunctionModel, AgentInfo

        call_count = 0

        def my_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1 and info.function_tools:
                # First call: invoke the first available tool
                tool = info.function_tools[0]
                return ModelResponse(parts=[
                    ToolCallPart(tool_name=tool.name, args='{"x": 5}')
                ])
            else:
                return ModelResponse(parts=[TextPart(content="done")])

        agent = Agent(FunctionModel(my_model), output_type=str)

        @agent.tool_plain
        def double(x: int) -> int:
            """Double a number."""
            return x * 2

        result = agent.run_sync("double 5")
        assert result.output == "done"
        assert call_count == 2


# ---------------------------------------------------------------------------
# 7. Usage tracking
# ---------------------------------------------------------------------------

class TestUsageTracking:
    """Test that usage (token counts) is tracked during agent runs."""

    def test_usage_after_run(self):
        """A user checks token usage after a run with TestModel."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(custom_output_text="short response"))
        result = agent.run_sync("hello")

        usage = result.usage
        # total_tokens > 0 is the load-bearing check: it requires real usage accumulation during
        # the run. (A request_tokens + response_tokens == total_tokens equality would be
        # tautological -- those are deprecated aliases of input/output_tokens and total_tokens is
        # defined as their sum -- so it is not asserted.)
        assert usage.total_tokens is not None
        assert usage.total_tokens > 0
        assert usage.request_tokens is not None
        assert usage.response_tokens is not None


# ---------------------------------------------------------------------------
# 8. Retries and ModelRetry exception
# ---------------------------------------------------------------------------

class TestRetries:
    """Test the retry mechanism when tools raise ModelRetry."""

    def test_tool_retry_on_model_retry_exception(self):
        """A user's tool raises ModelRetry and the framework retries the tool call."""
        from pydantic_ai import Agent, ModelRetry
        from pydantic_ai.models.test import TestModel

        call_count = 0
        agent = Agent(TestModel(), output_type=str)

        @agent.tool_plain(retries=2)
        def flaky_tool() -> str:
            """A tool that fails on first call."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ModelRetry("temporary failure")
            return "success"

        result = agent.run_sync("call flaky tool")
        assert call_count == 2
        tool_returns = [
            p for msg in result.all_messages() for p in msg.parts
            if p.__class__.__name__ == 'ToolReturnPart'
        ]
        assert any("success" in str(p.content) for p in tool_returns)


# ---------------------------------------------------------------------------
# 9. Exceptions
# ---------------------------------------------------------------------------

class TestExceptions:
    """Test framework exceptions for error scenarios."""

    def test_user_error_on_no_model(self):
        """A user creates an Agent without a model and runs it without providing one, raising UserError."""
        from pydantic_ai import Agent
        from pydantic_ai.exceptions import UserError

        agent = Agent()

        with pytest.raises(UserError, match="(?i)model"):
            agent.run_sync("test")  # no model provided

    def test_usage_limit_exceeded(self):
        """A user sets a request limit and the agent stops when exceeded."""
        from pydantic_ai import Agent
        from pydantic_ai.exceptions import UsageLimitExceeded
        from pydantic_ai.models.test import TestModel
        from pydantic_ai.usage import UsageLimits

        agent = Agent(TestModel(), output_type=str)

        @agent.tool_plain
        def dummy() -> str:
            """Dummy tool."""
            return "x"

        with pytest.raises(UsageLimitExceeded):
            agent.run_sync("run", usage_limits=UsageLimits(request_limit=1))


# ---------------------------------------------------------------------------
# 10. ToolDefinition and function schema generation
# ---------------------------------------------------------------------------

class TestToolDefinition:
    """Test ToolDefinition construction and JSON schema generation for tools."""

    def test_tool_definition_from_function(self):
        """A user inspects a registered tool's definition including its JSON schema."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        model = TestModel()
        agent = Agent(model, output_type=str)

        @agent.tool_plain
        def search(query: str, limit: int = 10) -> str:
            """Search for items matching query.

            Args:
                query: The search string.
                limit: Maximum results to return.
            """
            return f"found {limit} results for {query}"

        # Access the tool definitions through the TestModel's last request parameters.
        agent.run_sync("search for test")
        params = model.last_model_request_parameters
        assert params is not None
        tool_defs = params.function_tools
        assert len(tool_defs) >= 1
        search_def = [t for t in tool_defs if t.name == 'search'][0]
        assert 'query' in search_def.parameters_json_schema['properties']
        assert 'limit' in search_def.parameters_json_schema['properties']
        assert search_def.parameters_json_schema['required'] == ['query']


# ---------------------------------------------------------------------------
# 11. pydantic_graph: Graph builder API — steps, decisions, forks
# ---------------------------------------------------------------------------

class TestGraphMultiNodeWorkflow:
    """Test pydantic_graph with multi-node workflows including branching and looping."""

    def test_graph_with_accumulator_loop(self):
        """A user builds a graph that loops, accumulating values in state until a condition is met."""
        import warnings
        from pydantic_graph import BaseNode, End, GraphRunContext

        @dataclass
        class AccState:
            values: list[int]
            step: int = 0

        @dataclass
        class Accumulate(BaseNode[AccState, None, list[int]]):
            async def run(self, ctx: GraphRunContext) -> Union['Accumulate', End[list[int]]]:
                ctx.state.step += 1
                ctx.state.values.append(ctx.state.step * 10)
                if ctx.state.step >= 3:
                    return End(ctx.state.values)
                return Accumulate()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pydantic_graph.graph import Graph
            graph = Graph(nodes=(Accumulate,))
            result = asyncio.run(
                graph.run(Accumulate(), state=AccState(values=[]))
            )
        assert result.output == [10, 20, 30]

    def test_graph_branching_with_multiple_node_types(self):
        """A user builds a graph with conditional branching between different node types."""
        import warnings
        from pydantic_graph import BaseNode, End, GraphRunContext

        @dataclass
        class BranchState:
            route: str
            result: str = ""

        @dataclass
        class Router(BaseNode[BranchState, None, str]):
            async def run(self, ctx: GraphRunContext) -> Union['PathA', 'PathB']:
                if ctx.state.route == "a":
                    return PathA()
                return PathB()

        @dataclass
        class PathA(BaseNode[BranchState, None, str]):
            async def run(self, ctx: GraphRunContext) -> End[str]:
                return End("took path A")

        @dataclass
        class PathB(BaseNode[BranchState, None, str]):
            async def run(self, ctx: GraphRunContext) -> End[str]:
                return End("took path B")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pydantic_graph.graph import Graph
            graph = Graph(nodes=(Router, PathA, PathB))

            result_a = asyncio.run(
                graph.run(Router(), state=BranchState(route="a"))
            )
            assert result_a.output == "took path A"

            result_b = asyncio.run(
                graph.run(Router(), state=BranchState(route="b"))
            )
            assert result_b.output == "took path B"


# ---------------------------------------------------------------------------
# 12. pydantic_graph: Legacy BaseNode API
# ---------------------------------------------------------------------------

class TestBaseNodeGraph:
    """Test pydantic_graph's legacy BaseNode-based API for graph execution."""

    def test_basenode_graph_with_deps(self):
        """A user builds a BaseNode graph that accesses dependencies via GraphRunContext."""
        import warnings
        from pydantic_graph import BaseNode, End, GraphRunContext

        @dataclass
        class AppState:
            values: list[int]

        @dataclass
        class Multiplier:
            factor: int

        @dataclass
        class MultiplyNode(BaseNode[AppState, Multiplier, list[int]]):
            async def run(self, ctx: GraphRunContext) -> End[list[int]]:
                result = [v * ctx.deps.factor for v in ctx.state.values]
                return End(result)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pydantic_graph.graph import Graph
            graph = Graph(nodes=(MultiplyNode,))
            result = asyncio.run(
                graph.run(MultiplyNode(), state=AppState(values=[1, 2, 3]), deps=Multiplier(factor=10))
            )
        assert result.output == [10, 20, 30]


# ---------------------------------------------------------------------------
# 13. Mermaid diagram generation from graphs
# ---------------------------------------------------------------------------

class TestMermaidDiagram:
    """Test mermaid diagram code generation from pydantic_graph graphs."""

    def test_basenode_mermaid_output(self):
        """A user generates mermaid diagram code from a BaseNode graph and verifies its structure."""
        import warnings
        from pydantic_graph import BaseNode, End, GraphRunContext

        @dataclass
        class St:
            v: int

        @dataclass
        class A(BaseNode[St, None, int]):
            async def run(self, ctx: GraphRunContext) -> 'B':
                return B()

        @dataclass
        class B(BaseNode[St, None, int]):
            async def run(self, ctx: GraphRunContext) -> End[int]:
                return End(ctx.state.v)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pydantic_graph.graph import Graph
            graph = Graph(nodes=(A, B))
            mermaid = graph.mermaid_code()

        assert isinstance(mermaid, str)
        assert len(mermaid) > 10
        lines = mermaid.strip().split('\n')
        assert len(lines) >= 2
        # Assert the concrete edges a correct renderer emits for A -> B -> End:
        # the real A->B transition and B's terminal edge. Checking node names and
        # a bare arrow separately would pass even if the A->B edge were omitted.
        assert 'A --> B' in mermaid
        assert 'B --> [*]' in mermaid


# ---------------------------------------------------------------------------
# 14. ModelSettings
# ---------------------------------------------------------------------------

class TestModelSettings:
    """Test ModelSettings for configuring model behavior."""

    def test_model_settings_temperature(self):
        """A user passes model settings with temperature and verifies they propagate to the model."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
        from pydantic_ai.models.function import AgentInfo, FunctionModel
        from pydantic_ai.settings import ModelSettings

        captured = {}

        def my_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            captured["settings"] = info.model_settings
            return ModelResponse(parts=[TextPart(content="ok")])

        agent = Agent(FunctionModel(my_model))
        result = agent.run_sync(
            "test",
            model_settings=ModelSettings(temperature=0.5, max_tokens=100),
        )
        assert result.output == "ok"
        # The settings must actually reach the model, not just be accepted by run_sync.
        assert captured["settings"] is not None
        assert captured["settings"].get("temperature") == 0.5
        assert captured["settings"].get("max_tokens") == 100

    def test_run_settings_override_agent_settings(self):
        """A user sets agent-level model settings and overrides some at run time; run values win."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
        from pydantic_ai.models.function import AgentInfo, FunctionModel
        from pydantic_ai.settings import ModelSettings, merge_model_settings

        captured = {}

        def my_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            captured["settings"] = info.model_settings
            return ModelResponse(parts=[TextPart(content="ok")])

        # Agent-level defaults + a run-level override of one key. The settings that reach the
        # model must merge the two with the run-level value winning, exercising the precedence
        # contract through the public Agent surface (not an isolated internal merge helper).
        agent = Agent(
            FunctionModel(my_model),
            model_settings=ModelSettings(temperature=0.5, max_tokens=100),
        )
        result = agent.run_sync("test", model_settings=ModelSettings(temperature=0.9))
        assert result.output == "ok"
        assert captured["settings"] is not None
        # Run-level temperature overrides the agent default; the agent's max_tokens is preserved.
        assert captured["settings"].get("temperature") == 0.9
        assert captured["settings"].get("max_tokens") == 100

        # The same precedence contract is also exposed as the standalone merge helper the two
        # levels are merged through, including its both-None case, which the Agent surface
        # cannot reach.
        merged = merge_model_settings(
            ModelSettings(temperature=0.5, max_tokens=100), ModelSettings(temperature=0.9)
        )
        assert merged is not None
        assert merged.get("temperature") == 0.9
        assert merged.get("max_tokens") == 100
        assert merge_model_settings(None, None) is None


# ---------------------------------------------------------------------------
# 15. RunResult and AgentRunResult
# ---------------------------------------------------------------------------

class TestRunResult:
    """Test AgentRunResult properties and methods."""

    def test_new_messages_excludes_prior_history(self):
        """A user distinguishes a run's own messages (new_messages) from the full conversation
        (all_messages) when continuing from a prior history."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import UserPromptPart
        from pydantic_ai.models.test import TestModel

        prior = Agent(TestModel(custom_output_text="first reply")).run_sync("first query").all_messages()

        result = Agent(TestModel(custom_output_text="second reply")).run_sync(
            "second query", message_history=prior
        )

        def prompts(msgs):
            return [p.content for m in msgs for p in m.parts if isinstance(p, UserPromptPart)]

        all_msgs = result.all_messages()
        new_msgs = result.new_messages()

        # all_messages() carries the whole conversation forward (both prompts); new_messages()
        # is ONLY this run's slice -- it excludes the prior run's prompt and is exactly the tail
        # of all_messages(). A naive impl that returns all_messages() from new_messages() (or
        # that drops the passed-in history) fails this concrete split.
        assert prompts(all_msgs) == ["first query", "second query"]
        assert prompts(new_msgs) == ["second query"]
        assert list(all_msgs[-len(new_msgs):]) == list(new_msgs)


# ---------------------------------------------------------------------------
# 16. Async agent runs
# ---------------------------------------------------------------------------

class TestAsyncAgent:
    """Test that the Agent supports async runs via agent.run()."""

    def test_async_run(self):
        """A user runs an agent asynchronously and gets the same result as sync."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(custom_output_text="async result"))

        async def do_run():
            result = await agent.run("async query")
            return result.output

        output = asyncio.run(do_run())
        assert output == "async result"


# ---------------------------------------------------------------------------
# 17. capture_run_messages context manager
# ---------------------------------------------------------------------------

class TestCaptureRunMessages:
    """Test the capture_run_messages context manager for observing messages."""

    def test_capture_messages(self):
        """A user captures messages during a run using the context manager."""
        from pydantic_ai import Agent, capture_run_messages
        from pydantic_ai.messages import TextPart, UserPromptPart
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(custom_output_text="captured"))
        with capture_run_messages() as messages:
            agent.run_sync("test capture")

        assert len(messages) >= 2
        # The captured stream must hold the run's actual content (prompt in, response out),
        # not just any two messages -- capture that collected the wrong messages would pass
        # a bare count check.
        user_prompts = [p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart)]
        response_texts = [p.content for m in messages for p in m.parts if isinstance(p, TextPart)]
        assert "test capture" in user_prompts
        assert "captured" in response_texts


# ---------------------------------------------------------------------------
# 19. Agent overrides via model parameter at run time
# ---------------------------------------------------------------------------

class TestAgentModelOverride:
    """Test overriding the model at run time."""

    def test_override_model_at_run(self):
        """A user overrides the default model at run time with a different TestModel."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        agent = Agent(TestModel(custom_output_text="default"))
        result = agent.run_sync(
            "test",
            model=TestModel(custom_output_text="overridden"),
        )
        assert result.output == "overridden"


# ---------------------------------------------------------------------------
# 20. pydantic_graph: graph persistence (in-memory)
# ---------------------------------------------------------------------------

class TestGraphPersistence:
    """Test in-memory persistence for graph state snapshots."""

    def test_simple_state_persistence(self):
        """A user runs a BaseNode graph with SimpleStatePersistence and retrieves snapshots."""
        import warnings
        from pydantic_graph import BaseNode, End, GraphRunContext

        @dataclass
        class PState:
            n: int

        @dataclass
        class CountUp(BaseNode[PState, None, int]):
            async def run(self, ctx: GraphRunContext) -> Union['CountUp', End[int]]:
                ctx.state.n += 1
                if ctx.state.n >= 5:
                    return End(ctx.state.n)
                return CountUp()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from pydantic_graph import SimpleStatePersistence
            from pydantic_graph.graph import Graph
            from pydantic_graph.persistence import EndSnapshot
            persistence = SimpleStatePersistence()
            graph = Graph(nodes=(CountUp,))
            result = asyncio.run(
                graph.run(CountUp(), state=PState(n=0), persistence=persistence)
            )
        assert result.output == 5
        # The persistence object must actually have recorded the run's terminal snapshot --
        # a graph engine that silently ignored the persistence= argument would still produce
        # output == 5 but leave last_snapshot unset. Assert the captured End snapshot carries
        # the run's final result and state.
        snapshot = persistence.last_snapshot
        assert isinstance(snapshot, EndSnapshot)
        assert snapshot.result.data == 5
        assert snapshot.state.n == 5


# ---------------------------------------------------------------------------
# 21. UsageLimits configuration
# ---------------------------------------------------------------------------

class TestUsageLimits:
    """Test UsageLimits for controlling agent resource usage."""

    def test_token_limit_propagates(self):
        """A user sets a response token limit and the run is bounded by it."""
        from pydantic_ai import Agent
        from pydantic_ai.exceptions import UsageLimitExceeded
        from pydantic_ai.models.test import TestModel
        from pydantic_ai.usage import UsageLimits

        # A generous limit lets the run complete normally and the actual response tokens
        # are counted. Assert real per-run response-token counting (a positive count) without
        # pinning the exact number, which is an internal tokenization detail of TestModel.
        agent = Agent(TestModel(custom_output_text="ok"))
        result = agent.run_sync("test", usage_limits=UsageLimits(response_tokens_limit=100000))
        assert result.output == "ok"
        assert result.usage.response_tokens > 0

        # The limit must actually take effect: a zero response-token budget makes the run
        # raise rather than return. A no-op limit (accepted but never enforced) would pass
        # the generous-limit assertion above yet fail to raise here.
        agent_capped = Agent(TestModel(custom_output_text="ok"))
        with pytest.raises(UsageLimitExceeded):
            agent_capped.run_sync("test", usage_limits=UsageLimits(response_tokens_limit=0))


# ---------------------------------------------------------------------------
# 22. Tool prepare functions
# ---------------------------------------------------------------------------

class TestToolPrepare:
    """Test tool prepare functions that can dynamically include/exclude tools."""

    def test_tool_prepare_excludes_tool(self):
        """A user uses a prepare function to conditionally exclude a tool from a run."""
        from pydantic_ai import Agent, RunContext
        from pydantic_ai.models.test import TestModel
        from pydantic_ai.tools import ToolDefinition

        model = TestModel(custom_output_text="no tools needed")
        agent = Agent(model, output_type=str)

        async def maybe_include(
            ctx: RunContext[None], tool_def: ToolDefinition
        ) -> ToolDefinition | None:
            # Exclude the tool entirely
            return None

        @agent.tool_plain(prepare=maybe_include)
        def hidden_tool() -> str:
            """This tool should be hidden."""
            return "should not appear"

        agent.run_sync("test")
        params = model.last_model_request_parameters
        assert params is not None
        # The tool should not be in the function tools list
        tool_names = [t.name for t in params.function_tools]
        assert 'hidden_tool' not in tool_names


# ---------------------------------------------------------------------------
# 23. Agent with end_strategy
# ---------------------------------------------------------------------------

class TestEndStrategy:
    """Test different end strategies for agent runs."""

    def test_end_strategy_early(self):
        """A user compares end strategies: 'early' skips extra tool calls that arrive with a final result, 'exhaustive' runs them."""
        from pydantic import BaseModel
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        class Out(BaseModel):
            val: int

        def make_agent(strategy):
            ran = []

            def my_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                # One response carrying BOTH a final-output tool call and an extra function tool call.
                out_tool = info.output_tools[0].name
                return ModelResponse(parts=[
                    ToolCallPart(tool_name=out_tool, args={"val": 1}),
                    ToolCallPart(tool_name="side_effect", args={}),
                ])

            agent = Agent(FunctionModel(my_model), output_type=Out, end_strategy=strategy)

            @agent.tool_plain
            def side_effect() -> str:
                """A side-effect tool that records when it runs."""
                ran.append(True)
                return "ran"

            return agent, ran

        # 'early': the extra function tool is skipped once a final result is present.
        agent_early, ran_early = make_agent('early')
        result_early = agent_early.run_sync("test")
        assert result_early.output.val == 1
        assert ran_early == []

        # 'exhaustive': the same extra function tool is still executed.
        agent_exhaustive, ran_exhaustive = make_agent('exhaustive')
        result_exhaustive = agent_exhaustive.run_sync("test")
        assert result_exhaustive.output.val == 1
        assert ran_exhaustive == [True]


# ---------------------------------------------------------------------------
# 24. format_as_xml utility
# ---------------------------------------------------------------------------

class TestFormatAsXml:
    """Test the format_as_xml utility for structuring prompts."""

    def test_format_as_xml(self):
        """A user formats structured data as XML, with and without a wrapping root tag."""
        from pydantic_ai.format_prompt import format_as_xml

        # With root_tag: the dict is rendered as child elements wrapped in the root tag,
        # pretty-printed with two-space indentation. The output is fully determined, so assert
        # the exact rendered string (not just substring presence).
        with_tag = format_as_xml({"key": "value"}, root_tag="data")
        assert with_tag == "<data>\n  <key>value</key>\n</data>"

        # Without root_tag: each dict entry becomes a top-level element joined by newlines (no
        # outer wrapper).
        no_tag = format_as_xml({"name": "Alice", "age": 30})
        assert no_tag == "<name>Alice</name>\n<age>30</age>"


# ---------------------------------------------------------------------------
# 25. Agent with model_name from string
# ---------------------------------------------------------------------------

class TestModelName:
    """Test TestModel model name and system properties."""

    def test_test_model_name(self):
        """A user runs agents with TestModel and the model name shows up on the produced response."""
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse
        from pydantic_ai.models.test import TestModel

        # An explicit model_name must propagate onto the ModelResponse produced by a real run
        # (not merely be stored on the model).
        model = TestModel(custom_output_text="hi", model_name="my-test")
        result = Agent(model).run_sync("q")
        responses = [m for m in result.all_messages() if isinstance(m, ModelResponse)]
        assert responses and all(r.model_name == "my-test" for r in responses)

        # When model_name is not given it defaults to "test", which likewise reaches the response.
        default_result = Agent(TestModel(custom_output_text="hi")).run_sync("q")
        default_responses = [m for m in default_result.all_messages() if isinstance(m, ModelResponse)]
        assert default_responses and all(r.model_name == "test" for r in default_responses)

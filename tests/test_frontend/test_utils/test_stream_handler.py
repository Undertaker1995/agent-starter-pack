# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Any
from unittest.mock import MagicMock

from frontend.utils.stream_handler import EventProcessor, StreamHandler


class MockStreamlit:
    """Mock Streamlit class for testing"""

    class SessionState(dict):
        def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
            super().__init__()
            self.user_chats: dict[str, dict[str, list[dict[str, Any]]]] = {
                "test_session": {"messages": messages or []}
            }
            self["session_id"] = "test_session"
            self["user_id"] = "test_user"
            self["run_id"] = None  # Initialize run_id as None

    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self.session_state = self.SessionState(messages)

    def toast(self, message: str) -> None:
        pass


def test_stream_handler_initialization() -> None:
    """Test StreamHandler initialization"""
    st_mock = MagicMock()
    handler = StreamHandler(st_mock, initial_text="test")

    assert handler.text == "test"
    assert handler.tools_logs == "test"
    st_mock.expander.assert_called_once()
    st_mock.empty.assert_called_once()


def test_stream_handler_new_token() -> None:
    """Test adding new tokens to StreamHandler"""
    st_mock = MagicMock()
    handler = StreamHandler(st_mock)

    handler.new_token("Hello ")
    handler.new_token("World")

    assert handler.text == "Hello World"
    assert handler.container.markdown.call_count == 2


def test_stream_handler_new_status() -> None:
    """Test adding status updates to StreamHandler"""
    st_mock = MagicMock()
    handler = StreamHandler(st_mock)

    handler.new_status("Tool started")
    handler.new_status("Tool completed")

    assert handler.tools_logs == "Tool startedTool completed"
    assert handler.tool_expander.markdown.call_count == 2


def test_event_processor_tool_calls() -> None:
    """Test EventProcessor handling of tool calls"""
    st_mock = MockStreamlit()
    client_mock = MagicMock()
    stream_handler_mock = MagicMock()

    # Mock stream events with tool calls
    tool_call_event = {
        "type": "constructor",
        "kwargs": {
            "tool_calls": [
                {"id": "test_id", "name": "test_tool", "args": {"arg1": "value1"}}
            ]
        },
    }

    tool_response_event = {
        "type": "constructor",
        "kwargs": {"tool_call_id": "test_id", "content": "tool response"},
    }

    final_response_event = {
        "type": "constructor",
        "kwargs": {"content": "final response"},
    }

    client_mock.stream_messages.return_value = [
        (tool_call_event, {}),
        (tool_response_event, {}),
        (final_response_event, {}),
    ]

    processor = EventProcessor(st_mock, client_mock, stream_handler_mock)
    processor.process_events()

    # Verify tool calls were processed
    assert len(processor.tool_calls) == 2
    assert isinstance(processor.tool_calls[0], dict)
    assert processor.tool_calls[0]["tool_calls"][0]["name"] == "test_tool"
    assert isinstance(processor.tool_calls[1], dict)
    assert processor.tool_calls[1]["content"] == "tool response"

    # Verify final content
    assert processor.final_content == "final response"

    # Verify stream handler updates
    assert stream_handler_mock.new_status.call_count == 2
    assert stream_handler_mock.new_token.call_count == 1


def test_event_processor_direct_response() -> None:
    """Test EventProcessor handling direct AI responses"""
    st_mock = MockStreamlit()
    client_mock = MagicMock()
    stream_handler_mock = MagicMock()

    # Mock stream events with direct response
    response_events: list[tuple[dict[str, Any], dict[str, Any]]] = [
        ({"type": "constructor", "kwargs": {"content": "Hello"}}, {}),
        ({"type": "constructor", "kwargs": {"content": " World"}}, {}),
    ]

    client_mock.stream_messages.return_value = response_events

    processor = EventProcessor(st_mock, client_mock, stream_handler_mock)
    processor.process_events()

    # Verify content was accumulated correctly
    assert processor.final_content == "Hello World"
    assert len(processor.tool_calls) == 0

    # Verify stream handler updates
    assert stream_handler_mock.new_token.call_count == 2
    stream_handler_mock.new_token.assert_any_call("Hello")
    stream_handler_mock.new_token.assert_any_call(" World")


def test_event_processor_session_state_updates() -> None:
    """Test EventProcessor updates to session state"""
    st_mock = MockStreamlit()
    client_mock = MagicMock()
    stream_handler_mock = MagicMock()

    # Mock stream events with message that should be added to session state
    client_mock.stream_messages.return_value = [
        ({"type": "constructor", "kwargs": {"content": "test response"}}, {})
    ]

    # Initialize session state with empty messages
    st_mock.session_state.user_chats["test_session"]["messages"] = []

    processor = EventProcessor(st_mock, client_mock, stream_handler_mock)
    run_id = "test_run"
    processor.process_events(run_id=run_id)

    # Verify stream events call
    client_mock.stream_messages.assert_called_once()
    call_args = client_mock.stream_messages.call_args[1]["data"]

    # Verify messages passed correctly
    assert "messages" in call_args
    assert call_args["messages"] == []

    # Verify config passed correctly
    assert "config" in call_args
    config = call_args["config"]
    assert "run_id" in config
    assert config["run_id"] == processor.current_run_id
    assert config["metadata"]["user_id"] == "test_user"
    assert config["metadata"]["session_id"] == "test_session"

    # Verify session state updates
    messages = st_mock.session_state.user_chats["test_session"]["messages"]
    assert len(messages) == 1
    assert messages[0]["content"] == "test response"
    assert "id" in messages[0]
    assert st_mock.session_state["run_id"] == run_id


def test_event_processor_session_state_updates_with_tools() -> None:
    """Test EventProcessor updates to session state when using tools"""
    st_mock = MockStreamlit()
    client_mock = MagicMock()
    stream_handler_mock = MagicMock()

    # Mock stream events with tool calls and final response
    client_mock.stream_messages.return_value = [
        (
            {
                "type": "constructor",
                "kwargs": {
                    "tool_calls": [
                        {
                            "id": "test_id",
                            "name": "test_tool",
                            "args": {"arg1": "value1"},
                        }
                    ]
                },
            },
            {},
        ),
        (
            {
                "type": "constructor",
                "kwargs": {"tool_call_id": "test_id", "content": "tool response"},
            },
            {},
        ),
        ({"type": "constructor", "kwargs": {"content": "final response"}}, {}),
    ]

    # Initialize session state with empty messages
    st_mock.session_state.user_chats["test_session"]["messages"] = []

    processor = EventProcessor(st_mock, client_mock, stream_handler_mock)
    run_id = "test_run"
    processor.process_events(run_id=run_id)

    # Verify session state updates
    messages = st_mock.session_state.user_chats["test_session"]["messages"]
    assert (
        len(messages) == 3
    )  # Should have tool call, tool response, and final response

    # Verify tool call message
    assert messages[0]["tool_calls"][0]["name"] == "test_tool"
    assert messages[0]["tool_calls"][0]["args"] == {"arg1": "value1"}

    # Verify tool response message
    assert messages[1]["content"] == "tool response"
    assert messages[1]["tool_call_id"] == "test_id"

    # Verify final response message
    assert messages[2]["content"] == "final response"
    assert messages[2]["id"] == "test_run"

    # Verify run_id was updated
    assert st_mock.session_state["run_id"] == "test_run"

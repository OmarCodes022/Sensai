"""user_messages: the creator's own messages, shared by /history and T34's /edit N numbering."""

from sensai.chat.saved_sessions import user_messages
from sensai.core.messages import Message


def test_keeps_only_user_messages_in_order_with_original_contents():
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="  Premier\nmessage  "),
        Message(role="assistant", content="R1"),
        Message(role="system", content="persona"),
        Message(role="user", content="Deuxième"),
    ]
    assert user_messages(messages) == ["  Premier\nmessage  ", "Deuxième"]


def test_tool_loop_protocol_turns_are_skipped():
    messages = [
        Message(role="user", content="Calcule"),
        Message(role="assistant", content='{"tool": "run_python", "arguments": {}}'),
        Message(role="user", content="Tool result from run_python:\n{}"),
        Message(role="user", content="Tool error from run_python: boom\n"
                                     "Tool round limit reached. Give a final answer without tools."),
        Message(role="user", content="Merci"),
    ]
    assert user_messages(messages) == ["Calcule", "Merci"]


def test_only_the_exact_prefixes_are_protocol():
    messages = [Message(role="user", content=text) for text in
                ("Tool results from last week?", "tool result from x", " Tool error from x")]
    assert user_messages(messages) == [m.content for m in messages]


def test_empty_history():
    assert user_messages([]) == []
    assert user_messages([Message(role="system", content="sys")]) == []

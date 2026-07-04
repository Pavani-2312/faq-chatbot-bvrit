"""
memory.py
---------
Multi-turn conversation state management for the BVRIT FAQ Chatbot.

Keeps a simple ordered list of {role, content} message dicts per session.
Designed to be stored in Streamlit's st.session_state so it persists
for the lifetime of one browser session.

No external dependencies — plain Python only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Role = Literal["user", "assistant", "system"]

# Maximum number of prior turns to include in the prompt context.
# Keeps token usage bounded without losing meaningful conversational context.
MAX_HISTORY_TURNS = 10  # each turn = 1 user + 1 assistant message


@dataclass
class Message:
    role: Role
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class ConversationMemory:
    """
    Stores and manages the conversation history for a single chat session.

    Usage:
        memory = ConversationMemory()
        memory.add_user("What is the CSE fee?")
        memory.add_assistant("The CSE tuition fee is ₹1,20,000/year. [Fee Structure, Page 4]")
        history = memory.get_history()   # list of dicts for prompt injection
    """

    def __init__(self, max_turns: int = MAX_HISTORY_TURNS) -> None:
        self._messages: list[Message] = []
        self.max_turns = max_turns

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_user(self, content: str) -> None:
        """Append a user message."""
        self._messages.append(Message(role="user", content=content))

    def add_assistant(self, content: str) -> None:
        """Append an assistant message."""
        self._messages.append(Message(role="assistant", content=content))

    def clear(self) -> None:
        """Reset the conversation (e.g., when the user clicks 'New Chat')."""
        self._messages.clear()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history(self, exclude_last_user: bool = False) -> list[dict]:
        """
        Return the conversation history as a list of {role, content} dicts,
        limited to the most recent `max_turns` complete exchanges.

        Args:
            exclude_last_user:  If True, omit the most recent user message
                                (useful when the caller is about to send it
                                separately as the current query).

        Returns:
            List of {"role": ..., "content": ...} dicts, oldest first.
        """
        messages = self._messages.copy()
        if exclude_last_user and messages and messages[-1].role == "user":
            messages = messages[:-1]

        # Keep only the last max_turns * 2 messages (pairs of user+assistant)
        max_messages = self.max_turns * 2
        if len(messages) > max_messages:
            messages = messages[-max_messages:]

        return [m.to_dict() for m in messages]

    def get_display_messages(self) -> list[dict]:
        """
        Return all messages (no truncation) for rendering in the Streamlit
        chat UI. Includes the full conversation history.
        """
        return [m.to_dict() for m in self._messages]

    @property
    def turn_count(self) -> int:
        """Number of complete user+assistant turns in this session."""
        user_msgs = sum(1 for m in self._messages if m.role == "user")
        return user_msgs

    @property
    def is_empty(self) -> bool:
        return len(self._messages) == 0

    def last_user_message(self) -> str | None:
        """Return the content of the most recent user message, or None."""
        for msg in reversed(self._messages):
            if msg.role == "user":
                return msg.content
        return None

    def last_assistant_message(self) -> str | None:
        """Return the content of the most recent assistant message, or None."""
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                return msg.content
        return None

    def __len__(self) -> int:
        return len(self._messages)

    def __repr__(self) -> str:
        return (
            f"ConversationMemory("
            f"turns={self.turn_count}, "
            f"messages={len(self._messages)}, "
            f"max_turns={self.max_turns})"
        )

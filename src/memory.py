"""
memory.py
---------
Multi-turn conversation state management for the BVRIT FAQ Chatbot.

Implements the memory requirements from HandsOn_Memory_Questions.docx:
  - Exercise 1: Conversation history management (messages list per session)
  - Exercise 2: Summarisation strategy for long sessions (>10 turns)
  - Exercise 3: Persistent user profile storage across sessions (JSON file)

Summarisation strategy (Exercise 2):
  After every 10 user+assistant turn pairs, the oldest 10 turns are
  condensed into a single summary paragraph by the LLM. This keeps the
  context window bounded (prevents confusion at turn 25+) while preserving
  key facts discussed earlier.

  Before summarisation (20+ messages in memory):
    [user_1][asst_1][user_2][asst_2]...[user_10][asst_10][user_11][asst_11]...
  After summarisation of oldest 10 turns:
    [SUMMARY: student asked about CSE fees, placements, hostel...][user_11][asst_11]...

Persistent user profile (Exercise 3):
  User profiles are saved to data/user_profiles/<user_id>.json.
  Fields: name, branch_interest, questions_asked, session_count, last_seen.
  Profile is injected into the system prompt at session start.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum number of verbatim turns kept after summarisation
MAX_HISTORY_TURNS = 10        # each turn = 1 user + 1 assistant message
SUMMARISE_AFTER_TURNS = 10    # trigger summarisation after this many turns
SUMMARY_MODEL = "openai/gpt-4o-mini"  # model used for summarisation

# User profile storage directory
PROFILES_DIR = Path(__file__).resolve().parent.parent / "data" / "user_profiles"

# ---------------------------------------------------------------------------
# Message and role types
# ---------------------------------------------------------------------------

Role = Literal["user", "assistant", "system"]


@dataclass
class Message:
    role: Role
    content: str
    is_summary: bool = False  # True for injected summary messages

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


# ---------------------------------------------------------------------------
# Conversation Memory
# ---------------------------------------------------------------------------

class ConversationMemory:
    """
    Stores and manages the conversation history for a single chat session.
    Supports automatic summarisation of older turns to keep context bounded.

    Usage:
        memory = ConversationMemory()
        memory.add_user("What is the CSE fee?")
        memory.add_assistant("The CSE tuition fee is ₹1,20,000/year. [Fee Structure, Page 1]")

        # After 10 turns, call maybe_summarise() to compress old context
        memory.maybe_summarise(llm_client, model=SUMMARY_MODEL)

        history = memory.get_history()   # list of dicts for prompt injection
    """

    def __init__(self, max_turns: int = MAX_HISTORY_TURNS) -> None:
        self._messages: list[Message] = []
        self.max_turns = max_turns
        self._summaries: list[str] = []   # accumulated summary text

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
        self._summaries.clear()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history(self, exclude_last_user: bool = False) -> list[dict]:
        """
        Return the conversation history as a list of {role, content} dicts,
        limited to the most recent `max_turns` complete exchanges.

        If summarisation has been performed, the summary is prepended as
        a system message so the model has full context.

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

        result: list[dict] = []

        # Prepend accumulated summaries as a system message
        if self._summaries:
            combined_summary = (
                "[CONVERSATION SUMMARY — earlier turns compressed to save context]\n"
                + "\n".join(self._summaries)
            )
            result.append({"role": "system", "content": combined_summary})

        result.extend(m.to_dict() for m in messages)
        return result

    def get_display_messages(self) -> list[dict]:
        """
        Return all messages (no truncation) for rendering in the Streamlit
        chat UI. Does NOT include summary system messages.
        """
        return [m.to_dict() for m in self._messages if not m.is_summary]

    @property
    def turn_count(self) -> int:
        """Number of complete user+assistant turns in this session."""
        return sum(1 for m in self._messages if m.role == "user")

    @property
    def is_empty(self) -> bool:
        return len(self._messages) == 0

    def last_user_message(self) -> Optional[str]:
        for msg in reversed(self._messages):
            if msg.role == "user":
                return msg.content
        return None

    def last_assistant_message(self) -> Optional[str]:
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
            f"summaries={len(self._summaries)}, "
            f"max_turns={self.max_turns})"
        )

    # ------------------------------------------------------------------
    # Summarisation (Exercise 2)
    # ------------------------------------------------------------------

    def should_summarise(self) -> bool:
        """
        Return True if the in-memory message list is large enough to warrant
        summarisation. Triggers when messages exceed 2× max_turns (i.e., we
        have more old turns that need compressing than we plan to keep verbatim).
        """
        return len(self._messages) > self.max_turns * 2

    def maybe_summarise(self, llm_client, model: str = SUMMARY_MODEL) -> bool:
        """
        Summarise older turns if the threshold is reached.
        Called from app.py after each assistant response is added.

        Args:
            llm_client: OpenAI client instance (already configured).
            model:      Model name for summarisation.

        Returns:
            True if summarisation was performed, False otherwise.
        """
        if not self.should_summarise():
            return False

        # Identify the oldest turns to summarise (all except the last max_turns)
        keep_count = self.max_turns * 2  # keep last N messages verbatim
        if len(self._messages) <= keep_count:
            return False

        to_summarise = self._messages[:-keep_count]
        keep_verbatim = self._messages[-keep_count:]

        # Format turns for the summarisation prompt
        turns_text = "\n".join(
            f"{'User' if m.role == 'user' else 'Assistant'}: {m.content[:300]}"
            for m in to_summarise
        )

        summary_prompt = (
            "You are summarising a student's conversation with the BVRIT college chatbot. "
            "Condense the following conversation turns into 2-3 sentences capturing the "
            "key topics discussed, facts mentioned, and any student preferences or context "
            "(e.g., interested in CSE, asked about hostel, mentioned her name is Priya). "
            "Be factual and concise. Use past tense.\n\n"
            f"TURNS TO SUMMARISE:\n{turns_text}"
        )

        try:
            completion = llm_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=200,
                temperature=0.2,
            )
            summary_text = completion.choices[0].message.content.strip()
        except Exception as exc:
            # Don't fail the conversation if summarisation fails
            summary_text = (
                f"[Earlier conversation covered: "
                f"{', '.join(m.content[:50] for m in to_summarise if m.role == 'user')[:200]}]"
            )

        # Store summary and replace old messages with verbatim recent turns
        self._summaries.append(summary_text)
        self._messages = keep_verbatim
        return True

    def token_estimate(self) -> int:
        """Rough token estimate for the current history (4 chars ≈ 1 token)."""
        total_chars = sum(len(m.content) for m in self._messages)
        total_chars += sum(len(s) for s in self._summaries)
        return total_chars // 4


# ---------------------------------------------------------------------------
# User Profile (Exercise 3)
# ---------------------------------------------------------------------------

@dataclass
class UserProfile:
    """Persistent user profile stored across sessions."""
    user_id: str
    name: str = ""
    branch_interest: str = ""   # e.g., "CSE", "ECE"
    questions_asked: list[str] = field(default_factory=list)
    session_count: int = 0
    created_at: str = ""
    last_seen: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_system_prompt_snippet(self) -> str:
        """
        Format the profile as a system prompt injection for personalisation.
        Returns empty string if no meaningful profile data.
        """
        parts = []
        if self.name:
            parts.append(f"The student's name is {self.name}.")
        if self.branch_interest:
            parts.append(f"They have expressed interest in {self.branch_interest}.")
        if self.session_count > 1:
            parts.append(f"This is their session #{self.session_count} with this chatbot.")
        if not parts:
            return ""
        return "USER CONTEXT (from previous sessions): " + " ".join(parts)


def load_user_profile(user_id: str) -> UserProfile:
    """
    Load a user profile from disk. Creates a new profile if not found.

    Args:
        user_id: Unique identifier for the user (e.g., student email or ID).

    Returns:
        UserProfile instance.
    """
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = PROFILES_DIR / f"{_sanitise_id(user_id)}.json"

    if profile_path.exists():
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            return UserProfile(**data)
        except Exception:
            pass  # Fall through to create new profile

    return UserProfile(
        user_id=user_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        last_seen=datetime.now(timezone.utc).isoformat(),
    )


def save_user_profile(profile: UserProfile) -> None:
    """Persist a user profile to disk."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile.last_seen = datetime.now(timezone.utc).isoformat()
    profile_path = PROFILES_DIR / f"{_sanitise_id(profile.user_id)}.json"
    profile_path.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def update_profile_from_conversation(
    profile: UserProfile,
    user_message: str,
    assistant_message: str,
) -> None:
    """
    Extract facts from a conversation turn and update the user profile.
    Looks for name introductions and branch interest mentions.
    """
    msg_lower = user_message.lower()

    # Extract name mentions (e.g., "I'm Priya" or "my name is Priya")
    name_match = re.search(
        r"(?:i'm|i am|my name is|call me)\s+([A-Za-z]+)", user_message, re.IGNORECASE
    )
    if name_match and not profile.name:
        profile.name = name_match.group(1).capitalize()

    # Extract branch interest
    for branch in ["cse", "ece", "eee", "it", "ai&ml", "aiml", "cse-aiml"]:
        if branch in msg_lower:
            profile.branch_interest = branch.upper()
            break

    # Track questions (limit to last 20)
    profile.questions_asked.append(user_message[:100])
    if len(profile.questions_asked) > 20:
        profile.questions_asked = profile.questions_asked[-20:]


def _sanitise_id(user_id: str) -> str:
    """Convert user_id to a safe filename component."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", user_id)[:64]

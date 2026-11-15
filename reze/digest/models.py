"""Plain data carried through the Channel Digest pipeline. Holds no Telegram objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class SourceMessage:
    chat_id: int
    title: str
    username: str
    priority: int
    message_id: int
    date: datetime  # naive UTC
    text: str
    is_forward: bool = False
    media_kind: str = ""
    link: Optional[str] = None


@dataclass
class ChannelBatch:
    chat_id: int
    title: str
    username: str
    priority: int
    messages: List[SourceMessage] = field(default_factory=list)
    checkpoint: int = 0  # highest message id fetched for this channel in this run


@dataclass
class ChannelSection:
    title: str
    bullets: List[str]
    links: List[str] = field(default_factory=list)

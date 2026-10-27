"""
Data models and schemas for Reze.
Pydantic models for validated web requests, responses, and internal data structures.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class ProfileClockConfig(BaseModel):
    name_clock_enabled: bool = False
    bio_clock_enabled: bool = False
    clock_format: str = "%H:%M"
    name_template: str = "{name} | {time}"
    bio_template: str = "{bio} • {time}"
    original_name: Optional[str] = ""
    original_bio: Optional[str] = ""
    timezone: str = "Asia/Tehran"
    interval_minutes: int = 1


class GroupConfig(BaseModel):
    chat_id: int
    chat_title: Optional[str] = None
    antiflood_enabled: bool = False
    antiflood_limit: int = 5
    antiflood_seconds: int = 5
    antiflood_action: str = "mute"
    antiraid_enabled: bool = False
    antiraid_limit: int = 10
    antiraid_seconds: int = 60
    antilink_enabled: bool = False
    rules: str = ""
    welcome_enabled: bool = False
    welcome_text: str = "Welcome {mention} to {title}!"
    goodbye_enabled: bool = False
    goodbye_text: str = "Goodbye {name}!"
    cleanservice_enabled: bool = False
    log_channel_id: int = 0
    slowmode_seconds: int = 0


class WarningRecord(BaseModel):
    id: int
    chat_id: int
    user_id: int
    reason: str
    warned_by: int
    created_at: datetime


class FilterRecord(BaseModel):
    keyword: str
    reply_text: str


class BlacklistRecord(BaseModel):
    trigger: str
    action: str = "delete"


class AdminLogRecord(BaseModel):
    id: int
    chat_id: Optional[int]
    action: str
    performer_id: int
    target_id: Optional[int]
    details: Optional[str]
    created_at: datetime


class ServiceStats(BaseModel):
    uptime_seconds: float
    commands_executed: int
    errors_count: int
    configured_groups: int
    name_clock_active: bool
    bio_clock_active: bool
    telegram_connected: bool

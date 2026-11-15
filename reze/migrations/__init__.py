"""Ordered migration registry for REZE 3.0.

Append new migrations here; never edit an applied one. Each entry is executed
once, inside a transaction, and recorded in ``schema_migrations``.
"""

from __future__ import annotations

from reze.core.migrations import Migration
from reze.migrations import v3, v4, v5, v6

MIGRATIONS = [
    Migration(version=3, name="reze3_services", apply=v3.apply),
    Migration(version=4, name="reze3_search", apply=v4.apply),
    Migration(version=5, name="channel_digest", apply=v5.apply),
    Migration(version=6, name="style_assistant", apply=v6.apply),
]

MIGRATIONS.sort(key=lambda migration: migration.version)

__all__ = ["MIGRATIONS"]

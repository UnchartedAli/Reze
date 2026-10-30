"""REZE 3 personal OS services.

Every service is local-first, owner-scoped and writes only to the existing
SQLite database through versioned migrations.
"""

from reze.personal.crm import CRMService, crm_service
from reze.personal.decisions import DecisionService, decision_service
from reze.personal.expenses import ExpenseService, expense_service
from reze.personal.focus import FocusService, focus_service
from reze.personal.life_graph import LifeGraphService, life_graph
from reze.personal.memory import MemoryService, memory_service
from reze.personal.projects import ProjectService, project_service
from reze.personal.timeline import TimelineService, timeline_service
from reze.personal.writing import WritingService, writing_service

__all__ = [
    "CRMService",
    "DecisionService",
    "ExpenseService",
    "FocusService",
    "LifeGraphService",
    "MemoryService",
    "ProjectService",
    "TimelineService",
    "WritingService",
    "crm_service",
    "decision_service",
    "expense_service",
    "focus_service",
    "life_graph",
    "memory_service",
    "project_service",
    "timeline_service",
    "writing_service",
]

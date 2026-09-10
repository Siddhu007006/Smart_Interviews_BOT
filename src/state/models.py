"""
State models for Hive Automation Bot.

Represents the internal state structures for persistence and recovery.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid

from src.utils import WorkflowState, VerdictType


@dataclass
class Credentials:
    """Credentials for persistence (non-sensitive fields only)"""
    username: str
    login_url: str


@dataclass
class Submission:
    """
    Represents a single submission attempt.
    
    Attributes:
        problem_id: Problem identifier
        attempt_number: Attempt number (1-5)
        code: Submitted code
        language: Programming language
        verdict: Submission verdict
        error_message: Error message if failed
        execution_time: Execution time in seconds
        memory_used: Memory used in MB
        timestamp: Submission timestamp
    """
    problem_id: str
    attempt_number: int
    code: str
    language: str
    verdict: VerdictType
    error_message: Optional[str] = None
    execution_time: Optional[float] = None
    memory_used: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "problem_id": self.problem_id,
            "attempt_number": self.attempt_number,
            "code": self.code,
            "language": self.language,
            "verdict": self.verdict.value,
            "error_message": self.error_message,
            "execution_time": self.execution_time,
            "memory_used": self.memory_used,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Submission":
        """Create from dictionary"""
        data = data.copy()
        data["verdict"] = VerdictType(data["verdict"])
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


@dataclass
class ProblemProgress:
    """
    Represents progress on a single problem.
    
    Attributes:
        problem_id: Problem identifier
        title: Problem title
        solved: Whether problem is solved
        failed: Whether problem failed
        attempts: Number of attempts
        submissions: List of submission attempts
        last_error: Last error encountered
    """
    problem_id: str
    title: str
    solved: bool = False
    failed: bool = False
    attempts: int = 0
    submissions: List[Submission] = field(default_factory=list)
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "problem_id": self.problem_id,
            "title": self.title,
            "solved": self.solved,
            "failed": self.failed,
            "attempts": self.attempts,
            "submissions": [s.to_dict() for s in self.submissions],
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProblemProgress":
        """Create from dictionary"""
        data = data.copy()
        data["submissions"] = [
            Submission.from_dict(s) for s in data.get("submissions", [])
        ]
        return cls(**data)


@dataclass
class SessionState:
    """
    Represents current session state.
    
    Attributes:
        session_id: Unique session identifier
        authenticated: Whether user is authenticated
        credentials: User credentials (username, login_url)
        on_problem_list: Whether on problem list page
        workflow_state: Current workflow state
        current_problem: Current problem being solved
        created_at: Session creation timestamp
        last_activity: Last activity timestamp
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    authenticated: bool = False
    credentials: Optional[Credentials] = None
    on_problem_list: bool = False
    workflow_state: WorkflowState = WorkflowState.IDLE
    current_problem: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "session_id": self.session_id,
            "authenticated": self.authenticated,
            "credentials": {
                "username": self.credentials.username,
                "login_url": self.credentials.login_url,
            } if self.credentials else None,
            "on_problem_list": self.on_problem_list,
            "workflow_state": self.workflow_state.value,
            "current_problem": self.current_problem,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        """Create from dictionary"""
        data = data.copy()

        if creds_data := data.get("credentials"):
            data["credentials"] = Credentials(**creds_data)

        data["workflow_state"] = WorkflowState(data.get("workflow_state", "idle"))
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["last_activity"] = datetime.fromisoformat(data["last_activity"])

        return cls(**data)


@dataclass
class BotState:
    """
    Complete bot state for persistence and recovery.
    
    Attributes:
        session: Current session state
        problems_queue: Queue of problems to solve
        progress: Progress on each problem
        completed_problems: List of completed problem IDs
        failed_problems: List of failed problem IDs
        total_sessions: Total number of sessions
        last_checkpoint: Last checkpoint timestamp
    """
    session: SessionState = field(default_factory=SessionState)
    problems_queue: List[str] = field(default_factory=list)
    progress: Dict[str, ProblemProgress] = field(default_factory=dict)
    completed_problems: List[str] = field(default_factory=list)
    failed_problems: List[str] = field(default_factory=list)
    total_sessions: int = 0
    last_checkpoint: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "session": self.session.to_dict(),
            "problems_queue": self.problems_queue,
            "progress": {
                pid: progress.to_dict()
                for pid, progress in self.progress.items()
            },
            "completed_problems": self.completed_problems,
            "failed_problems": self.failed_problems,
            "total_sessions": self.total_sessions,
            "last_checkpoint": self.last_checkpoint.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotState":
        """Create from dictionary"""
        data = data.copy()

        data["session"] = SessionState.from_dict(data["session"])
        data["progress"] = {
            pid: ProblemProgress.from_dict(p)
            for pid, p in data.get("progress", {}).items()
        }
        data["last_checkpoint"] = datetime.fromisoformat(data["last_checkpoint"])

        return cls(**data)

    def add_problem_progress(self, problem_id: str, title: str) -> None:
        """Add progress tracking for a problem"""
        if problem_id not in self.progress:
            self.progress[problem_id] = ProblemProgress(
                problem_id=problem_id,
                title=title,
            )

    def mark_problem_solved(self, problem_id: str) -> None:
        """Mark problem as solved"""
        if problem_id in self.progress:
            self.progress[problem_id].solved = True

        if problem_id not in self.completed_problems:
            self.completed_problems.append(problem_id)

        if problem_id in self.failed_problems:
            self.failed_problems.remove(problem_id)

    def mark_problem_failed(self, problem_id: str, reason: str) -> None:
        """Mark problem as failed"""
        if problem_id in self.progress:
            self.progress[problem_id].failed = True
            self.progress[problem_id].last_error = reason

        if problem_id not in self.failed_problems:
            self.failed_problems.append(problem_id)

        if problem_id in self.completed_problems:
            self.completed_problems.remove(problem_id)

    def get_stats(self) -> Dict[str, int]:
        """Get progress statistics"""
        return {
            "total": len(self.progress),
            "completed": len(self.completed_problems),
            "failed": len(self.failed_problems),
            "pending": len(self.problems_queue),
        }

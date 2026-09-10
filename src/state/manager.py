"""
State persistence and management for bot recovery.

Handles:
- Saving and loading bot state
- Atomic file writes with locking
- Problem progress tracking
- Checkpoint management
"""

import json
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

from src.utils import get_logger, StateError, LogContext, HIVE_BOT_STATE_FILE
from .models import BotState, SessionState, Credentials

logger = get_logger(__name__)


class StateManager:
    """
    Manages persistent bot state.
    
    Features:
    - Load/save state from JSON files
    - Atomic writes with file locking
    - Problem progress tracking
    - Crash recovery support
    """

    def __init__(self, state_file: Optional[Path] = None):
        """
        Initialize StateManager.
        
        Args:
            state_file: Path to state persistence file
        """
        self.state_file = Path(state_file or HIVE_BOT_STATE_FILE)
        self.lock = threading.Lock()
        self.state = BotState()

        logger.debug(f"StateManager initialized with file: {self.state_file}")

        # Try to load existing state
        self._load_state()

    def _load_state(self) -> None:
        """Load state from file if it exists"""
        with LogContext("Loading persisted state"):
            try:
                if self.state_file.exists():
                    with open(self.state_file, 'r') as f:
                        data = json.load(f)
                        self.state = BotState.from_dict(data)
                    logger.info(f"State loaded from {self.state_file}")
                else:
                    logger.debug(f"No existing state file: {self.state_file}")

            except json.JSONDecodeError as e:
                logger.warning(f"Corrupted state file: {e}")
                self.state = BotState()
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
                self.state = BotState()

    def save_state(self) -> None:
        """
        Save state to file atomically.
        
        Raises:
            StateError: If save fails
        """
        with self.lock:
            with LogContext("Saving bot state"):
                try:
                    # Ensure directory exists
                    self.state_file.parent.mkdir(parents=True, exist_ok=True)

                    # Write to temporary file first
                    temp_file = self.state_file.with_suffix('.tmp')
                    with open(temp_file, 'w') as f:
                        json.dump(self.state.to_dict(), f, indent=2)

                    # Atomic rename
                    temp_file.replace(self.state_file)
                    logger.debug(f"State saved to {self.state_file}")

                except Exception as e:
                    logger.error(f"Failed to save state: {e}")
                    raise StateError(f"Failed to save state: {e}") from e

    def create_checkpoint(self) -> None:
        """
        Create a checkpoint (backup) of current state.
        
        Creates a timestamped backup for recovery.
        """
        with LogContext("Creating state checkpoint"):
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                checkpoint_file = self.state_file.with_stem(
                    f"{self.state_file.stem}_checkpoint_{timestamp}"
                )

                with open(checkpoint_file, 'w') as f:
                    json.dump(self.state.to_dict(), f, indent=2)

                logger.info(f"Checkpoint created: {checkpoint_file}")

            except Exception as e:
                logger.warning(f"Failed to create checkpoint: {e}")

    def get_current_state(self) -> BotState:
        """Get current bot state"""
        return self.state

    def get_session_state(self) -> SessionState:
        """Get current session state"""
        return self.state.session

    def update_session(self, authenticated: bool, credentials: Optional[Credentials] = None) -> None:
        """
        Update session state after authentication.
        
        Args:
            authenticated: Whether user is authenticated
            credentials: User credentials (username, login_url)
        """
        with LogContext("Updating session state"):
            self.state.session.authenticated = authenticated

            if credentials:
                self.state.session.credentials = credentials
                logger.info(f"Session updated for user: {credentials.username}")

            self.state.session.last_activity = datetime.now()
            self.save_state()

    def mark_on_problem_list(self, on_list: bool) -> None:
        """
        Update problem list status.
        
        Args:
            on_list: Whether on problem list page
        """
        self.state.session.on_problem_list = on_list
        self.state.session.last_activity = datetime.now()
        self.save_state()

    def add_problem(self, problem_id: str, title: str) -> None:
        """
        Add problem to progress tracking.
        
        Args:
            problem_id: Problem identifier
            title: Problem title
        """
        with LogContext(f"Adding problem {problem_id}"):
            self.state.add_problem_progress(problem_id, title)
            if problem_id not in self.state.problems_queue:
                self.state.problems_queue.append(problem_id)
            self.save_state()

    def mark_problem_solved(self, problem_id: str) -> None:
        """
        Mark problem as solved.
        
        Args:
            problem_id: Problem identifier
        """
        with LogContext(f"Marking problem {problem_id} as solved"):
            self.state.mark_problem_solved(problem_id)
            logger.info(f"Problem marked as solved: {problem_id}")
            self.save_state()

    def mark_problem_failed(self, problem_id: str, reason: str) -> None:
        """
        Mark problem as failed.
        
        Args:
            problem_id: Problem identifier
            reason: Failure reason
        """
        with LogContext(f"Marking problem {problem_id} as failed"):
            self.state.mark_problem_failed(problem_id, reason)
            logger.warning(f"Problem marked as failed: {problem_id} - {reason}")
            self.save_state()

    def get_progress_stats(self) -> dict:
        """Get progress statistics"""
        return self.state.get_stats()

    def reset_state(self) -> None:
        """Reset state to initial"""
        with LogContext("Resetting bot state"):
            self.state = BotState()
            self.save_state()
            logger.info("State reset to initial")

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure state is saved"""
        self.save_state()
        return False

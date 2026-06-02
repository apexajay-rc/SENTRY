"""
Action tracking and timeout management for SENTRY.
Tracks applied actions and auto-resumes limits after timeout.
"""

import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ActionRecord:
    """Record of an applied action."""
    pid: int
    action_type: str  # 'cpu', 'memory', 'io', 'combined'
    timestamp: float
    cpu_weight: Optional[int] = None
    memory_limit: Optional[int] = None
    io_weight: Optional[int] = None


class ActionTracker:
    """
    Tracks applied actions and manages auto-resume timeouts.
    """
    
    def __init__(self, resume_seconds=10):
        """
        Initialize action tracker.
        
        Args:
            resume_seconds (int): Time before automatically resuming limits
        """
        self.resume_seconds = resume_seconds
        self.actions: Dict[int, ActionRecord] = {}
    
    def record_action(self, pid, action_type, cpu_weight=None, 
                     memory_limit=None, io_weight=None):
        """
        Record an applied action.
        
        Args:
            pid (int): Process ID
            action_type (str): Type of action ('cpu', 'memory', 'io', 'combined')
            cpu_weight (int): CPU weight applied, if any
            memory_limit (int): Memory limit applied, if any
            io_weight (int): I/O weight applied, if any
        """
        self.actions[pid] = ActionRecord(
            pid=pid,
            action_type=action_type,
            timestamp=time.time(),
            cpu_weight=cpu_weight,
            memory_limit=memory_limit,
            io_weight=io_weight
        )
    
    def should_resume(self, pid):
        """
        Check if an action on a PID should be resumed (timeout expired).
        
        Args:
            pid (int): Process ID
        
        Returns:
            bool: True if timeout expired, False otherwise
        """
        if pid not in self.actions:
            return False
        
        record = self.actions[pid]
        elapsed = time.time() - record.timestamp
        
        return elapsed >= self.resume_seconds
    
    def get_expired_pids(self):
        """
        Get list of PIDs with expired timeouts.
        
        Returns:
            list: PIDs that should have limits resumed
        """
        return [pid for pid in self.actions if self.should_resume(pid)]
    
    def resume_action(self, pid):
        """
        Mark an action as resumed (remove from tracking).
        
        Args:
            pid (int): Process ID
        """
        if pid in self.actions:
            del self.actions[pid]
    
    def get_action_info(self, pid):
        """
        Get info about an active action.
        
        Args:
            pid (int): Process ID
        
        Returns:
            ActionRecord or None
        """
        return self.actions.get(pid)
    
    def cleanup_expired(self):
        """
        Remove all expired actions from tracking.
        
        Returns:
            list: PIDs that were cleaned up
        """
        expired = self.get_expired_pids()
        for pid in expired:
            self.resume_action(pid)
        return expired
    
    def get_active_actions_count(self):
        """Get count of currently active actions."""
        return len(self.actions)
    
    def get_active_actions(self):
        """Get all currently active actions."""
        return list(self.actions.values())

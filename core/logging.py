"""
Structured JSON logging module for SENTRY.
Provides audit trail in JSON format for integration with monitoring stacks.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: LogRecord to format
        
        Returns:
            str: JSON-formatted log entry
        """
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, "event_type"):
            log_data["event_type"] = record.event_type
        if hasattr(record, "pid"):
            log_data["pid"] = record.pid
        if hasattr(record, "process_name"):
            log_data["process_name"] = record.process_name
        if hasattr(record, "cpu"):
            log_data["cpu"] = record.cpu
        if hasattr(record, "memory"):
            log_data["memory"] = record.memory
        if hasattr(record, "io"):
            log_data["io"] = record.io
        if hasattr(record, "stress_score"):
            log_data["stress_score"] = record.stress_score
        if hasattr(record, "stress_level"):
            log_data["stress_level"] = record.stress_level
        if hasattr(record, "action"):
            log_data["action"] = record.action
        if hasattr(record, "cpu_weight"):
            log_data["cpu_weight"] = record.cpu_weight
        if hasattr(record, "memory_limit"):
            log_data["memory_limit"] = record.memory_limit
        if hasattr(record, "io_weight"):
            log_data["io_weight"] = record.io_weight
        
        return json.dumps(log_data, default=str)


class SentryLogger:
    """
    Structured logger for SENTRY audit trail.
    Logs to both JSON file and console.
    """
    
    def __init__(self, log_file: str = "sentry_audit.json", 
                 console: bool = True, console_level: str = "INFO"):
        """
        Initialize SENTRY logger.
        
        Args:
            log_file (str): Path to JSON log file
            console (bool): Also log to console
            console_level (str): Console logging level
        """
        self.log_file = log_file
        self.logger = logging.getLogger("sentry")
        self.logger.setLevel(logging.DEBUG)
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # File handler (JSON)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(file_handler)
        
        # Console handler (if enabled)
        if console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(getattr(logging, console_level))
            formatter = logging.Formatter(
                "[%(asctime)s] %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
    
    def log_metrics(self, cpu: float, memory: float, io: float, 
                   stress_score: float, stress_level: str):
        """
        Log system metrics snapshot.
        
        Args:
            cpu (float): CPU usage percentage
            memory (float): Memory usage percentage
            io (float): I/O wait percentage
            stress_score (float): Computed stress score
            stress_level (str): Classification level
        """
        record = logging.LogRecord(
            name="sentry",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="System metrics",
            args=(),
            exc_info=None
        )
        record.event_type = "metrics"
        record.cpu = cpu
        record.memory = memory
        record.io = io
        record.stress_score = stress_score
        record.stress_level = stress_level
        
        self.logger.handle(record)
    
    def log_process_identified(self, pid: int, process_name: str, 
                              process_score: float):
        """
        Log identification of top resource consumer.
        
        Args:
            pid (int): Process ID
            process_name (str): Process name
            process_score (float): Resource consumption score
        """
        record = logging.LogRecord(
            name="sentry",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Top process identified: {process_name}",
            args=(),
            exc_info=None
        )
        record.event_type = "process_identified"
        record.pid = pid
        record.process_name = process_name
        record.cpu = process_score  # Reuse for process score
        
        self.logger.handle(record)
    
    def log_action_applied(self, pid: int, process_name: str, 
                          stress_level: str, action: str,
                          cpu_weight: Optional[int] = None,
                          memory_limit: Optional[int] = None,
                          io_weight: Optional[int] = None):
        """
        Log application of throttling action.
        
        Args:
            pid (int): Process ID
            process_name (str): Process name
            stress_level (str): Stress level that triggered action
            action (str): Action description
            cpu_weight (int): CPU weight applied
            memory_limit (int): Memory limit applied
            io_weight (int): I/O weight applied
        """
        record = logging.LogRecord(
            name="sentry",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg=f"Action applied to {process_name} (PID {pid}): {action}",
            args=(),
            exc_info=None
        )
        record.event_type = "action_applied"
        record.pid = pid
        record.process_name = process_name
        record.stress_level = stress_level
        record.action = action
        record.cpu_weight = cpu_weight
        record.memory_limit = memory_limit
        record.io_weight = io_weight
        
        self.logger.handle(record)
    
    def log_action_resumed(self, pid: int, process_name: str, action: str):
        """
        Log resumption of limits on a process.
        
        Args:
            pid (int): Process ID
            process_name (str): Process name
            action (str): Action resumed
        """
        record = logging.LogRecord(
            name="sentry",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Limits resumed for {process_name} (PID {pid}): {action}",
            args=(),
            exc_info=None
        )
        record.event_type = "action_resumed"
        record.pid = pid
        record.process_name = process_name
        record.action = action
        
        self.logger.handle(record)
    
    def log_cooldown_active(self, pid: int, process_name: str):
        """
        Log cooldown period preventing action.
        
        Args:
            pid (int): Process ID
            process_name (str): Process name
        """
        record = logging.LogRecord(
            name="sentry",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg=f"Cooldown active for {process_name} (PID {pid})",
            args=(),
            exc_info=None
        )
        record.event_type = "cooldown_active"
        record.pid = pid
        record.process_name = process_name
        
        self.logger.handle(record)
    
    def log_system_stable(self):
        """Log system is stable (no action needed)."""
        record = logging.LogRecord(
            name="sentry",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="System stable, no action required",
            args=(),
            exc_info=None
        )
        record.event_type = "system_stable"
        
        self.logger.handle(record)
    
    def log_error(self, message: str, exception: Optional[Exception] = None):
        """
        Log an error.
        
        Args:
            message (str): Error message
            exception (Exception): Optional exception object
        """
        if exception:
            self.logger.exception(message)
        else:
            self.logger.error(message)
    
    def log_info(self, message: str, **kwargs):
        """
        Log generic info message with custom fields.
        
        Args:
            message (str): Log message
            **kwargs: Additional fields to include in JSON
        """
        record = logging.LogRecord(
            name="sentry",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=message,
            args=(),
            exc_info=None
        )
        
        # Attach custom fields
        for key, value in kwargs.items():
            setattr(record, key, value)
        
        self.logger.handle(record)
    
    def get_log_file(self) -> Path:
        """Get path to log file."""
        return Path(self.log_file)

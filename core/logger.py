"""
core/logger.py

Production-grade structured JSON logger for SENTRY.
Renamed from 'logging.py' to avoid standard library namespace collisions in CI/CD.
"""

import logging
import json
import sys
from datetime import datetime

class SentryJSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module
        }
        
        # Inject custom audit fields if present
        if hasattr(record, "pid"): log_record["pid"] = record.pid
        if hasattr(record, "reason"): log_record["reason"] = record.reason
        
        return json.dumps(log_record)

class StructuredLogger:
    def __init__(self, name: str, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.propagate = False # Prevent duplicate stdout spam
        
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(SentryJSONFormatter())
            self.logger.addHandler(handler)

    def info(self, msg: str):
        self.logger.info(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def audit(self, action: str, pid: int, target: str, details: str):
        """Dedicated method for Ring-0 mitigation tracking."""
        extra = {"pid": pid, "reason": action, "details": details}
        # In standard logging, passing extra injects attributes into the LogRecord
        self.logger.warning(f"AUDIT_EVENT: {action} on {target} (PID: {pid}) - {details}", extra=extra)

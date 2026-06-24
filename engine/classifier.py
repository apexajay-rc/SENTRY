"""
Workload Classification Engine

Responsible for determining the intent of a workload
based on process metadata.

This module does NOT:

- make mitigation decisions
- apply cgroups
- modify priorities

It only answers:

"What kind of workload is this?"
"""

from enum import Enum


class WorkloadType(str, Enum):
    SYSTEM = "system"
    INTERACTIVE = "interactive"
    BACKGROUND = "background"
    BATCH = "batch"
    UNKNOWN = "unknown"


SYSTEM_PROCESSES = {
    "systemd",
    "dbus-daemon",
    "gnome-shell",
    "xorg",
    "pipewire",
    "pulseaudio",
    "networkmanager",
    "sshd",
    "udevd",
}


INTERACTIVE_PROCESSES = {
    "firefox",
    "chrome",
    "chromium",
    "code",
    "cursor",
    "discord",
    "kitty",
    "alacritty",
    "wezterm",
    "gnome-terminal",
    "konsole",
    "thunderbird",
    "slack",
}


BATCH_PROCESSES = {
    "gcc",
    "g++",
    "clang",
    "clang++",
    "cargo",
    "rustc",
    "make",
    "cmake",
    "ninja",
    "ffmpeg",
    "docker",
    "podman",
    "pytest",
    "python",
    "python3",
}


BACKGROUND_PROCESSES = {
    "rsync",
    "updatedb",
    "tracker-miner-fs",
    "tracker-extract",
    "syncthing",
    "backupd",
}


def classify_process(process_name: str) -> WorkloadType:
    """
    Classify a process into a workload category.

    Args:
        process_name: Process executable name

    Returns:
        WorkloadType
    """

    if not process_name:
        return WorkloadType.UNKNOWN

    name = process_name.lower().strip()

    if name in SYSTEM_PROCESSES:
        return WorkloadType.SYSTEM

    if name in INTERACTIVE_PROCESSES:
        return WorkloadType.INTERACTIVE

    if name in BATCH_PROCESSES:
        return WorkloadType.BATCH

    if name in BACKGROUND_PROCESSES:
        return WorkloadType.BACKGROUND

    return WorkloadType.UNKNOWN


def workload_priority(workload: WorkloadType) -> int:
    """
    Higher number = more important.

    Used later by mitigation policy.
    """

    priorities = {
        WorkloadType.SYSTEM: 100,
        WorkloadType.INTERACTIVE: 80,
        WorkloadType.UNKNOWN: 50,
        WorkloadType.BACKGROUND: 30,
        WorkloadType.BATCH: 20,
    }

    return priorities[workload]


def mitigation_candidate_score(
    cpu_percent: float,
    memory_percent: float,
    workload: WorkloadType,
) -> float:
    """
    Rank how attractive a process is as a mitigation target.

    Higher score = throttle first.
    """

    resource_score = (0.7 * cpu_percent) + (0.3 * memory_percent)

    priority_penalty = workload_priority(workload)

    return round(resource_score - priority_penalty, 2)

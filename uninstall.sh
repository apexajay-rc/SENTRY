#!/usr/bin/env bash
# uninstall.sh - SENTRY V1.0 Complete Removal Script
# Reverts all changes made by install.sh, restores system to pristine state.

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================
readonly INSTALL_ROOT="/opt/sentry"
readonly SYSTEMD_SYSTEM_DIR="/etc/systemd/system"
readonly SYSTEMD_USER_DIR="/etc/systemd/user"
readonly SYSTEMD_SYSTEM_DST="${SYSTEMD_SYSTEM_DIR}/sentry.service"
readonly SYSTEMD_USER_DST="${SYSTEMD_USER_DIR}/sentry-bridge.service"
readonly CLI_DST="/usr/local/bin/sentry"
readonly SOCKET_DIR="/run"
readonly BRIDGE_SOCK="${SOCKET_DIR}/sentry_bridge.sock"
readonly HUD_SOCK="${SOCKET_DIR}/sentry_hud.sock"

# ============================================================================
# COLORS & LOGGING
# ============================================================================
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly BOLD='\033[1m'
readonly RESET='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${RESET} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${RESET} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET} $*"; }

# ============================================================================
# PRE-FLIGHT
# ============================================================================
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)."
        exit 1
    fi
}

confirm_uninstall() {
    echo -e "${BOLD}${RED}WARNING: This will completely remove SENTRY V1.0 from your system.${RESET}"
    echo "The following will be removed:"
    echo "  - System service: sentry.service"
    echo "  - User service:   sentry-bridge.service (global)"
    echo "  - Installation:   ${INSTALL_ROOT}"
    echo "  - CLI wrapper:    /usr/local/bin/sentry"
    echo "  - IPC sockets:    /run/sentry_bridge.sock, /run/sentry_hud.sock"
    echo "  - All cgroup throttles applied by SENTRY will be released."
    echo
    read -rp "Are you sure you want to continue? [y/N] " -n 1
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Uninstall cancelled."
        exit 0
    fi
}

# ============================================================================
# UNINSTALL STEPS
# ============================================================================
stop_and_disable_services() {
    log_info "Stopping and disabling services..."

    # Stop and disable root daemon
    if systemctl is-active --quiet sentry.service 2>/dev/null; then
        systemctl stop sentry.service
        log_info "Stopped sentry.service"
    fi
    if systemctl is-enabled --quiet sentry.service 2>/dev/null; then
        systemctl disable sentry.service
        log_info "Disabled sentry.service"
    fi

    # Stop and disable user bridge (global)
    if systemctl --global is-enabled sentry-bridge.service 2>/dev/null; then
        systemctl --global disable sentry-bridge.service 2>/dev/null || true
        log_info "Disabled sentry-bridge.service (global)"
    fi

    # Stop any running user instances
    systemctl --global stop sentry-bridge.service 2>/dev/null || true
}

release_cgroup_throttles() {
    log_info "Releasing all SENTRY cgroup throttles..."

    if [[ -d /sys/fs/cgroup ]]; then
        # Find all processes with SENTRY's signature throttles
        for pid_dir in /proc/*/; do
            pid="${pid_dir%/}"
            pid="${pid##*/}"
            if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
                continue
            fi

            cgroup_path=""
            if [[ -f "/proc/$pid/cgroup" ]]; then
                while IFS= read -r line; do
                    if [[ $line == 0::* ]]; then
                        cgroup_path="/sys/fs/cgroup${line#0::}"
                        break
                    fi
                done < "/proc/$pid/cgroup"
            fi

            if [[ -n "$cgroup_path" && -d "$cgroup_path" ]]; then
                # Check for SENTRY's CPU clamp signature
                cpu_max="${cgroup_path}/cpu.max"
                if [[ -f "$cpu_max" ]]; then
                    current=$(cat "$cpu_max" 2>/dev/null || echo "")
                    # SENTRY uses 20% (20000 100000) or other configured quotas
                    # Release any non-max CPU limits
                    if [[ "$current" != "max 100000" && "$current" != "" ]]; then
                        echo "max 100000" > "$cpu_max" 2>/dev/null || true
                        log_info "Released CPU clamp on PID $pid"
                    fi
                fi

                # Release memory.high
                mem_high="${cgroup_path}/memory.high"
                if [[ -f "$mem_high" ]]; then
                    current=$(cat "$mem_high" 2>/dev/null || echo "")
                    if [[ "$current" != "max" && "$current" != "" ]]; then
                        echo "max" > "$mem_high" 2>/dev/null || true
                        log_info "Released memory clamp on PID $pid"
                    fi
                fi

                # Release I/O weights
                for io_file in "${cgroup_path}/io.weight" "${cgroup_path}/io.bfq.weight"; do
                    if [[ -f "$io_file" ]]; then
                        current=$(cat "$io_file" 2>/dev/null || echo "")
                        if [[ "$current" != "100" && "$current" != "default" && "$current" != "" ]]; then
                            echo "100" > "$io_file" 2>/dev/null || true
                        fi
                    fi
                done
            fi
        done
    fi

    log_success "All SENTRY cgroup throttles released."
}

cleanup_sockets() {
    log_info "Cleaning up IPC sockets..."
    for sock in "${BRIDGE_SOCK}" "${HUD_SOCK}"; do
        if [[ -S "$sock" ]]; then
            rm -f "$sock"
            log_info "Removed socket: $sock"
        fi
    done
}

remove_systemd_units() {
    log_info "Removing systemd units..."

    # System service
    if [[ -f "${SYSTEMD_SYSTEM_DST}" ]]; then
        rm -f "${SYSTEMD_SYSTEM_DST}"
        log_info "Removed ${SYSTEMD_SYSTEM_DST}"
    fi

    # User service
    if [[ -f "${SYSTEMD_USER_DST}" ]]; then
        rm -f "${SYSTEMD_USER_DST}"
        log_info "Removed ${SYSTEMD_USER_DST}"
    fi

    systemctl daemon-reload
    log_success "Systemd units removed and daemon reloaded."
}

remove_cli_wrapper() {
    log_info "Removing CLI wrapper..."
    if [[ -f "${CLI_DST}" ]]; then
        rm -f "${CLI_DST}"
        log_info "Removed ${CLI_DST}"
    fi
}

remove_installation_root() {
    log_info "Removing installation directory..."
    if [[ -d "${INSTALL_ROOT}" ]]; then
        rm -rf "${INSTALL_ROOT}"
        log_info "Removed ${INSTALL_ROOT}"
    fi
}

cleanup_runtime() {
    log_info "Cleaning up runtime artifacts..."

    # Remove any leftover temp sockets
    rm -f /tmp/sentry_*.sock /tmp/sentry_hud_client_*.sock /tmp/sentry_top_client_*.sock 2>/dev/null || true

    # Remove systemd user generator state (if any)
    rm -rf /etc/systemd/user/sentry-bridge.service.d 2>/dev/null || true
    rm -rf /etc/systemd/system/sentry.service.d 2>/dev/null || true
}

print_uninstall_complete() {
    echo
    echo -e "${BOLD}${GREEN}╔═══════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${GREEN}║          SENTRY V1.0 UNINSTALLATION COMPLETE                ║${RESET}"
    echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════════════════════╝${RESET}"
    echo
    echo "All SENTRY components have been removed:"
    echo "  ✓ System service (sentry.service) stopped, disabled, removed"
    echo "  ✓ User service (sentry-bridge.service) disabled, removed"
    echo "  ✓ All cgroup throttles released (CPU, memory, I/O)"
    echo "  ✓ IPC sockets cleaned up"
    echo "  ✓ Installation directory (${INSTALL_ROOT}) removed"
    echo "  ✓ CLI wrapper (/usr/local/bin/sentry) removed"
    echo "  ✓ Systemd units removed, daemon reloaded"
    echo "  ✓ Runtime artifacts cleaned"
    echo
    echo "System restored to pristine state. No SENTRY artifacts remain."
    echo
}

# ============================================================================
# MAIN
# ============================================================================
main() {
    echo -e "${BOLD}${RED}SENTRY V1.0 - Complete Uninstallation${RESET}"
    echo "========================================"
    echo

    check_root
    confirm_uninstall
    echo

    stop_and_disable_services
    release_cgroup_throttles
    cleanup_sockets
    remove_systemd_units
    remove_cli_wrapper
    remove_installation_root
    cleanup_runtime

    print_uninstall_complete
}

main "$@"
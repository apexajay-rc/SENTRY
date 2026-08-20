#!/usr/bin/env bash
# install.sh - SENTRY V1.0 Production Deployment Script
# Installs SENTRY as system + user systemd services with unified CLI.
# Idempotent, strict, and reversible.

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================
readonly INSTALL_ROOT="/opt/sentry"
readonly SYSTEMD_SYSTEM_DIR="/etc/systemd/system"
readonly SYSTEMD_USER_DIR="/etc/systemd/user"
readonly SYSTEMD_SYSTEM_SRC="packaging/sentry.service"
readonly SYSTEMD_USER_SRC="packaging/sentry-bridge.service"
readonly SYSTEMD_SYSTEM_DST="${SYSTEMD_SYSTEM_DIR}/sentry.service"
readonly SYSTEMD_USER_DST="${SYSTEMD_USER_DIR}/sentry-bridge.service"
readonly CLI_SRC="tools/sentry_cli.py"
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
# PRE-FLIGHT CHECKS
# ============================================================================
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)."
        exit 1
    fi
}

check_source_files() {
    local missing=0
    local required_files=(
        "${SYSTEMD_SYSTEM_SRC}"
        "${SYSTEMD_USER_SRC}"
        "${CLI_SRC}"
        "daemon/main.py"
        "core/cgroup_manager.py"
        "core/safety_guard.py"
        "core/config.py"
        "core/logger.py"
        "core/metrics.py"
        "core/procfs.py"
        "core/process.py"
        "core/psi_sensor.py"
        "core/classifier.py"
        "core/platform_adapter.py"
        "core/proc_scanner.py"
        "engine/pressure.py"
        "engine/selector.py"
        "engine/feedback.py"
        "engine/timeseries.py"
        "engine/classifier.py"
        "engine/reconciliation.py"
        "tools/desktop_bridge.py"
        "tools/sentry_top.py"
        "tools/sentry_hud.py"
        "tools/sentry_cli.py"
        "sentry_config.yaml"
        "requirements.txt"
        "model/__init__.py"
        "model/pressure.py"
        "model/action_outcome.py"
        "model/candidate.py"
    )

    local missing=0
    for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            log_error "Missing required file: $file"
            missing=1
        fi
    done

    if [[ $missing -eq 1 ]]; then
        log_error "Run this script from the SENTRY repository root."
        exit 1
    fi
}

# ============================================================================
# INSTALLATION STEPS
# ============================================================================
create_directories() {
    log_info "Creating installation directories..."
    mkdir -p "${INSTALL_ROOT}"
    mkdir -p "${INSTALL_ROOT}/core"
    mkdir -p "${INSTALL_ROOT}/engine"
    mkdir -p "${INSTALL_ROOT}/daemon"
    mkdir -p "${INSTALL_ROOT}/tools"
    mkdir -p "${INSTALL_ROOT}/model"
    mkdir -p "${INSTALL_ROOT}/packaging"
}

copy_files() {
    log_info "Copying SENTRY source files to ${INSTALL_ROOT}..."

    # Core modules
    cp core/*.py "${INSTALL_ROOT}/core/"

    # Engine modules
    cp engine/*.py "${INSTALL_ROOT}/engine/"

    # Daemon
    cp daemon/main.py "${INSTALL_ROOT}/daemon/"

    # Model
    cp model/*.py "${INSTALL_ROOT}/model/"

    # Tools
    cp tools/desktop_bridge.py "${INSTALL_ROOT}/tools/"
    cp tools/sentry_top.py "${INSTALL_ROOT}/tools/"
    cp tools/sentry_hud.py "${INSTALL_ROOT}/tools/"
    cp tools/sentry_cli.py "${INSTALL_ROOT}/tools/"
    # Package init for module execution (python -m tools.sentry_cli)
    touch "${INSTALL_ROOT}/tools/__init__.py"

    # Config and requirements
    cp sentry_config.yaml "${INSTALL_ROOT}/"
    cp requirements.txt "${INSTALL_ROOT}/"

    # Packaging (systemd units will be installed separately)
    cp packaging/sentry.service "${INSTALL_ROOT}/packaging/"
    cp packaging/sentry-bridge.service "${INSTALL_ROOT}/packaging/"

    # Make scripts executable
    chmod +x "${INSTALL_ROOT}/daemon/main.py"
    chmod +x "${INSTALL_ROOT}/tools/desktop_bridge.py"
    chmod +x "${INSTALL_ROOT}/tools/sentry_top.py"
    chmod +x "${INSTALL_ROOT}/tools/sentry_hud.py"
    chmod +x "${INSTALL_ROOT}/tools/sentry_cli.py"
}

setup_python_env() {
    log_info "Setting up Python virtual environment..."
    if [[ ! -d "${INSTALL_ROOT}/venv" ]]; then
        python3 -m venv "${INSTALL_ROOT}/venv"
    fi
    "${INSTALL_ROOT}/venv/bin/pip" install --upgrade pip >/dev/null
    "${INSTALL_ROOT}/venv/bin/pip" install -r "${INSTALL_ROOT}/requirements.txt" >/dev/null
    log_success "Python environment ready."
}

setup_socket_directories() {
    log_info "Setting up runtime socket directories..."
    mkdir -p "${SOCKET_DIR}"
    # Daemon creates sockets and chowns to SUDO_UID/SUDO_GID
    # Ensure parent exists with correct permissions
}

install_systemd_units() {
    log_info "Installing systemd service units..."

    # System service (root daemon)
    cp "${SYSTEMD_SYSTEM_SRC}" "${SYSTEMD_SYSTEM_DST}"

    # User service (desktop bridge) - install to system-wide user directory
    mkdir -p "${SYSTEMD_USER_DIR}"
    cp "${SYSTEMD_USER_SRC}" "${SYSTEMD_USER_DST}"

    systemctl daemon-reload
    log_success "Systemd units installed."
}

install_cli_wrapper() {
    log_info "Installing unified CLI wrapper..."
    cat > "${CLI_DST}" <<'EOF'
#!/usr/bin/env bash
# sentry - Unified CLI wrapper for SENTRY V1.0
cd /opt/sentry && exec /opt/sentry/venv/bin/python -m tools.sentry_cli "$@"
EOF
    chmod +x "${CLI_DST}"
    log_success "CLI wrapper installed at ${CLI_DST}"
}

enable_services() {
    log_info "Enabling and starting services..."

    # Root daemon
    systemctl enable --now sentry.service

    # User bridge - enable globally for all users (systemd user instances)
    log_info "Enabling user session bridge service (will start on graphical login)..."
    systemctl --global enable sentry-bridge.service 2>/dev/null || true

    log_success "Services enabled."
}

verify_installation() {
    log_info "Verifying installation..."
    sleep 2  # Give daemon time to start

    if systemctl is-active --quiet sentry.service; then
        log_success "SENTRY daemon is running."
    else
        log_error "SENTRY daemon failed to start. Check logs with: journalctl -u sentry -f"
        return 1
    fi

    # Check socket creation (may take a moment)
    for i in {1..5}; do
        if [[ -S "${BRIDGE_SOCK}" && -S "${HUD_SOCK}" ]]; then
            log_success "IPC sockets created successfully."
            break
        fi
        sleep 1
    done

    if [[ ! -S "${BRIDGE_SOCK}" || ! -S "${HUD_SOCK}" ]]; then
        log_warn "IPC sockets not yet visible (daemon may still be starting)."
    fi
}

print_post_install_info() {
    echo
    echo -e "${BOLD}${GREEN}╔═══════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${GREEN}║          SENTRY V1.0 INSTALLATION COMPLETE                  ║${RESET}"
    echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════════════════════╝${RESET}"
    echo
    echo -e "${BOLD}Installation Path:${RESET} ${INSTALL_ROOT}"
    echo -e "${BOLD}System Service:${RESET} sentry.service (root, enabled, running)"
    echo -e "${BOLD}User Service:${RESET} sentry-bridge.service (enabled for graphical sessions)"
    echo -e "${BOLD}CLI Command:${RESET} sentry (installed at /usr/local/bin/sentry)"
    echo -e "${BOLD}Config File:${RESET} ${INSTALL_ROOT}/sentry_config.yaml"
    echo -e "${BOLD}Logs:${RESET} sentry logs  |  journalctl -u sentry -f"
    echo
    echo -e "${BOLD}CLI Usage:${RESET}"
    echo "  sentry hud        Interactive HUD (real-time telemetry)"
    echo "  sentry status     One-shot status check"
    echo "  sentry logs -f    Follow daemon logs"
    echo "  sentry restart    Restart all SENTRY services"
    echo "  sentry config     View/edit configuration"
    echo "  sentry version    Show version information"
    echo
    echo -e "${BOLD}User-Space Components (auto-started on graphical login):${RESET}"
    echo "  Desktop Bridge:  Monitors active window, grants Spatial Immunity"
    echo
    echo -e "${BOLD}Stress Test:${RESET} ${INSTALL_ROOT}/stress_test.sh (requires stress-ng)"
    echo
    echo -e "${YELLOW}Note:${RESET} The daemon runs as root via systemd. The desktop bridge"
    echo "runs automatically in your user session upon graphical login,"
    echo "connecting via secured Unix sockets at /run/sentry_bridge.sock"
    echo "and /run/sentry_hud.sock."
    echo
}

# ============================================================================
# MAIN
# ============================================================================
main() {
    echo -e "${BOLD}${BLUE}SENTRY V1.0 - Production Deployment${RESET}"
    echo "======================================"
    echo

    check_root
    check_source_files
    create_directories
    copy_files
    setup_python_env
    setup_socket_directories
    install_systemd_units
    install_cli_wrapper
    enable_services
    verify_installation
    print_post_install_info
}

main "$@"
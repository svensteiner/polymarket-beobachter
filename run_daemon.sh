#!/bin/bash
# =============================================================================
# POLYMARKET WEATHER BOT - DAEMON MIT AUTO-RESTART
# =============================================================================
# Startet den Scheduler im Dauerlauf. Bei Absturz automatischer Neustart
# nach kurzer Pause. Self-Healer repariert Probleme beim naechsten Run.
#
# Nutzung:
#   ./run_daemon.sh          # Startet im Vordergrund
#   ./run_daemon.sh &        # Startet im Hintergrund
#   nohup ./run_daemon.sh &  # Ueberlebt Terminal-Schliessung
#
# Stoppen:
#   kill $(cat data/daemon.pid)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="data/daemon.pid"
LOG_FILE="logs/daemon.log"
MAX_RESTARTS=50          # Max Neustarts bevor Daemon aufgibt
RESTART_DELAY=30         # Sekunden zwischen Neustarts
CRASH_COOLDOWN=300       # 5 Min Cooldown nach 3+ schnellen Crashes
RAPID_CRASH_WINDOW=120   # Crash innerhalb 2 Min = "schneller Crash"

mkdir -p logs data

# Pruefe ob schon ein Daemon laeuft
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Daemon laeuft bereits (PID $OLD_PID)"
        echo "Stoppen mit: kill $OLD_PID"
        exit 1
    fi
    rm -f "$PID_FILE"
fi

# PID schreiben
echo $$ > "$PID_FILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cleanup() {
    log "Daemon gestoppt (PID $$)"
    rm -f "$PID_FILE"
    # Lockfile aufraeumen falls vorhanden
    rm -f "data/cockpit.lock"
    exit 0
}

trap cleanup EXIT INT TERM

log "========================================="
log "Daemon gestartet (PID $$)"
log "Intervall: 15 Minuten"
log "Max Restarts: $MAX_RESTARTS"
log "========================================="

restart_count=0
rapid_crash_count=0
last_start_time=0

while [ $restart_count -lt $MAX_RESTARTS ]; do
    restart_count=$((restart_count + 1))
    current_time=$(date +%s)

    # Schneller Crash erkennen
    if [ $last_start_time -gt 0 ]; then
        elapsed=$((current_time - last_start_time))
        if [ $elapsed -lt $RAPID_CRASH_WINDOW ]; then
            rapid_crash_count=$((rapid_crash_count + 1))
            log "WARNUNG: Schneller Crash #$rapid_crash_count (nach ${elapsed}s)"

            if [ $rapid_crash_count -ge 3 ]; then
                log "3+ schnelle Crashes - Cooldown ${CRASH_COOLDOWN}s"
                sleep $CRASH_COOLDOWN
                rapid_crash_count=0
            fi
        else
            rapid_crash_count=0
        fi
    fi

    last_start_time=$current_time

    log "Start #$restart_count: python3 cockpit.py --scheduler"

    # Lockfile aufraeumen falls stale
    rm -f "data/cockpit.lock"

    # Scheduler starten
    python3 cockpit.py --scheduler --no-color 2>&1 | tee -a "$LOG_FILE" || true

    exit_code=${PIPESTATUS[0]:-1}

    if [ $exit_code -eq 0 ]; then
        log "Scheduler sauber beendet (exit 0)"
        break
    elif [ $exit_code -eq 3 ]; then
        log "Scheduler pausiert (exit 3) - warte 5 Min"
        sleep 300
    else
        log "Scheduler abgestuerzt (exit $exit_code) - Neustart in ${RESTART_DELAY}s"
        sleep $RESTART_DELAY
    fi
done

if [ $restart_count -ge $MAX_RESTARTS ]; then
    log "KRITISCH: Max Restarts ($MAX_RESTARTS) erreicht - Daemon gibt auf"
    exit 1
fi

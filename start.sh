#!/usr/bin/env bash
# Event-App starten (Backend + Frontend)
# Erreichbar im LAN unter http://<DEINE-LAN-IP>:3000

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# docker compose (neu) oder docker-compose (alt) wählen
if docker compose version &>/dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

# LAN-IP ermitteln (Mac: en0/en1, Linux: hostname -I)
get_lan_ip() {
    if [[ "$(uname)" == "Darwin" ]]; then
        ipconfig getifaddr en0 2>/dev/null \
            || ipconfig getifaddr en1 2>/dev/null \
            || echo "<DEINE-LAN-IP>"
    else
        hostname -I 2>/dev/null | awk '{print $1}' || echo "<DEINE-LAN-IP>"
    fi
}

echo "Event-App wird gestartet..."
echo

# DB starten falls nicht healthy
if ! $DOCKER_COMPOSE -f "$SCRIPT_DIR/docker-compose.yml" ps db 2>/dev/null | grep -q "healthy"; then
    echo "Starte PostgreSQL..."
    $DOCKER_COMPOSE -f "$SCRIPT_DIR/docker-compose.yml" up -d db
    sleep 5
fi

# Backend starten
echo "Starte Backend auf Port 8000..."
cd "$SCRIPT_DIR/backend"
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
sleep 3

# Frontend starten
echo "Starte Frontend auf Port 3000..."
cd "$SCRIPT_DIR/frontend"
npx next dev --hostname 0.0.0.0 --port 3000 &
FRONTEND_PID=$!
sleep 5

LAN_IP=$(get_lan_ip)

echo
echo "========================================"
echo "  Event-App läuft!"
echo "  PC:     http://localhost:3000"
echo "  iPhone: http://$LAN_IP:3000"
echo "  Admin:  http://localhost:3000/admin"
echo "========================================"
echo
echo "Ctrl+C zum Beenden..."

cleanup() {
    echo
    echo "Server werden gestoppt..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    echo "Gestoppt."
}
trap cleanup INT TERM

wait "$BACKEND_PID" "$FRONTEND_PID"

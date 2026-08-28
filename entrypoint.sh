#!/bin/bash
# Entrypoint do container (runtime autônomo T3) — Tezk42/FSB.
#
# Sobe o display virtual e entrega o controlo ao worker. O container não tem
# display real, mas o Web Agent (Electron em modo tray) exige um X.
#
# Argumentos do `docker run` chegam ao worker:
#   docker run <imagem> --dry-run --json
#   docker run <imagem> --fluxo classificar_nf --inicio-ate-planilha

set -euo pipefail

DISPLAY_NUM="${DISPLAY:-:99}"
GEOMETRIA="${XVFB_GEOMETRY:-1280x800x24}"

if [ ! -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ]; then
  echo "[entrypoint] iniciando Xvfb em ${DISPLAY_NUM} (${GEOMETRIA})"
  Xvfb "${DISPLAY_NUM}" -screen 0 "${GEOMETRIA}" -nolisten tcp > /tmp/xvfb.log 2>&1 &
  XVFB_PID=$!
  # Espera o socket do X existir: iniciar Chromium/Web Agent contra um display
  # ainda não pronto falha de forma confusa, difícil de diagnosticar no log.
  for _ in $(seq 1 30); do
    [ -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ] && break
    sleep 0.5
  done
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "[entrypoint] ERRO: Xvfb não iniciou. Log:"
    cat /tmp/xvfb.log
    exit 1
  fi
  echo "[entrypoint] Xvfb ativo (pid ${XVFB_PID})"
fi
export DISPLAY="${DISPLAY_NUM}"

cd /app
# exec: o worker vira PID 1 e recebe os sinais do Docker diretamente, para que
# o cleanup (VPN, sessão remota) rode no `docker stop`.
exec python -m agent.worker "$@"

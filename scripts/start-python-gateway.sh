#!/usr/bin/env bash
export PORT=18790
cd /root/openclaw
echo "Starting Python gateway on port $PORT at $(date)"
exec /usr/bin/python3 -u /root/openclaw/gateway.py 2>&1

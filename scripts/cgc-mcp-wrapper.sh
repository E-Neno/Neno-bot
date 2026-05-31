#!/bin/bash
cd /tmp
export CGC_RUNTIME_DB_TYPE=kuzudb
export CGC_RUNTIME_DB_PATH=/home/admin/emotion-bot/.codegraphcontext/codegraph.kuzu
exec /home/admin/emotion-bot/venv/bin/cgc "$@"

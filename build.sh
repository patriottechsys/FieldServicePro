#!/usr/bin/env bash
set -o errexit

echo "==> Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Running database seed (idempotent — skips if data exists)..."
python seed_master.py

echo "==> Build complete."

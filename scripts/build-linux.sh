#!/usr/bin/env bash
set -euo pipefail
npm ci
npm --prefix frontend ci
npm --prefix frontend run build
npm run build:linux

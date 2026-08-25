#!/bin/bash
# Build script run by Cloudera AI Workbench (CML) when this project's
# Session, Job, or Application starts. Installs Python dependencies.
set -e
pip install --no-cache-dir -r requirements.txt

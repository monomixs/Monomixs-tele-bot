#!/bin/bash

# This command makes the script exit immediately if any part fails
set -e 

echo "--- Sourcing virtual environment ---"
source /opt/venv/bin/activate

echo "--- Starting Python bot script ---"
python main.py
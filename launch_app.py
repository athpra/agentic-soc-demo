"""
Entry point for the Cloudera AI Workbench Application.

Cloudera AI Workbench's "New Application" form runs a Python script (not an
arbitrary shell command), so this script's only job is to launch Streamlit
as a subprocess bound to the host/port Cloudera AI Workbench expects,
inheriting $CDSW_APP_PORT and all the other environment variables (like the
/tmp/jwt workload token) the platform sets up for the Application.

In the "New Application" form, set:
  Script:     launch_app.py
  Subdomain:  anything you like, e.g. agentic-soc
"""

import os
import subprocess
import sys

port = os.environ.get("CDSW_APP_PORT", "8090")

cmd = [
    sys.executable, "-m", "streamlit", "run", "app.py",
    "--server.port", port,
    "--server.address", "127.0.0.1",
    "--server.headless", "true",
    "--server.enableCORS", "false",
    "--server.enableXsrfProtection", "false",
]

subprocess.run(cmd, check=True)

# deploy/

Per the [Cloudera Blueprint Standard](https://github.com/kevinbtalbert/Cloudera-Blueprints-Standard),
this is where deployment configs/scripts would normally live. For this project they
intentionally stay at the repository root instead:

- **`cdsw-build.sh`** — Cloudera AI Workbench's Application build step looks for this
  file by convention at the project root; it isn't a configurable path, so moving it
  here would silently break the automatic build.
- **`launch_app.py`** — the CML Application's "Script" field is set to `launch_app.py`
  at the root. It *could* be moved and the field updated to `deploy/launch_app.py`, but
  it's kept alongside `cdsw-build.sh` so the two root-level deploy entry points aren't
  split across two locations.

See the main [README](../README.md)'s **Deploying on Cloudera AI Workbench** section for
the actual deployment steps.

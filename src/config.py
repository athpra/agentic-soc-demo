"""
Central configuration for the Agentic SOC demo.

Endpoint URLs and model IDs point at models deployed via Cloudera AI Registry
and served through Cloudera AI Inference Service. Both endpoints expose an
OpenAI-compatible /v1/chat/completions API, so the same client code (see
src/llm_client.py) talks to either one just by swapping base_url + model.
"""

import json
import os
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    key: str            # internal key used throughout the app
    label: str          # human-friendly display name
    role: str           # narrative role this model plays in the demo
    base_url: str       # OpenAI-compatible base URL for this endpoint
    model_id: str       # value sent in the "model" field of each request


# --- Cloudera AI Inference Service endpoints -------------------------------
#
# Fast, cheap model used for high-volume triage of raw telemetry -- routes
# high-risk telemetry for closer attention instead of treating every log
# the same.
QWEN_TRIAGE = ModelConfig(
    key="qwen2.5-7b-instruct",
    label="Qwen2.5-7B-Instruct",
    role="Fast Triage",
    base_url=(
        "https://ml-64288d82-5dd.go01-dem.ylcu-atmi.cloudera.site/"
        "namespaces/serving-default/endpoints/qwen25-7b-instruct/openai/v1"
    ),
    model_id="Qwen/Qwen2.5-7B-Instruct",
)

# Larger, higher-reasoning model used for deep, multi-source investigation of
# whatever the triage stage escalates, once noise has been filtered out.
NEMOTRON_INVESTIGATE = ModelConfig(
    key="nemotron-3-super-120b",
    label="Nemotron-3-Super-120B (A12B)",
    role="Deep Investigation",
    base_url=(
        "https://ml-64288d82-5dd.go01-dem.ylcu-atmi.cloudera.site/"
        "namespaces/serving-default/endpoints/goes---nemotron-3-super-120b/v1"
    ),
    model_id="nvidia/nemotron-3-super-120b-a12b",
)

MODELS = {
    QWEN_TRIAGE.key: QWEN_TRIAGE,
    NEMOTRON_INVESTIGATE.key: NEMOTRON_INVESTIGATE,
}

# --- Auth --------------------------------------------------------------
#
# Inside a Cloudera AI Workbench Session, Application, or Job, the platform
# mounts a short-lived JWT for the running workload at /tmp/jwt and keeps it
# refreshed for the lifetime of the workload. That token is accepted as a
# bearer token by Cloudera AI Inference Service endpoints in the same
# workspace, so we don't manage any separate API keys for this demo.
JWT_FILE = os.environ.get("CDSW_APIV2_JWT_FILE", "/tmp/jwt")


class TokenUnavailableError(RuntimeError):
    """Raised when no usable auth token can be found."""


def get_access_token() -> str:
    """Read a fresh access token for calling Cloudera AI Inference endpoints.

    Re-reads the token file on every call (rather than caching it) since
    Cloudera AI Workbench rotates the token underneath the running workload.

    Falls back to the CDP_TOKEN / CLOUDERA_AI_API_KEY env vars so the code
    can also be pointed at a token when run outside of a CML workload (e.g.
    a developer's laptop during local testing), if one is exported.
    """
    for env_var in ("CDP_TOKEN", "CLOUDERA_AI_API_KEY"):
        if os.environ.get(env_var):
            return os.environ[env_var]

    # The platform's token-refresh sidecar can take a moment to (re)populate
    # this file right after a session/application starts, so a request that
    # lands in that window can catch it mid-write, empty, or with
    # placeholder content. Retry with backoff (~11s total) rather than
    # failing on the very first read.
    max_attempts = 10
    delay = 0.4
    last_exc: Exception | None = None
    last_detail = ""

    for attempt in range(max_attempts):
        try:
            # utf-8-sig transparently strips a leading byte-order-mark if
            # present (invisible in a terminal `cat`, but poison to
            # json.loads) -- a no-op on a file with no BOM.
            with open(JWT_FILE, encoding="utf-8-sig") as f:
                raw = f.read()
            if not raw.strip():
                raise ValueError("file was empty")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Tolerate any other stray leading bytes/whitespace before
                # the JSON object actually starts, by re-parsing from the
                # first '{' we can find.
                brace = raw.find("{")
                if brace == -1:
                    raise
                data = json.loads(raw[brace:])
            return data["access_token"]
        except FileNotFoundError as exc:
            last_exc, last_detail = exc, "file does not exist"
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc, last_detail = exc, f"content was not valid JSON ({exc}); {len(raw)} bytes read"
        except KeyError as exc:
            last_exc = exc
            # Never surface token *values* here -- only structural info (key
            # names, value types/lengths) so a pasted error can't leak a secret.
            shape = {
                k: (f"str[{len(v)}]" if isinstance(v, str) else type(v).__name__)
                for k, v in data.items()
            }
            last_detail = f"parsed JSON but had no 'access_token' key; keys present: {shape}"
        except OSError as exc:
            last_exc, last_detail = exc, f"OS error reading file: {exc}"
        if attempt < max_attempts - 1:
            time.sleep(delay)
            delay = min(delay * 1.3, 2.0)

    if isinstance(last_exc, FileNotFoundError):
        raise TokenUnavailableError(
            f"Could not find a JWT at {JWT_FILE} after retrying for ~11s. "
            "This app expects to run inside a Cloudera AI Workbench Session, "
            "Application, or Job, which mounts a workload token "
            "automatically. For local development, export CDP_TOKEN with a "
            "valid Cloudera AI token."
        ) from last_exc

    raise TokenUnavailableError(
        f"Could not get a usable access_token from {JWT_FILE} after "
        f"{max_attempts} attempts over ~11s. Last attempt: {last_detail}."
    ) from last_exc


SAMPLE_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_logs")

LOG_SOURCES = {
    "auth_events": {"label": "Identity / Auth Logs", "file": "auth_events.jsonl"},
    "firewall_events": {"label": "Firewall / Proxy Logs", "file": "firewall_events.jsonl"},
    "edr_alerts": {"label": "EDR Endpoint Alerts", "file": "edr_alerts.jsonl"},
    "cloud_audit_events": {"label": "Cloud Audit Logs", "file": "cloud_audit_events.jsonl"},
}

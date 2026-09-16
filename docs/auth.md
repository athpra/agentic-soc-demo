# Auth

Inside a Cloudera AI Workbench Session, Application, or Job, the platform mounts a
short-lived workload JWT at `/tmp/jwt` and keeps it refreshed automatically. This app reads
that token fresh on every request (`src/config.get_access_token`) and uses it as the bearer
token against both endpoints — no API key management needed when running in-platform.

For local development outside of Cloudera AI Workbench, export a valid token instead:

```bash
export CDP_TOKEN=<your Cloudera AI token>
```

## Reliability notes

`get_access_token()` retries for ~11s with backoff before giving up, and tolerates a
leading byte-order-mark or stray bytes ahead of the JSON payload, since the platform's
token-refresh sidecar can momentarily leave `/tmp/jwt` empty or mid-write right after a
session/application starts.

If calls fail with a token error even though `cat /tmp/jwt` from a Session terminal shows
a valid token: Sessions and Applications run in **separate containers**, so a Session's
`/tmp/jwt` is not the same file an Application actually reads. Use the "🔧 Debug: inspect
`/tmp/jwt`" expander on the home page — it reads the file from inside the Application
itself and reports its shape (never its contents) without leaking the token value.

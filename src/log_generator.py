"""
Synthetic SOC telemetry generator.

Produces four log sources (identity/auth, firewall/proxy, EDR endpoint
alerts, cloud audit) that share one coherent narrative: a phishing email
opened on a finance laptop leads to a beacon, a stolen session, a new AWS
access key, and a bucket made public. That chain is interleaved with plain
business-as-usual noise and one red-herring noisy vulnerability scanner, so
a triage model actually has to separate signal from noise rather than every
"interesting-looking" row being the answer.

Each event carries a hidden "scenario" field (not shown to the LLM) used
only so the UI can display ground truth / scoring for the demo:
  - "baseline"                     normal, uninteresting activity
  - "scn_phish_to_exfil"           the real attack chain
  - "scn_noisy_scanner"            high-volume but benign red herring
"""

import json
import os
import random
from datetime import datetime, timedelta, timezone

SEED = 42
DAY = datetime(2026, 8, 24, tzinfo=timezone.utc)

EMPLOYEES = [
    ("j.chen", "10.20.4.31", "SEA-LAP-1002"),
    ("r.patel", "10.20.4.55", "SEA-LAP-1044"),
    ("k.oduya", "10.20.7.12", "AUS-LAP-2091"),
    ("t.nguyen", "10.20.7.88", "AUS-LAP-2114"),
    ("s.moreau", "10.20.9.20", "NYC-LAP-3007"),
    ("m.alvarez", "10.20.9.61", "FIN-LAP-2214"),  # the victim in the attack chain
]
SAAS_DOMAINS = ["github.com", "slack.com", "office.com", "salesforce.com", "zoom.us", "atlassian.net"]
CLOUD_ACTIONS_BENIGN = ["ConsoleLogin", "DescribeInstances", "GetObject", "ListBuckets", "AssumeRole"]

ATTACKER_IP = "185.220.101.47"       # known hosting/anonymization range, used in the attack chain
SCANNER_IP = "198.51.100.77"         # red herring: noisy but benign internet scanner


def _ts(base: datetime, minutes: float) -> str:
    return (base + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rand_ext_ip(rng: random.Random) -> str:
    return f"{rng.randint(20,209)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(1,254)}"


def generate_auth_events(rng: random.Random) -> list[dict]:
    events = []
    idx = 1

    # baseline: normal badge-in logins across the day
    for minute in range(0, 600, 22):
        user, ip, _host = rng.choice(EMPLOYEES)
        events.append({
            "id": f"auth-{idx:04d}", "timestamp": _ts(DAY, minute), "event_type": "authentication",
            "source": "AD-DC01", "action": "login_success", "user": user, "src_ip": ip,
            "geo": "US", "auth_method": "password+mfa", "mfa": True, "scenario": "baseline",
        })
        idx += 1

    # occasional harmless typo/failed-then-success, still baseline
    for minute in (95, 260, 410):
        user, ip, _host = rng.choice(EMPLOYEES)
        events.append({
            "id": f"auth-{idx:04d}", "timestamp": _ts(DAY, minute), "event_type": "authentication",
            "source": "AD-DC01", "action": "login_failed", "user": user, "src_ip": ip,
            "geo": "US", "auth_method": "password+mfa", "mfa": True, "scenario": "baseline",
        })
        idx += 1

    # --- attack chain: stolen session used from attacker infra, no MFA, wrong geo ---
    events.append({
        "id": f"auth-{idx:04d}", "timestamp": _ts(DAY, 247), "event_type": "authentication",
        "source": "AD-DC01", "action": "login_success", "user": "m.alvarez", "src_ip": ATTACKER_IP,
        "geo": "NL", "auth_method": "session_token_replay", "mfa": False,
        "scenario": "scn_phish_to_exfil",
    })
    idx += 1

    rng.shuffle(events)
    return sorted(events, key=lambda e: e["timestamp"])


def generate_firewall_events(rng: random.Random) -> list[dict]:
    events = []
    idx = 1

    # baseline outbound SaaS traffic
    for minute in range(5, 600, 14):
        user, ip, host = rng.choice(EMPLOYEES)
        domain = rng.choice(SAAS_DOMAINS)
        events.append({
            "id": f"fw-{idx:04d}", "timestamp": _ts(DAY, minute), "event_type": "network_connection",
            "source": "PA-FW-EDGE01", "src_ip": ip, "src_host": host, "dst_domain": domain,
            "dst_ip": _rand_ext_ip(rng), "dst_port": 443, "protocol": "TCP", "action": "allowed",
            "bytes_out": rng.randint(4_000, 250_000), "category": "outbound", "scenario": "baseline",
        })
        idx += 1

    # red herring: noisy internet scanner hammering random ports, all blocked, no follow-through
    for minute in range(30, 560, 6):
        events.append({
            "id": f"fw-{idx:04d}", "timestamp": _ts(DAY, minute), "event_type": "network_connection",
            "source": "PA-FW-EDGE01", "src_ip": SCANNER_IP, "src_host": None,
            "dst_domain": None, "dst_ip": "10.20.1.10", "dst_port": rng.choice([22, 3389, 445, 8080, 5900]),
            "protocol": "TCP", "action": "blocked", "bytes_out": 0, "category": "scan",
            "scenario": "scn_noisy_scanner",
        })
        idx += 1

    # --- attack chain: beacon shortly after the phishing click, then a large exfil-sized transfer ---
    events.append({
        "id": f"fw-{idx:04d}", "timestamp": _ts(DAY, 232), "event_type": "network_connection",
        "source": "PA-FW-EDGE01", "src_ip": "10.20.9.61", "src_host": "FIN-LAP-2214",
        "dst_domain": "cdn-assets-storage.co", "dst_ip": "45.153.160.22", "dst_port": 443,
        "protocol": "TCP", "action": "allowed", "bytes_out": 18_000, "category": "outbound",
        "scenario": "scn_phish_to_exfil",
    })
    idx += 1
    events.append({
        "id": f"fw-{idx:04d}", "timestamp": _ts(DAY, 251), "event_type": "network_connection",
        "source": "PA-FW-EDGE01", "src_ip": "10.20.9.61", "src_host": "FIN-LAP-2214",
        "dst_domain": "cdn-assets-storage.co", "dst_ip": "45.153.160.22", "dst_port": 443,
        "protocol": "TCP", "action": "allowed", "bytes_out": 261_000_000, "category": "outbound",
        "scenario": "scn_phish_to_exfil",
    })
    idx += 1

    rng.shuffle(events)
    return sorted(events, key=lambda e: e["timestamp"])


def generate_edr_alerts(rng: random.Random) -> list[dict]:
    events = []
    idx = 1

    # baseline: a couple of low-severity, resolved nuisance alerts
    for minute, host, user in ((120, "AUS-LAP-2091", "k.oduya"), (340, "SEA-LAP-1044", "r.patel")):
        events.append({
            "id": f"edr-{idx:04d}", "timestamp": _ts(DAY, minute), "event_type": "endpoint_alert",
            "source": "EDR-Sensor", "host": host, "user": user, "alert_name": "Potentially Unwanted Program",
            "process": "installer.exe", "parent_process": "chrome.exe", "command_line": "installer.exe /silent",
            "severity": "low", "status": "resolved", "scenario": "baseline",
        })
        idx += 1

    # --- attack chain: phishing doc spawns encoded PowerShell ---
    events.append({
        "id": f"edr-{idx:04d}", "timestamp": _ts(DAY, 229), "event_type": "endpoint_alert",
        "source": "EDR-Sensor", "host": "FIN-LAP-2214", "user": "m.alvarez",
        "alert_name": "Suspicious Encoded PowerShell Command", "process": "powershell.exe",
        "parent_process": "outlook.exe",
        "command_line": "powershell.exe -nop -w hidden -enc JABjAGwAaQBlAG4AdAAgAD0AIABOAGUAdwAtAE8AYgBqAGUAYwB0AA==",
        "severity": "high", "status": "new", "scenario": "scn_phish_to_exfil",
    })
    idx += 1
    events.append({
        "id": f"edr-{idx:04d}", "timestamp": _ts(DAY, 230), "event_type": "endpoint_alert",
        "source": "EDR-Sensor", "host": "FIN-LAP-2214", "user": "m.alvarez",
        "alert_name": "LOLBin Living-off-the-Land Execution", "process": "rundll32.exe",
        "parent_process": "powershell.exe", "command_line": "rundll32.exe comsvcs.dll, MiniDump 1234 lsass.dmp full",
        "severity": "high", "status": "new", "scenario": "scn_phish_to_exfil",
    })
    idx += 1

    rng.shuffle(events)
    return sorted(events, key=lambda e: e["timestamp"])


def generate_cloud_audit_events(rng: random.Random) -> list[dict]:
    events = []
    idx = 1

    # baseline cloud console/API activity
    for minute in range(10, 600, 35):
        user, _ip, _host = rng.choice(EMPLOYEES)
        events.append({
            "id": f"cloud-{idx:04d}", "timestamp": _ts(DAY, minute), "event_type": "cloud_audit",
            "source": "AWS-CloudTrail", "actor": user, "action": rng.choice(CLOUD_ACTIONS_BENIGN),
            "resource": f"arn:aws:iam::123456789012:user/{user}", "src_ip": "10.20.1.5",
            "result": "success", "scenario": "baseline",
        })
        idx += 1

    # --- attack chain: persistence + public exposure, from attacker infra ---
    events.append({
        "id": f"cloud-{idx:04d}", "timestamp": _ts(DAY, 255), "event_type": "cloud_audit",
        "source": "AWS-CloudTrail", "actor": "m.alvarez", "action": "CreateAccessKey",
        "resource": "arn:aws:iam::123456789012:user/m.alvarez", "src_ip": ATTACKER_IP,
        "result": "success", "scenario": "scn_phish_to_exfil",
    })
    idx += 1
    events.append({
        "id": f"cloud-{idx:04d}", "timestamp": _ts(DAY, 258), "event_type": "cloud_audit",
        "source": "AWS-CloudTrail", "actor": "m.alvarez", "action": "PutBucketPolicy",
        "resource": "arn:aws:s3:::finance-quarterly-reports", "src_ip": ATTACKER_IP,
        "result": "success", "detail": "Policy grants s3:GetObject to Principal: *",
        "scenario": "scn_phish_to_exfil",
    })
    idx += 1

    rng.shuffle(events)
    return sorted(events, key=lambda e: e["timestamp"])


def generate_dataset(seed: int = SEED) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    return {
        "auth_events": generate_auth_events(rng),
        "firewall_events": generate_firewall_events(rng),
        "edr_alerts": generate_edr_alerts(rng),
        "cloud_audit_events": generate_cloud_audit_events(rng),
    }


def write_dataset(out_dir: str, seed: int = SEED) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for name, events in generate_dataset(seed).items():
        path = os.path.join(out_dir, f"{name}.jsonl")
        with open(path, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")


if __name__ == "__main__":
    target = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_logs")
    write_dataset(target)
    print(f"Wrote synthetic sample logs to {target}")

"""Local-only enforcement: verify (and optionally apply) the Step 9 controls.

Checks that the model server is loopback-only, privacy flags are off, data
lives inside the project and outside OneDrive, only the owner can read the
course data, and nothing sensitive is tracked by git. --egress runs a real
question while watching every TCP connection of our process and Ollama.

Usage (from the project root, venv active):
    python -m rag.security_check                 # run all checks
    python -m rag.security_check --harden        # restrict folder permissions
    python -m rag.security_check --egress        # also watch connections during a real Q&A
"""
import argparse
import os
import re
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from rag import config

IS_WINDOWS = os.name == "nt"
PROTECTED_DIRS = [config.DATA_DIR, config.RAW_DOCS_DIR]
# Well-known Windows SIDs, so the check works in any OS language.
SYSTEM_SID, ADMINS_SID = "*S-1-5-18", "*S-1-5-32-544"
ALLOWED_PRINCIPALS = {"NT AUTHORITY\\SYSTEM", "BUILTIN\\Administrators"}

SENSITIVE_TRACKED = re.compile(r"(\.pdf$|\.sqlite3$|(^|/)\.env|^data/(?!\.gitkeep$)"
                               r"|^docs/raw/(?!\.gitkeep$)|manifest\.json$)", re.IGNORECASE)
MUST_BE_IGNORED = ["data/chroma/chroma.sqlite3", "data/manifest.json",
                   "docs/raw/slides/example.pdf", ".env"]


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          cwd=config.BASE_DIR).stdout


def _current_user() -> str:
    return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"


def _is_loopback(addr: str) -> bool:
    host = addr.rsplit(":", 1)[0].strip("[]")
    return host in {"127.0.0.1", "::1", "0.0.0.0", "::", "*"} or host.startswith("127.")


# --------------------------------------------------------------------------- checks
def check_ollama_url():
    host = urlparse(config.OLLAMA_BASE_URL).hostname
    return host in config.LOOPBACK_HOSTS, f"code connects to {config.OLLAMA_BASE_URL}"


def check_ollama_listener():
    port = f":{urlparse(config.OLLAMA_BASE_URL).port}"
    listening = [line.split()[1] for line in _run(["netstat", "-an"]).splitlines()
                 if port in line and "LISTEN" in line.upper()]
    local = [a for a in listening if a.endswith(port)]
    if not local:
        return None, "Ollama is not running (start it, then re-check)"
    bad = [a for a in local if not (a.startswith("127.") or a.startswith("[::1]"))]
    return not bad, f"listening on {', '.join(sorted(set(local)))}"


def check_ollama_host_env():
    values = {"this process": os.environ.get("OLLAMA_HOST")}
    if IS_WINDOWS:
        import winreg
        for scope, root, key in [
            ("user", winreg.HKEY_CURRENT_USER, r"Environment"),
            ("machine", winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ]:
            try:
                with winreg.OpenKey(root, key) as k:
                    values[scope] = winreg.QueryValueEx(k, "OLLAMA_HOST")[0]
            except OSError:
                values[scope] = None
    set_values = {k: v for k, v in values.items() if v}
    bad = {k: v for k, v in set_values.items()
           if (urlparse(v if "//" in v else f"//{v}").hostname or "") not in config.LOOPBACK_HOSTS}
    detail = "not set (Ollama default: 127.0.0.1)" if not set_values else str(set_values)
    return not bad, f"OLLAMA_HOST {detail}"


def check_privacy_flags():
    expected = {"ANONYMIZED_TELEMETRY": "False", "LANGCHAIN_TRACING_V2": "false",
                "LANGSMITH_TRACING": "false", "HF_HUB_OFFLINE": "1"}
    wrong = {k: os.environ.get(k) for k, v in expected.items() if os.environ.get(k) != v}
    return not wrong, "telemetry/tracing/downloads off" if not wrong else f"wrong: {wrong}"


def check_data_location():
    problems = []
    for d in [config.CHROMA_DIR, config.RAW_DOCS_DIR, config.MANIFEST_PATH]:
        p = d.resolve()
        if config.BASE_DIR not in p.parents:
            problems.append(f"{p} is outside the project")
        if "onedrive" in str(p).lower():
            problems.append(f"{p} is inside OneDrive (would sync to the cloud)")
    drive = f" on drive {config.BASE_DIR.drive}" if IS_WINDOWS else ""
    return not problems, "; ".join(problems) or f"inside project, not in OneDrive{drive}"


def check_permissions():
    problems = []
    for d in PROTECTED_DIRS:
        if not d.exists():
            continue
        if IS_WINDOWS:
            # icacls prints "<path> PRINCIPAL:(perms)" then "   PRINCIPAL:(perms)" lines.
            principals = set()
            for line in _run(["icacls", str(d)]).splitlines():
                if ":(" in line:
                    principals.add(line.replace(str(d), "", 1).split(":(")[0].strip())
            extra = {p.lower() for p in principals} - \
                {p.lower() for p in ALLOWED_PRINCIPALS | {_current_user()}}
            if extra:
                problems.append(f"{d.name}/ readable by {sorted(extra)}")
        else:
            mode = stat.S_IMODE(d.stat().st_mode)
            if mode & 0o077:
                problems.append(f"{d.name}/ mode {oct(mode)} (group/others have access)")
    return not problems, "; ".join(problems) or "only owner, SYSTEM and Administrators"


def check_git():
    tracked = [f for f in _run(["git", "ls-files"]).splitlines() if SENSITIVE_TRACKED.search(f)]
    not_ignored = [p for p in MUST_BE_IGNORED
                   if subprocess.run(["git", "check-ignore", "-q", p],
                                     cwd=config.BASE_DIR).returncode != 0]
    problems = ([f"tracked: {tracked}"] if tracked else []) + \
               ([f"not ignored: {not_ignored}"] if not_ignored else [])
    return not problems, "; ".join(problems) or "no course data, DB, manifest or .env in git"


CHECKS = [
    ("Ollama URL in code is loopback", check_ollama_url),
    ("Ollama server listens on loopback only", check_ollama_listener),
    ("OLLAMA_HOST not exposing the server", check_ollama_host_env),
    ("Telemetry / cloud tracing disabled", check_privacy_flags),
    ("Data inside project, outside OneDrive", check_data_location),
    ("Course data readable only by owner", check_permissions),
    ("Nothing sensitive in git", check_git),
]


# --------------------------------------------------------------------------- harden
def harden() -> None:
    """Restrict docs/raw and data to the owner (+ SYSTEM, Administrators)."""
    for d in PROTECTED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        if IS_WINDOWS:
            # Grant first, then cut inheritance, so we never lock ourselves out.
            # (OI)(CI)F = full control, inherited by files and subfolders.
            _run(["icacls", str(d), "/grant:r", f"{_current_user()}:(OI)(CI)F",
                  f"{SYSTEM_SID}:(OI)(CI)F", f"{ADMINS_SID}:(OI)(CI)F"])
            _run(["icacls", str(d), "/inheritance:r"])
        else:
            for root, dirs, files in os.walk(d):
                os.chmod(root, 0o700)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o600)
        print(f"hardened {d}")


# --------------------------------------------------------------------------- egress
def _ollama_pids() -> dict[int, str]:
    pids = {}
    if IS_WINDOWS:
        for line in _run(["tasklist", "/FO", "CSV", "/NH"]).splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1 and "ollama" in parts[0].lower():
                pids[int(parts[1])] = parts[0]
    return pids


def egress_check(question: str) -> bool:
    """Ask a real question while recording any non-loopback TCP connection."""
    from rag.qa import answer

    watched = {os.getpid(): "python (this app)", **_ollama_pids()}
    seen: dict[tuple, str] = {}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            for line in _run(["netstat", "-ano", "-p", "TCP"]).splitlines():
                parts = line.split()
                if len(parts) == 5 and parts[0] == "TCP" and parts[4].isdigit():
                    pid, remote = int(parts[4]), parts[2]
                    if pid in watched and not _is_loopback(remote):
                        seen[(watched[pid], remote)] = parts[3]
            time.sleep(0.3)

    t = threading.Thread(target=sample, daemon=True)
    t.start()
    a = answer(question)
    stop.set()
    t.join()

    print(f"\nWatched processes: {sorted(set(watched.values()))}")
    print(f"Question: {question}\nAnswer ({a.seconds:.1f}s): {a.text[:150]}...")
    if seen:
        print("NON-LOCAL connections observed:")
        for (proc, remote), state in seen.items():
            print(f"  {proc} -> {remote} ({state})")
    else:
        print("No non-loopback TCP connections from the app or Ollama during the answer.")
    return not seen


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local-only controls")
    parser.add_argument("--harden", action="store_true", help="restrict folder permissions first")
    parser.add_argument("--egress", nargs="?", const="What is a SYN flood?", metavar="QUESTION",
                        help="watch network connections during a real Q&A")
    args = parser.parse_args()

    if args.harden:
        harden()
        print()

    failed = 0
    for name, check in CHECKS:
        ok, detail = check()
        mark = "PASS" if ok else "WARN" if ok is None else "FAIL"
        failed += ok is False
        print(f"[{mark}] {name:<40} {detail}")

    if args.egress is not None:
        if not IS_WINDOWS:
            print("\n--egress is implemented for Windows netstat only; use Wireshark instead.")
        elif not egress_check(args.egress):
            failed += 1

    print(f"\n{'ALL CHECKS PASSED' if not failed else f'{failed} CHECK(S) FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

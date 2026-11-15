"""Administrator rights, asked for only when they are needed and only once per batch.

The updater itself ALWAYS starts as a normal user (no administrator manifest, no relaunch at start). Only when the
install mode is 'All users' and a batch holds installers that need administrator rights (a Windows Setup.exe, a macOS
.pkg) does it start ONE elevated helper for the whole batch:
  Windows: this same program again with `--elevated-run <job file>` through ShellExecute 'runas' (one UAC prompt).
  macOS:   one `osascript ... with administrator privileges` that runs every staged .pkg.
'Just for me' never prompts. When the app already runs as administrator nothing is prompted at all.

What the helper may do is deliberately tiny, because it runs with rights the app does not otherwise have:
  - it only reads a job file that sits in the updater's own staging folder, next to the installers it names;
  - it re-checks the SHA256 of every installer right before it runs it (the staging folder is writable by the user);
  - the command line of each installer is built here from a fixed list, never taken from the job file (no command
    strings, no extra arguments, no paths outside the staging folder).
The logic is pure and tested with a fake backend (tests/helpers.py FakeBackend); the thin ctypes and osascript
launchers at the bottom cannot be exercised off their own operating system.
"""
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DECLINED = "Administrator permission was not given, so nothing was installed. Nothing was changed."
KINDS = ("exe", "pkg")


class ElevationError(Exception):
    pass


@dataclass
class Job:
    repo: str
    name: str
    kind: str            # 'exe' (Windows Setup.exe) or 'pkg' (macOS installer package)
    file: str
    sha256: str
    version: str = ""
    tag: str = ""


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def installer_command(kind, file):
    """The ONLY command lines the elevated side will run. Fixed here, never read from a file."""
    if kind == "exe":
        return [str(file), "/SILENT", "/NORESTART", "/SP-"]
    if kind == "pkg":
        return ["/usr/sbin/installer", "-pkg", str(file), "-target", "/"]
    raise ElevationError("unknown installer kind")


def write_job_file(jobs, stage_dir, name="elevated-job.json"):
    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    job_path = stage_dir / name
    result_path = stage_dir / "elevated-result.json"
    try:
        result_path.unlink()
    except OSError:
        pass
    data = {"format": 1, "result": result_path.name,
            "jobs": [{"repo": j.repo, "kind": j.kind, "file": Path(j.file).name, "sha256": j.sha256} for j in jobs]}
    tmp = job_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, job_path)
    return job_path, result_path


def read_job_file(job_path):
    """Validate a job file for the elevated side. Returns (jobs, result_path). Raises ElevationError on anything odd."""
    job_path = Path(job_path).resolve()
    stage = job_path.parent
    try:
        data = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ElevationError("job file unreadable")
    if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(data.get("jobs"), list) or not data["jobs"]:
        raise ElevationError("job file has an unknown format")
    res = data.get("result")
    if not isinstance(res, str) or os.sep in res or "/" in res or res.startswith("."):
        raise ElevationError("bad result name")
    jobs = []
    for j in data["jobs"]:
        if not isinstance(j, dict):
            raise ElevationError("bad job")
        kind, fname, sha, repo = j.get("kind"), j.get("file"), j.get("sha256"), j.get("repo")
        if kind not in KINDS or not isinstance(fname, str) or not isinstance(sha, str) or not isinstance(repo, str):
            raise ElevationError("bad job")
        if fname != os.path.basename(fname) or fname in ("", ".", "..") or "/" in fname or "\\" in fname:
            raise ElevationError("installer must sit next to the job file")
        if len(sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sha):
            raise ElevationError("bad checksum")
        jobs.append(Job(repo=repo, name=repo, kind=kind, file=str((stage / fname).resolve()), sha256=sha.lower()))
    return jobs, stage / res


def run_jobs(jobs, runner=subprocess.run, timeout=1800):
    """Run installers one after another; a failure never stops the rest. Returns [{'repo','ok','message'}]."""
    out = []
    for j in jobs:
        try:
            if not os.path.isfile(j.file):
                raise ElevationError("installer file is missing")
            if sha256_of(j.file) != j.sha256.lower():
                raise ElevationError("installer changed after it was verified; refused")
            r = runner(installer_command(j.kind, j.file), capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["no message"])[-1]
                raise ElevationError("installer failed (code %s): %s" % (r.returncode, tail[:160]))
            out.append({"repo": j.repo, "ok": True, "message": "Installed."})
        except (ElevationError, OSError, subprocess.SubprocessError) as e:
            out.append({"repo": j.repo, "ok": False, "message": str(e)[:200]})
    return out


def helper_main(argv, runner=subprocess.run):
    """Entry of the elevated helper: `--elevated-run <job file>`. Writes the result file. Returns an exit code."""
    try:
        i = argv.index("--elevated-run")
        jobs, result_path = read_job_file(argv[i + 1])
    except (ValueError, IndexError, ElevationError):
        return 2
    results = run_jobs(jobs, runner)
    tmp = Path(str(result_path) + ".tmp")
    tmp.write_text(json.dumps(results), encoding="utf-8")
    os.replace(tmp, result_path)
    return 0


def _collect(jobs, results):
    by = {r.get("repo"): r for r in (results or []) if isinstance(r, dict)}
    out = {}
    for j in jobs:
        r = by.get(j.repo)
        out[j.repo] = (bool(r and r.get("ok")), (r or {}).get("message") or "The administrator step did not report a result.")
    return out


class Backend:
    """What Installer needs: is the app already administrator, and run a batch with administrator rights."""

    def is_admin(self):
        return False

    def run_batch(self, jobs, stage_dir):
        """-> {repo: (ok, message)}. ONE prompt for the whole list."""
        raise NotImplementedError


class WindowsBackend(Backend):
    """launcher(exe, params) starts the elevated helper and waits; returns True when it ran, False when the user declined."""

    def __init__(self, launcher=None, admin=None, runner=subprocess.run):
        self.launcher, self._admin, self.runner = launcher or windows_runas_and_wait, admin, runner

    def is_admin(self):
        if self._admin is not None:
            return self._admin()
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def run_batch(self, jobs, stage_dir):
        job_path, result_path = write_job_file(jobs, stage_dir)
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, '--elevated-run "%s"' % job_path
        else:
            exe, params = sys.executable, '-m studio87_updater --elevated-run "%s"' % job_path
        try:
            ran = self.launcher(exe, params)
        except OSError as e:
            return {j.repo: (False, "could not start the administrator helper: %s" % e) for j in jobs}
        if not ran:
            return {j.repo: (False, DECLINED) for j in jobs}
        try:
            results = json.loads(Path(result_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            results = []
        for p in (job_path, result_path):
            try:
                Path(p).unlink()
            except OSError:
                pass
        return _collect(jobs, results)


class MacBackend(Backend):
    """One osascript prompt runs a small shell script that installs every staged .pkg and records each result."""

    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def run_batch(self, jobs, stage_dir):
        stage_dir = Path(stage_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)
        script, result = stage_dir / "install-batch.sh", stage_dir / "install-batch.result"
        try:
            result.unlink()
        except OSError:
            pass
        script.write_text(pkg_script(jobs, result), encoding="utf-8")
        try:
            r = self.runner(osascript_command(script), capture_output=True, text=True, timeout=3600)
            ran, tail = r.returncode == 0, ((r.stderr or r.stdout or "").strip().splitlines() or ["no message"])[-1][:160]
        except (OSError, subprocess.SubprocessError) as e:
            ran, tail = False, str(e)[:160]
        lines = []
        try:
            lines = result.read_text(encoding="utf-8").splitlines()
        except OSError:
            pass
        for p in (script, result):
            try:
                p.unlink()
            except OSError:
                pass
        if not ran:
            return {j.repo: (False, "The administrator step failed or was cancelled: %s" % tail) for j in jobs}
        rc = {}
        for ln in lines:
            k, _, v = ln.partition("\t")
            rc[k] = v.strip()
        out = {}
        for i, j in enumerate(jobs):
            v = rc.get(str(i))
            out[j.repo] = (True, "Installed (one administrator prompt for the batch).") if v == "0" else \
                          (False, "installer failed (code %s)" % (v if v is not None else "unknown"))
        return out


def _q(p):
    return "'" + str(p).replace("'", "'\\''") + "'"


def pkg_script(jobs, result_path):
    """Shell script for ONE elevated run: re-check each hash, install, append '<index>\\t<exit code>' to the result file."""
    lines = ["#!/bin/sh"]
    for i, j in enumerate(jobs):
        lines.append('if [ "$(/usr/bin/shasum -a 256 %s | /usr/bin/cut -d" " -f1)" = "%s" ]; then /usr/sbin/installer -pkg %s -target / >/dev/null 2>&1; rc=$?; else rc=99; fi; printf "%d\\t%%s\\n" "$rc" >> %s'
                     % (_q(j.file), j.sha256.lower(), _q(j.file), i, _q(result_path)))
    lines.append("exit 0")
    return "\n".join(lines) + "\n"


def osascript_command(script_path):
    return ["osascript", "-e", 'do shell script "/bin/sh %s" with administrator privileges' % str(script_path).replace("\\", "\\\\").replace('"', '\\"')]


def windows_runas_and_wait(exe, params):
    """ShellExecuteExW 'runas' and wait for the process. False when the user declines the UAC prompt. Windows only."""
    import ctypes
    from ctypes import wintypes

    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    SEE_MASK_NOCLOSEPROCESS = 0x40
    info = SEI()
    info.cbSize = ctypes.sizeof(SEI)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb, info.lpFile, info.lpParameters, info.nShow = "runas", exe, params, 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False          # 1223: the user clicked No on the UAC prompt
    if info.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 3600 * 1000)
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True


def default_backend(system, runner=subprocess.run):
    if system == "windows":
        return WindowsBackend(runner=runner)
    if system == "macos":
        return MacBackend(runner=runner)
    return Backend()

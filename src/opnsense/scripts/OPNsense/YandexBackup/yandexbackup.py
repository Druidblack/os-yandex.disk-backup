#!/usr/local/bin/python3
"""OPNsense Yandex.Disk configuration backup backend (Python 3.13).

The only secret-bearing source is /conf/config.xml. Results/logs never contain tokens,
provider upload URLs or configuration contents.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import sys
import time
from typing import Any
from urllib import error, parse, request
import xml.etree.ElementTree as ET

CONFIG_FILE = Path(os.environ.get("YD_BACKUP_CONFIG", "/conf/config.xml"))
STATE_DIR = Path(os.environ.get("YD_BACKUP_STATE", "/conf/yandexbackup"))
LOCK_FILE = Path(os.environ.get("YD_BACKUP_LOCK", "/var/run/yandexbackup.lock"))
API = "https://cloud-api.yandex.net/v1/disk"
BACKUP_RE = re.compile(r"^OPNsense-([A-Za-z0-9_-]{1,50})-(\d{8}T\d{6}Z)-([0-9a-f]{8})\.xml$")
CTX = ssl.create_default_context()


class BackupError(Exception):
    pass


class ApiHTTPError(BackupError):
    """HTTP status + validated machine code; never show provider text or URLs."""
    def __init__(self, code: int, provider_code: str = ""):
        self.status = code
        # The provider's free-text messages are never used in log output. Only a
        # narrowly validated machine-readable error identifier is passed through.
        self.provider_code = (provider_code if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,63}Error", provider_code)
                              else "")
        suffix = f" ({self.provider_code})" if self.provider_code else ""
        super().__init__(f"Yandex.Disk API returned HTTP {code}{suffix}")


def read_config() -> dict[str, Any]:
    if not CONFIG_FILE.is_file():
        raise BackupError("OPNsense configuration file not found")
    root = ET.parse(CONFIG_FILE).getroot()
    node = root.find("./OPNsense/yandexbackup/general")
    if node is None:
        node = ET.Element("general")
    def field(name: str, default: str = "") -> str:
        el = node.find(name)
        return (el.text or "").strip() if el is not None else default
    folder = field("remote_folder", "OPNsense-Backups").strip("/")
    segments = folder.split("/")
    if not (1 <= len(folder) <= 160 and len(segments) <= 8):
        raise BackupError("Invalid Yandex.Disk folder")
    if any(s in ("", ".", "..") or ":" in s or "\\" in s or any(ord(c) < 32 for c in s)
           for s in segments):
        raise BackupError("Invalid Yandex.Disk folder segments")
    try:
        count = int(field("retention", "30"))
    except ValueError as exc:
        raise BackupError("Retention must be an integer") from exc
    if not 1 <= count <= 365:
        raise BackupError("Retention must be between 1 and 365")
    sysnode = root.find("./system")
    host = (sysnode.findtext("hostname") if sysnode is not None else "") or socket.gethostname()
    host = re.sub(r"[^A-Za-z0-9_-]", "-", host).strip("-")[:50] or "firewall"
    return {
        "enabled": field("enabled", "0") == "1",
        "token": field("oauth_token"),
        "folder": folder,
        "retention": count,
        "hostname": host,
    }


def emit(status: bool, message: str, **kwargs: Any) -> None:
    print(json.dumps({"ok": status, "message": message, **kwargs}, ensure_ascii=False), flush=True)


def log_event(action: str, ok: bool, message: str, file: str = "") -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    record = {"time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "action": action, "ok": ok, "message": message[:280], "file": file}
    path = STATE_DIR / "history.jsonl"
    # Root-only, append atomic small JSON line, truncate history to 200 entries.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    if path.stat().st_size > 180_000:
        lines = path.read_text(encoding="utf-8").splitlines()[-200:]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)


def history() -> list[dict[str, Any]]:
    path = STATE_DIR / "history.jsonl"
    if not path.is_file():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines()[-30:][::-1]:
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                result.append(record)
        except ValueError:
            continue
    return result


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req: request.Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        return None


OPENER = request.build_opener(request.HTTPSHandler(context=CTX), NoRedirect)


def api_call(token: str, method: str, endpoint: str, params: dict[str, Any] | None = None) -> Any:
    url = API + endpoint
    if params:
        url += "?" + parse.urlencode(params)
    req = request.Request(url, method=method, headers={
        "Authorization": "OAuth " + token,
        "Accept": "application/json",
        "User-Agent": "OPNsense-YandexBackup/0.1.6",
    })
    try:
        with OPENER.open(req, timeout=25) as resp:
            content = resp.read(1_000_000)
            return json.loads(content) if content else {}
    except error.HTTPError as exc:
        # Read only a bounded body and extract the structured error identifier.
        # Never echo full provider error text, request URLs or OAuth credentials.
        provider_code = ""
        try:
            body = json.loads(exc.read(4096))
            if isinstance(body, dict) and isinstance(body.get("error"), str):
                provider_code = body["error"]
        except (UnicodeDecodeError, ValueError, OSError):
            pass
        finally:
            exc.close()
        raise ApiHTTPError(exc.code, provider_code) from None
    except (error.URLError, TimeoutError, ssl.SSLError):
        raise BackupError("Yandex.Disk API network or TLS error") from None


def check_disk_access(token: str) -> None:
    """Verify that the OAuth token can read the regular Yandex.Disk root.

    The plugin exclusively operates on disk:/ and never probes or writes to
    an application's private folder. This check is read-only.
    """
    try:
        data = api_call(token, "GET", "/resources", {"path": "disk:/", "limit": 1})
    except ApiHTTPError as exc:
        if exc.status == 401:
            raise BackupError("OAuth token rejected (HTTP 401): obtain a new Yandex.Disk token") from None
        if exc.status == 403:
            raise BackupError("Yandex.Disk disk:/ access denied: " + str(exc) +
                              ". Check OAuth permissions cloud_api:disk.read and "
                              "cloud_api:disk.write, or run 'configctl yandexbackup diagnose'.") from None
        raise
    if not isinstance(data, dict) or data.get("type") != "dir":
        raise BackupError("Yandex.Disk returned an unexpected disk:/ root response")


def disk_path(folder: str, filename: str = "") -> str:
    return "disk:/" + folder + ("/" + filename if filename else "")


def ensure_folder(token: str, folder: str) -> None:
    prefix = ""
    for segment in folder.split("/"):
        prefix = prefix + ("/" if prefix else "") + segment
        try:
            api_call(token, "PUT", "/resources", {"path": disk_path(prefix)})
        except ApiHTTPError as exc:
            # 409 is how the Yandex.Disk API reports an existing folder.
            if exc.status == 403:
                raise BackupError("HTTP 403 creating disk:/ backup folder: "
                                  "OAuth token lacks write permission for this location") from None
            if exc.status != 409:
                raise



def upload(token: str, path: str, blob: bytes) -> None:
    try:
        response = api_call(token, "GET", "/resources/upload", {"path": path, "overwrite": "false"})
    except ApiHTTPError as exc:
        if exc.status == 403:
            raise BackupError("HTTP 403 obtaining upload link: "
                              "OAuth token lacks write permission for backup destination") from None
        raise
    href = response.get("href") if isinstance(response, dict) else None
    if not isinstance(href, str):
        raise BackupError("Upload URL missing from Yandex.Disk API response")
    parsed = parse.urlsplit(href)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host == d or host.endswith("." + d)
        for d in ("yandex.net", "yandex.ru", "yandex.com")) or parsed.username or parsed.password:
        raise BackupError("Unexpected Yandex.Disk upload destination")
    # No bearer token is sent to the signed upload endpoint.
    req = request.Request(href, data=blob, method="PUT", headers={
        "Content-Type": "application/octet-stream", "User-Agent": "OPNsense-YandexBackup/0.1.6"})
    try:
        with OPENER.open(req, timeout=120) as resp:
            if resp.status not in (200, 201, 202, 204):
                raise BackupError(f"Upload rejected (HTTP {resp.status})")
    except error.HTTPError as exc:
        raise BackupError(f"Yandex.Disk signed upload endpoint rejected data (HTTP {exc.code})") from None
    except (error.URLError, TimeoutError, ssl.SSLError):
        raise BackupError("Yandex.Disk upload network or TLS error") from None


def verify_upload(token: str, path: str, blob: bytes) -> None:
    expected_md5 = hashlib.md5(blob, usedforsecurity=False).hexdigest()
    for attempt in range(10):
        try:
            meta = api_call(token, "GET", "/resources", {"path": path, "fields": "type,size,md5"})
        except ApiHTTPError as exc:
            if exc.status != 404:
                raise
            meta = {}
        if isinstance(meta, dict) and meta.get("type") == "file":
            if meta.get("size") != len(blob):
                raise BackupError("Remote file size mismatch")
            if meta.get("md5") and meta["md5"].lower() != expected_md5:
                raise BackupError("Remote file MD5 mismatch")
            return
        if attempt < 9:
            time.sleep(2)
    raise BackupError("Upload not yet confirmed by Yandex.Disk (no retention performed)")


def list_files(token: str, folder: str) -> list[dict[str, Any]]:
    result = []
    offset, limit = 0, 100
    while True:
        data = api_call(token, "GET", "/resources", {
            "path": disk_path(folder), "limit": limit, "offset": offset,
            "fields": "_embedded.items.name,_embedded.items.type,_embedded.items.size,_embedded.items.created,_embedded.total"})
        emb = data.get("_embedded", {})
        items = emb.get("items", [])
        if not isinstance(items, list):
            raise BackupError("Invalid directory listing")
        result.extend({"name": item.get("name", ""), "size": item.get("size", 0),
                       "created": item.get("created", "")}
                      for item in items if isinstance(item, dict) and item.get("type") == "file")
        offset += len(items)
        total = emb.get("total")
        if len(items) == 0 or (total is not None and offset >= int(total)) or (total is None and len(items) < limit):
            break
        if offset > 10000:
            raise BackupError("Too many files in remote folder; refusing retention")
    return result


def only_our_files(files: list[dict[str, Any]], hostname: str) -> list[dict[str, Any]]:
    matched = []
    for item in files:
        m = BACKUP_RE.fullmatch(item["name"])
        if m and m.group(1) == hostname:
            matched.append(item)
    return sorted(matched, key=lambda d: d["name"], reverse=True)


def do_diagnose(cfg: dict[str, Any]) -> dict[str, Any]:
    """Read-only, secrets-free API diagnosis for permissions and token failures.

    No configuration contents, OAuth token, account name or disk contents are logged.
    """
    if not cfg["token"]:
        raise BackupError("OAuth token is empty")
    probes = {"disk_info": ("/", None),
              "disk_root": ("/resources", {"path": "disk:/", "limit": 1})}
    result = {}
    for name, (endpoint, params) in probes.items():
        try:
            info = api_call(cfg["token"], "GET", endpoint, params)
            if name == "disk_info":
                result[name] = "OK" if isinstance(info, dict) else "unexpected response"
            else:
                result[name] = "OK" if isinstance(info, dict) and info.get("type") == "dir" else "unexpected response"
        except ApiHTTPError as exc:
            result[name] = f"HTTP {exc.status}" + (f" ({exc.provider_code})" if exc.provider_code else "")
        except BackupError as exc:
            result[name] = str(exc)
    return result


def do_test(cfg: dict[str, Any]) -> dict[str, Any]:
    if not cfg["token"]:
        raise BackupError("OAuth token is empty")
    check_disk_access(cfg["token"])
    return {"folder": cfg["folder"], "storage_root": "disk:/"}


def do_backup(cfg: dict[str, Any]) -> dict[str, Any]:
    if not cfg["enabled"]:
        raise BackupError("Enable backups and save settings first")
    if not cfg["token"]:
        raise BackupError("OAuth token is empty")
    try:
        xml = CONFIG_FILE.read_bytes()
        ET.fromstring(xml)
    except (OSError, ET.ParseError) as exc:
        raise BackupError("Cannot read valid OPNsense configuration") from exc
    name = (f"OPNsense-{cfg['hostname']}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
            f"{secrets.token_hex(4)}.xml")
    blob = xml
    with LOCK_FILE.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError("Another backup is running") from None
        check_disk_access(cfg["token"])
        ensure_folder(cfg["token"], cfg["folder"])
        path = disk_path(cfg["folder"], name)
        upload(cfg["token"], path, blob)
        verify_upload(cfg["token"], path, blob)
        retention_warning = ""
        try:
            files = only_our_files(list_files(cfg["token"], cfg["folder"]), cfg["hostname"])
            for old in files[cfg["retention"]:]:
                api_call(cfg["token"], "DELETE", "/resources", {
                    "path": disk_path(cfg["folder"], old["name"]), "permanently": "false"})
        except BackupError:
            retention_warning = "; old-backup cleanup failed (review logs)"
        return {"file": name, "size": len(blob), "storage_root": "disk:/",
                "message": "Backup uploaded and verified" + retention_warning}


def do_list(cfg: dict[str, Any]) -> dict[str, Any]:
    if not cfg["token"]:
        raise BackupError("OAuth token is empty")
    check_disk_access(cfg["token"])
    try:
        files = only_our_files(list_files(cfg["token"], cfg["folder"]), cfg["hostname"])
    except ApiHTTPError as exc:
        if exc.status != 404:
            raise
        files = []
    return {"files": files[:100], "total": len(files), "storage_root": "disk:/"}



def main() -> int:
    parser = argparse.ArgumentParser(description="OPNsense Yandex.Disk backup")
    parser.add_argument("command", choices=["test", "backup", "list", "status", "diagnose"])
    args = parser.parse_args()
    try:
        if args.command == "status":
            cfg = read_config()
            emit(True, "Local status", enabled=cfg["enabled"],
                 token_configured=bool(cfg["token"]),
                 folder=cfg["folder"], retention=cfg["retention"], history=history())
            return 0
        cfg = read_config()
        if args.command == "diagnose":
            emit(True, "Read-only Yandex.Disk API diagnostics (no files modified)", **do_diagnose(cfg))
        elif args.command == "test":
            result = do_test(cfg)
            log_event("test", True, "Connection verified using " + result["storage_root"])
            emit(True, "Connection verified", **result)
        elif args.command == "backup":
            result = do_backup(cfg)
            log_event("backup", True, result["message"] + " using " + result["storage_root"], result["file"])
            emit(True, result["message"], file=result["file"], size=result["size"],
                 storage_root=result["storage_root"])
        elif args.command == "list":
            result = do_list(cfg)
            emit(True, "Remote backups listed", **result)
        return 0
    except (BackupError, OSError, ValueError) as exc:
        # Never emit exception objects from HTTP clients or dump secrets.
        msg = str(exc) if isinstance(exc, BackupError) else "Local filesystem or configuration error"
        if args.command in ("test", "backup"):
            try:
                log_event(args.command, False, msg)
            except OSError:
                pass
        emit(False, msg)
        return 1


if __name__ == "__main__":
    sys.exit(main())

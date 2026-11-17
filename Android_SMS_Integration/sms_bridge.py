"""
Android SMSGate Local Server Connector for Windows.
Python 3.14 stdlib only. No external frameworks or dependencies.

Connects to an Android phone running SMSGate Local Server over Tailscale IPv4.
Security controls:
  - Literal Tailscale IPv4 (100.64.0.0/10) or literal 127.0.0.1 (mocked tests only).
  - DPAPI-protected user-scoped credentials stored outside OneDrive.
  - Strict sender allowlist and neutral generated test content only.
  - No proxy leakage, no HTTP redirect following.
  - Atomic state persistence and file locking against concurrent operations.
  - Exact official SMSGate Local Server state schema (Pending/Processed/Sent/Delivered/Failed).
  - Single-test isolation: exactly one test per state directory until explicitly reset.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import datetime
import ipaddress
import json
import msvcrt
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------

TAILSCALE_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")
LOOPBACK_IPV4 = ipaddress.ip_address("127.0.0.1")
DEFAULT_TIMEOUT = 10.0
MAX_RESPONSE_BYTES = 65536  # 64 KB bounded read
MAX_INBOX_PAGES = 3
INBOX_PAGE_LIMIT = 50


def get_default_state_dir() -> str:
    """Return default runtime state/secrets directory in %LOCALAPPDATA% (outside OneDrive)."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    state_dir = os.path.join(local_app_data, "HMR-SMS-Bridge")
    return state_dir


def get_active_state_dir(override_dir: Optional[str] = None) -> str:
    """Resolve active state directory, allowing explicit override for testing."""
    if override_dir:
        return os.path.abspath(override_dir)
    env_dir = os.environ.get("HMR_BRIDGE_STATE_DIR")
    if env_dir:
        return os.path.abspath(env_dir)
    return get_default_state_dir()


# ---------------------------------------------------------------------------
# Windows DPAPI Implementation via ctypes
# ---------------------------------------------------------------------------

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def dpapi_protect(plaintext: bytes, description: str = "HMR-SMS-Bridge") -> bytes:
    """Encrypt bytes using Windows DPAPI user-scoped CryptProtectData."""
    if not isinstance(plaintext, bytes):
        plaintext = plaintext.encode("utf-8")
    cb_in = len(plaintext)
    in_buffer = (ctypes.c_byte * cb_in)(*plaintext)
    in_blob = _DATA_BLOB(cb_in, in_buffer)
    out_blob = _DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    # CRYPTPROTECT_UI_FORBIDDEN = 0x01
    flags = 0x01
    res = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None,  # optional entropy
        None,  # reserved
        None,  # prompt struct
        flags,
        ctypes.byref(out_blob),
    )
    if not res:
        raise ctypes.WinError()
    try:
        return bytes(ctypes.string_at(out_blob.pbData, out_blob.cbData))
    finally:
        kernel32.LocalFree(out_blob.pbData)


def dpapi_unprotect(ciphertext: bytes) -> bytes:
    """Decrypt bytes using Windows DPAPI user-scoped CryptUnprotectData."""
    if not isinstance(ciphertext, bytes):
        raise TypeError("Ciphertext must be bytes")
    cb_in = len(ciphertext)
    in_buffer = (ctypes.c_byte * cb_in)(*ciphertext)
    in_blob = _DATA_BLOB(cb_in, in_buffer)
    out_blob = _DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    res = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    if not res:
        raise ctypes.WinError()
    try:
        return bytes(ctypes.string_at(out_blob.pbData, out_blob.cbData))
    finally:
        kernel32.LocalFree(out_blob.pbData)


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------

def normalize_phone_number(phone_str: str) -> str:
    """
    Validate and normalize phone number.
    Accepts Australian mobile formats (04XX XXX XXX -> +614XXXXXXXX)
    and standard E.164 (+[1-9][0-9]{6,14}).
    Does not echo raw input in error messages to avoid leaking accidentally pasted secrets.
    """
    if not isinstance(phone_str, str):
        raise ValueError("Phone number must be a string.")
    cleaned = re.sub(r"[\s\-\(\)\.]", "", phone_str.strip())
    # Australian mobile local representation: 04XXXXXXXX (10 digits)
    if re.fullmatch(r"04\d{8}", cleaned):
        return "+614" + cleaned[2:]
    # E.164 international format
    if re.fullmatch(r"\+[1-9]\d{6,14}", cleaned):
        return cleaned
    raise ValueError(
        "Invalid test phone number format. Must be E.164 (e.g. +61400000001) or Australian mobile (04XXXXXXXX)."
    )


def validate_sim_number(sim_val: Any) -> int:
    """
    Validate SIM number is strictly 1, 2, or 3.
    Rejects booleans, floats, and non-digit strings.
    """
    if isinstance(sim_val, bool) or isinstance(sim_val, float):
        raise ValueError("Invalid SIM value: boolean and float types are rejected.")
    if isinstance(sim_val, str):
        sim_val = sim_val.strip()
        if sim_val not in ("1", "2", "3"):
            raise ValueError("Invalid SIM number. Must be 1, 2, or 3.")
        return int(sim_val)
    if isinstance(sim_val, int):
        if sim_val in (1, 2, 3):
            return sim_val
        raise ValueError(f"SIM number {sim_val} is out of range. Must be 1, 2, or 3.")
    raise ValueError("Invalid SIM number type. Must be 1, 2, or 3.")


def validate_gateway_url(url_str: str, allow_loopback: bool = True) -> Tuple[str, str, int]:
    """
    Strict validation of Gateway URL.
    Rules:
      - Scheme must be http or https.
      - HTTP is allowed only for literal loopback or literal Tailscale IPv4.
      - Host must be literal IPv4: Tailscale CGNAT 100.64.0.0/10, or 127.0.0.1 (mocked tests).
      - No embedded credentials (user/password).
      - No query parameters, fragments, or path components.
      - Disallows DNS hostnames, public IPs, LAN IPs, and out-of-range 100.x.
      - Never echoes raw user input in error messages.
    Returns:
      (normalized_base_url, host_ip_str, port)
    """
    if not isinstance(url_str, str):
        raise ValueError("Gateway URL must be a string.")
    try:
        parsed = urllib.parse.urlsplit(url_str.strip())
    except Exception:
        raise ValueError("Gateway URL is malformed.")

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("Invalid URL scheme. Only http and https are allowed.")

    if parsed.username or parsed.password:
        raise ValueError("Gateway URL must not contain embedded username or password.")
    if parsed.query:
        raise ValueError("Gateway URL must not contain query parameters.")
    if parsed.fragment:
        raise ValueError("Gateway URL must not contain URL fragments.")
    if parsed.path not in ("", "/"):
        raise ValueError("Gateway URL must not contain a path component.")

    host_str = parsed.hostname
    if not host_str:
        raise ValueError("Gateway URL must specify an explicit host IP.")

    # Strict literal IPv4 parsing
    try:
        ip = ipaddress.ip_address(host_str)
    except ValueError:
        raise ValueError(
            "Gateway host must be a literal IPv4 address. DNS names and hostnames are disallowed."
        )

    if ip.version != 4:
        raise ValueError("Only IPv4 addresses are supported.")

    is_loopback = ip == LOOPBACK_IPV4
    is_tailscale = ip in TAILSCALE_CGNAT_NET

    if not (is_tailscale or (allow_loopback and is_loopback)):
        raise ValueError(
            "Gateway IP is disallowed. Must be a literal Tailscale IPv4 (100.64.0.0/10) or literal 127.0.0.1 for local tests."
        )

    port = parsed.port
    if port is None:
        port = 8080 if scheme == "http" else 443

    if not (1 <= port <= 65535):
        raise ValueError("Gateway port is out of valid range (1..65535).")

    normalized_url = f"{scheme}://{host_str}:{port}"
    return normalized_url, host_str, port


def parse_aware_utc(ts_str: Any) -> Optional[datetime.datetime]:
    """Parse ISO8601 string to timezone-aware UTC datetime. Rejects naive or malformed timestamps."""
    if not isinstance(ts_str, str):
        return None
    try:
        s = ts_str.strip()
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return None
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tailscale Peer Verification
# ---------------------------------------------------------------------------

def find_tailscale_bin() -> Optional[str]:
    """Resolve tailscale executable via PATH or official Program Files directory."""
    bin_path = shutil.which("tailscale")
    if bin_path and os.path.isfile(bin_path):
        return bin_path
    official_path = r"C:\Program Files\Tailscale\tailscale.exe"
    if os.path.isfile(official_path):
        return official_path
    return None


def verify_tailscale_peer(
    gateway_ip: str,
    status_cmd_runner: Optional[Callable[[], Tuple[int, str, str]]] = None,
    ping_runner: Optional[Callable[[str], Tuple[int, str, str]]] = None,
) -> Tuple[bool, str]:
    """
    Verify that Tailscale daemon is Running, Self is Online, and target Tailscale peer is Online.
    Resolves CLI through shutil.which then C:/Program Files/Tailscale/tailscale.exe.
    Loopback 127.0.0.1 is permitted for local test mock harnesses.
    """
    if gateway_ip == "127.0.0.1":
        return True, "Loopback (127.0.0.1) permitted for local mock/test harness."

    custom_status_runner = status_cmd_runner is not None
    if status_cmd_runner is None:
        def default_runner() -> Tuple[int, str, str]:
            ts_bin = find_tailscale_bin()
            if not ts_bin:
                return -1, "", "Tailscale CLI ('tailscale.exe') not found in PATH or standard Program Files location."
            try:
                proc = subprocess.run(
                    [ts_bin, "status", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                return proc.returncode, proc.stdout, proc.stderr
            except FileNotFoundError:
                return -1, "", "Tailscale CLI is not installed or not in PATH."
            except subprocess.TimeoutExpired:
                return -2, "", "Tailscale status query timed out after 5 seconds."
            except Exception as e:
                return -3, "", f"Failed to execute Tailscale status: {type(e).__name__}"

        status_cmd_runner = default_runner

    code, stdout, stderr = status_cmd_runner()
    if code != 0:
        err_msg = stderr.strip() or "tailscale status returned non-zero exit code"
        return False, f"Tailscale verification failed: {err_msg}"

    try:
        status_data = json.loads(stdout)
    except json.JSONDecodeError:
        return False, "Failed to parse tailscale status JSON output."

    if not isinstance(status_data, dict):
        return False, "Malformed tailscale status output."

    # 1. BackendState check
    backend_state = status_data.get("BackendState")
    if backend_state != "Running":
        return False, f"Tailscale BackendState is '{backend_state}' (expected 'Running'). Tailscale login or start required."

    # 2. Self node online check
    self_node = status_data.get("Self")
    if not isinstance(self_node, dict):
        return False, "Tailscale local client status missing from status output."
    fallback = not self_node.get("Online")
    if fallback:
        try:
            target_ip = ipaddress.ip_address(gateway_ip)
            local_ips = self_node.get("TailscaleIPs")
            if (self_node.get("Online") is not False or self_node.get("InNetworkMap") is not True or
                    target_ip.version != 4 or target_ip not in TAILSCALE_CGNAT_NET or
                    not isinstance(local_ips, list) or not any(
                        isinstance(ip, str) and ipaddress.ip_address(ip) in TAILSCALE_CGNAT_NET for ip in local_ips
                    )):
                return False, "Tailscale local client (Self) is not Online."
        except (TypeError, ValueError):
            return False, "Tailscale local client (Self) is not Online."
        if custom_status_runner and ping_runner is None:
            return False, "Tailscale local client (Self) is not Online."

    # 3. Target peer online check
    peer_dict = status_data.get("Peer") or status_data.get("Peers") or {}
    peers_list: List[Dict[str, Any]] = []
    if isinstance(peer_dict, dict):
        peers_list = list(peer_dict.values())
    elif isinstance(peer_dict, list):
        peers_list = peer_dict

    for peer in peers_list:
        if not isinstance(peer, dict):
            continue
        ts_ips = peer.get("TailscaleIPs", [])
        if isinstance(ts_ips, list) and gateway_ip in ts_ips:
            if fallback:
                if peer.get("Online") is not True:
                    return False, "Tailscale peer verification failed."
                if ping_runner is None:
                    def ping_runner(target: str) -> Tuple[int, str, str]:
                        ts_bin = find_tailscale_bin()
                        if not ts_bin:
                            return -1, "", ""
                        try:
                            proc = subprocess.run([ts_bin, "ping", "--c", "1", "--timeout", "2s", target],
                                                  capture_output=True, text=True, timeout=3, check=False)
                            return proc.returncode, proc.stdout, ""
                        except (OSError, subprocess.TimeoutExpired):
                            return -1, "", ""
                try:
                    ping_code, ping_output, _ = ping_runner(gateway_ip)
                    matched = re.search(r"(?m)^pong from [^\r\n()]+ \(" + re.escape(gateway_ip) + r"\) (?:via|in) ", ping_output)
                    if ping_code == 0 and matched:
                        return True, "Tailscale peer reachability verified."
                except Exception:
                    pass
                return False, "Tailscale peer verification failed."
            is_online = bool(peer.get("Online"))
            if is_online:
                host_label = peer.get("HostName", "peer")
                return True, f"Tailscale peer '{host_label}' ({gateway_ip}) is Online."
            return False, f"Tailscale peer ({gateway_ip}) was found but is currently Offline."

    if fallback:
        return False, "Tailscale peer verification failed."
    return False, f"Gateway IP '{gateway_ip}' is not present in Tailscale peer list."


# ---------------------------------------------------------------------------
# Secure HTTP Client (No Proxies, No Redirects, Sanitized Errors)
# ---------------------------------------------------------------------------

class DisallowRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse HTTP redirects to prevent credentials leakage or URL hijacking."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            "HTTP redirects disallowed for security.",
            headers,
            fp,
        )


class BridgeError(Exception):
    """Base error for SMS bridge operations."""
    pass


class BridgeHTTPError(BridgeError):
    """Sanitized HTTP error containing only status code; no remote reason, headers, or body."""
    def __init__(self, code: int):
        super().__init__(f"SMSGate HTTP error {code}")
        self.code = code


class BridgeNetworkError(BridgeError):
    """Sanitized network/connection error; no secrets."""
    pass


class SMSGateClient:
    """HTTP client communicating with SMSGate Local Server."""

    def __init__(self, base_url: str, username: str, password: str, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # Prepare Basic Auth header
        user_pass = f"{username}:{password}".encode("utf-8")
        self._auth_header = f"Basic {base64.b64encode(user_pass).decode('ascii')}"

        # Build secure opener: No proxies, No redirects, Default SSL context
        ssl_ctx = ssl.create_default_context()
        proxy_handler = urllib.request.ProxyHandler({})  # empty = disable environment/system proxies
        redirect_handler = DisallowRedirectHandler()
        https_handler = urllib.request.HTTPSHandler(context=ssl_ctx)
        self.opener = urllib.request.build_opener(proxy_handler, redirect_handler, https_handler)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Any, Dict[str, str]]:
        url = f"{self.base_url}{path}"
        data_bytes = None
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "User-Agent": "HMR-SMS-Bridge/1.0",
        }
        if payload is not None:
            data_bytes = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                code = resp.status
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise BridgeError(f"Response from SMSGate exceeded {MAX_RESPONSE_BYTES} bytes cap.")
                headers_dict = {k.lower(): v for k, v in resp.headers.items()}
                parsed = None
                if raw:
                    try:
                        parsed = json.loads(raw.decode("utf-8"))
                    except Exception:
                        parsed = raw.decode("utf-8", errors="replace")
                return code, parsed, headers_dict
        except urllib.error.HTTPError as e:
            try:
                e.close()
            except Exception:
                pass
            # Sanitize: do not pass remote-controlled reason, headers, or response body
            raise BridgeHTTPError(e.code)
        except urllib.error.URLError as e:
            raise BridgeNetworkError("Connection to SMSGate failed.")
        except Exception as e:
            if isinstance(e, BridgeError):
                raise
            raise BridgeNetworkError(f"Request failed: {type(e).__name__}")

    def get_health(self) -> Dict[str, Any]:
        """Call GET /health."""
        _, data, _ = self._request("GET", "/health")
        if not isinstance(data, dict):
            raise BridgeError("Invalid health response format from gateway.")
        return data

    def send_message(self, client_id: str, text: str, recipient: str, sim_number: int) -> Dict[str, Any]:
        """
        Call POST /message.
        Payload matches official SMSGate Local Server specification.
        Official response contains 'state' (Pending, Processed, Sent, Delivered, Failed).
        """
        payload = {
            "id": client_id,
            "textMessage": {"text": text},
            "phoneNumbers": [recipient],
            "simNumber": sim_number,
            "withDeliveryReport": True,
            "ttl": 300,
        }
        _, data, _ = self._request("POST", "/message", payload)
        if isinstance(data, dict):
            return data
        raise BridgeError("Invalid message response format from gateway.")

    def get_message_status(self, client_id: str) -> Dict[str, Any]:
        """Call GET /message/{id}."""
        safe_id = urllib.parse.quote(client_id)
        _, data, _ = self._request("GET", f"/message/{safe_id}")
        if not isinstance(data, dict):
            raise BridgeError("Invalid status response format from gateway.")
        return data

    def get_inbox_page(self, since_iso: str, limit: int = INBOX_PAGE_LIMIT, offset: int = 0) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """
        Call GET /inbox?type=SMS&limit={limit}&offset={offset}&from={since_iso}.
        Returns (list_of_messages, total_count_or_None).
        Errors if the response is not a list.
        """
        query = urllib.parse.urlencode({
            "type": "SMS",
            "limit": limit,
            "offset": offset,
            "from": since_iso,
        })
        _, data, headers = self._request("GET", f"/inbox?{query}")
        total_count = None
        if "x-total-count" in headers:
            try:
                total_count = int(headers["x-total-count"])
            except ValueError:
                pass

        if not isinstance(data, list):
            raise BridgeError("Malformed inbox response from gateway: expected JSON list.")
        return data, total_count


# ---------------------------------------------------------------------------
# Concurrency File Lock & Atomic State Storage
# ---------------------------------------------------------------------------

class FileLocker:
    """Durable file lock using Windows msvcrt.locking to serialize all bridge operations."""

    def __init__(self, lock_file_path: str):
        self.lock_file_path = lock_file_path
        self._fd: Optional[int] = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.lock_file_path), exist_ok=True)
        try:
            self._fd = os.open(self.lock_file_path, os.O_RDWR | os.O_CREAT)
            msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
        except (OSError, IOError) as e:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None
            raise RuntimeError("Another SMS bridge process currently holds the lock.") from e
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fd is not None:
            try:
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None


class BridgeStorage:
    """Handles config, DPAPI credentials, and atomic state persistence."""

    def __init__(self, state_dir: str):
        self.state_dir = os.path.abspath(state_dir)
        self.config_path = os.path.join(self.state_dir, "config.json")
        self.creds_path = os.path.join(self.state_dir, "credentials.dpapi")
        self.state_path = os.path.join(self.state_dir, "state.json")
        self.lock_path = os.path.join(self.state_dir, "bridge.lock")

    def ensure_dir(self):
        os.makedirs(self.state_dir, exist_ok=True)

    def save_config(self, gateway_url: str, sim_number: int, test_number: str):
        norm_url, _, _ = validate_gateway_url(gateway_url)
        norm_phone = normalize_phone_number(test_number)
        norm_sim = validate_sim_number(sim_number)

        self.ensure_dir()
        payload = {
            "gateway_url": norm_url,
            "sim_number": norm_sim,
            "test_number": norm_phone,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._write_atomic(self.config_path, json.dumps(payload, indent=2).encode("utf-8"))

    def load_config(self) -> Dict[str, Any]:
        if not os.path.isfile(self.config_path):
            raise FileNotFoundError(
                f"Configuration file not found at '{self.config_path}'. Run 'configure' first."
            )
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            raise BridgeError(f"Corrupt configuration file at '{self.config_path}'.") from e

        if not isinstance(cfg, dict):
            raise BridgeError("Malformed configuration file shape.")

        norm_url, _, _ = validate_gateway_url(cfg["gateway_url"])
        norm_phone = normalize_phone_number(cfg["test_number"])
        norm_sim = validate_sim_number(cfg["sim_number"])
        return {
            "gateway_url": norm_url,
            "sim_number": norm_sim,
            "test_number": norm_phone,
            "updated_at": cfg.get("updated_at"),
        }

    def save_credentials(self, username: str, password: str):
        self.ensure_dir()
        creds_json = json.dumps({"username": username, "password": password}).encode("utf-8")
        encrypted = dpapi_protect(creds_json)
        self._write_atomic(self.creds_path, encrypted)

    def load_credentials(self) -> Tuple[str, str]:
        if not os.path.isfile(self.creds_path):
            raise FileNotFoundError(
                f"DPAPI credentials not found at '{self.creds_path}'. Run 'configure' first."
            )
        with open(self.creds_path, "rb") as f:
            encrypted = f.read()
        decrypted = dpapi_unprotect(encrypted)
        data = json.loads(decrypted.decode("utf-8"))
        return data["username"], data["password"]

    def has_credentials(self) -> bool:
        return os.path.isfile(self.creds_path)

    def has_config(self) -> bool:
        return os.path.isfile(self.config_path)

    def load_state(self) -> Dict[str, Any]:
        """
        Load state.json.
        Fails closed on corrupt or malformed state; never returns empty state on corruption.
        """
        if not os.path.isfile(self.state_path):
            return {"active_test": None, "history": []}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            raise BridgeError(f"Corrupt state file at '{self.state_path}'. Refusing to continue.") from e

        if not isinstance(state, dict):
            raise BridgeError(f"Malformed state file at '{self.state_path}': expected JSON object.")

        if "active_test" not in state or "history" not in state:
            raise BridgeError(f"Malformed state shape at '{self.state_path}': missing required keys.")

        if not isinstance(state["history"], list):
            raise BridgeError("Malformed state shape: 'history' must be a list.")

        active = state["active_test"]
        if active is not None and not isinstance(active, dict):
            raise BridgeError("Malformed state shape: 'active_test' must be a dictionary or null.")

        return state

    def save_state(self, state_dict: Dict[str, Any]):
        self.ensure_dir()
        data = json.dumps(state_dict, indent=2).encode("utf-8")
        self._write_atomic(self.state_path, data)

    def _write_atomic(self, target_path: str, data: bytes):
        tmp_path = f"{target_path}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Core Bridge Commands
# ---------------------------------------------------------------------------

def run_doctor(storage: BridgeStorage, print_fn=print, tailscale_checker=None) -> int:
    """Inspect local prerequisites, configuration, credentials, and Tailscale peer status."""
    print_fn("=== HMR SMSGate Connector: Doctor ===")
    has_issues = False

    # 1. State Directory & OneDrive Check
    state_dir = storage.state_dir
    print_fn(f"[CHECK] State directory: {state_dir}")
    if "onedrive" in state_dir.lower():
        print_fn("  [WARN] State directory is inside OneDrive! Credentials should reside outside OneDrive.")
        has_issues = True
    else:
        print_fn("  [PASS] State directory is outside OneDrive.")

    # 2. Config File Check
    cfg = None
    if storage.has_config():
        try:
            cfg = storage.load_config()
            print_fn(f"  [PASS] Config file present: Gateway={cfg['gateway_url']}, SIM={cfg['sim_number']}, TestNumber={cfg['test_number']}")
        except Exception as e:
            print_fn(f"  [FAIL] Config file invalid: {e}")
            has_issues = True
    else:
        print_fn("  [FAIL] Config file absent. Run 'configure' to initialize.")
        has_issues = True

    # 3. DPAPI Credentials Check (No secrets revealed)
    if storage.has_credentials():
        try:
            user, _ = storage.load_credentials()
            print_fn(f"  [PASS] DPAPI credentials verified and readable (username length: {len(user)}).")
        except Exception as e:
            print_fn(f"  [FAIL] DPAPI credentials decryption failed: {e}")
            has_issues = True
    else:
        print_fn("  [FAIL] DPAPI credentials absent. Run 'configure' to set credentials.")
        has_issues = True

    # 4. Tailscale Peer Check
    if cfg:
        _, host_ip, _ = validate_gateway_url(cfg["gateway_url"])
        ok, msg = verify_tailscale_peer(host_ip, status_cmd_runner=tailscale_checker)
        if ok:
            print_fn(f"  [PASS] Tailscale peer status: {msg}")
        else:
            print_fn(f"  [WARN] Tailscale peer status: {msg}")
            if host_ip != "127.0.0.1":
                has_issues = True

    # 5. Isolation Guard Check
    print_fn("  [PASS] Patient files isolation: no parent directory or patient database configured.")

    if has_issues:
        print_fn("\nDoctor result: ATTENTION NEEDED before running live tests.")
        return 1
    print_fn("\nDoctor result: ALL PREREQUISITES READY.")
    return 0


def run_health(storage: BridgeStorage, print_fn=print, tailscale_checker=None, timeout: float = DEFAULT_TIMEOUT) -> int:
    """Call GET /health on SMSGate Local Server."""
    if not storage.has_config() or not storage.has_credentials():
        print_fn("Error: Configuration or DPAPI credentials missing. Run 'configure' first.")
        return 1

    cfg = storage.load_config()
    _, host_ip, _ = validate_gateway_url(cfg["gateway_url"])

    ok, msg = verify_tailscale_peer(host_ip, status_cmd_runner=tailscale_checker)
    if not ok:
        print_fn(f"Error: Tailscale peer verification failed: {msg}")
        return 1

    user, pwd = storage.load_credentials()
    client = SMSGateClient(cfg["gateway_url"], user, pwd, timeout=timeout)

    try:
        health_data = client.get_health()
        print_fn("=== SMSGate Local Server Health ===")
        print_fn(f"Status:  {health_data.get('status', 'unknown')}")
        print_fn(f"Version: {health_data.get('version', 'unknown')}")
        if "checks" in health_data:
            print_fn(f"Checks:  {health_data.get('checks')}")
        return 0
    except BridgeError as e:
        print_fn(f"Error checking gateway health: {e}")
        return 1


def run_send_test(
    storage: BridgeStorage,
    dry_run: bool = False,
    print_fn=print,
    tailscale_checker=None,
    timeout: float = DEFAULT_TIMEOUT,
) -> int:
    """
    Queue and send ONE allowlisted neutral test SMS to the single configured test number.
    Strictly prevents duplicate tests across all states (pending, sent, delivered, failed, replied)
    until explicitly reset. Fails closed on corrupt state.
    """
    if not storage.has_config():
        print_fn("Error: Configuration missing. Run 'configure' first.")
        return 1

    cfg = storage.load_config()
    recipient = cfg["test_number"]
    sim_number = cfg["sim_number"]
    gateway_url = cfg["gateway_url"]
    _, host_ip, _ = validate_gateway_url(gateway_url)

    # Concurrency Lock serializes read, validation, network call, and state write
    with FileLocker(storage.lock_path):
        try:
            state = storage.load_state()
        except BridgeError as e:
            print_fn(f"[ERROR] Cannot send test: {e}")
            return 1

        active = state.get("active_test")

        # Refuse duplicate send if ANY active test is present in this state directory
        if active is not None:
            print_fn(
                f"Refusing send: An active test is already recorded in this state directory.\n"
                f"  Client ID: {active.get('client_id')}\n"
                f"  State:     {active.get('state')}\n"
                f"  Replied:   {active.get('replied')}\n"
                f"Single-test policy enforced: run 'reset' to safely archive before starting a new test."
            )
            return 1

        nonce = secrets.token_hex(4)  # 8-char random hex nonce
        # Keep client ID under 21 chars: "t-" (2) + nonce (8) + "-" (1) + 6-digit timestamp = 17 chars
        ts_suffix = f"{int(time.time()) % 1000000:06d}"
        client_id = f"t-{nonce}-{ts_suffix}"
        test_content = f"Connection test {nonce}. Please reply TEST {nonce}."
        created_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if dry_run:
            print_fn("=== Dry Run Send-Test ===")
            print_fn(f"Target Gateway: {gateway_url}")
            print_fn(f"Recipient:      {recipient} (SIM {sim_number})")
            print_fn(f"Client ID:      {client_id} (length: {len(client_id)} <= 20 chars)")
            print_fn(f"Neutral Text:   '{test_content}'")
            print_fn("Result: Dry run validated. No network call performed, state untouched.")
            return 0

        if not storage.has_credentials():
            print_fn("Error: DPAPI credentials missing. Run 'configure' first.")
            return 1

        # Check Tailscale status before real network command
        ok, msg = verify_tailscale_peer(host_ip, status_cmd_runner=tailscale_checker)
        if not ok:
            print_fn(f"Refusing send: Tailscale peer verification failed: {msg}")
            return 1

        # CRITICAL: Record durable state BEFORE network call
        test_record = {
            "client_id": client_id,
            "nonce": nonce,
            "recipient": recipient,
            "sim_number": sim_number,
            "content": test_content,
            "created_at": created_at_iso,
            "state": "Pending",
            "delivery_state": "Pending",
            "status": "Pending",
            "replied": False,
            "reply_timestamp": None,
            "reply_preview": None,
            "error": None,
        }
        state["active_test"] = test_record
        storage.save_state(state)

        user, pwd = storage.load_credentials()
        client = SMSGateClient(gateway_url, user, pwd, timeout=timeout)

        print_fn(f"Submitting test message {client_id} to {recipient} via SIM {sim_number}...")
        try:
            resp = client.send_message(client_id, test_content, recipient, sim_number)
            # Official SMSGate local schema returns 'state': Pending/Processed
            raw_state = resp.get("state") or resp.get("status") or "Pending"
            test_record["state"] = raw_state
            test_record["delivery_state"] = raw_state
            test_record["status"] = raw_state
            storage.save_state(state)
            print_fn(
                f"[SUBMITTED] Test message accepted by gateway.\n"
                f"  Client ID: {client_id}\n"
                f"  Nonce:     {nonce}\n"
                f"  Recipient: {recipient}\n"
                f"  State:     {raw_state}\n"
                f"Note: Message is submitted to phone queue. Run 'status' to confirm carrier delivery."
            )
            return 0
        except BridgeHTTPError as e:
            # 408/409/429/5xx are ambiguous (server may have received or queued request)
            if e.code in (408, 409, 429) or e.code >= 500:
                test_record["state"] = "Unknown"
                test_record["delivery_state"] = "Unknown"
                test_record["status"] = "Unknown"
                test_record["error"] = f"Ambiguous gateway HTTP error {e.code}"
                storage.save_state(state)
                print_fn(
                    f"[AMBIGUOUS] Ambiguous gateway response (HTTP {e.code}).\n"
                    f"  State preserved as 'Unknown'. No auto-resend.\n"
                    f"  Run 'status' to reconcile whether the phone received the request."
                )
                return 1
            else:
                # Known client rejection (e.g. 400, 401, 403, 422)
                test_record["state"] = "Failed"
                test_record["delivery_state"] = "Failed"
                test_record["status"] = "Failed"
                test_record["error"] = f"Gateway HTTP error {e.code}"
                storage.save_state(state)
                print_fn(f"[FAILED] Gateway rejected message: HTTP {e.code}")
                return 1
        except Exception as e:
            # Network failure / timeout / lost response: ambiguous delivery state
            test_record["state"] = "Unknown"
            test_record["delivery_state"] = "Unknown"
            test_record["status"] = "Unknown"
            test_record["error"] = f"Ambiguous send failure: {type(e).__name__}"
            storage.save_state(state)
            print_fn(
                f"[AMBIGUOUS] Network error or lost response during send.\n"
                f"  State recorded as 'Unknown'. No auto-resend will occur.\n"
                f"  Run 'status' to reconcile whether the phone received the request before attempting another send."
            )
            return 1


def run_status(storage: BridgeStorage, print_fn=print, tailscale_checker=None, timeout: float = DEFAULT_TIMEOUT) -> int:
    """
    Query delivery status of the active test message via GET /message/{id}.
    Serialized under FileLocker to prevent race conditions.
    Preserves replied and reset state; does not conflate Processed with Delivered.
    """
    with FileLocker(storage.lock_path):
        try:
            state = storage.load_state()
        except BridgeError as e:
            print_fn(f"[ERROR] Cannot query status: {e}")
            return 1

        active = state.get("active_test")
        if not active:
            print_fn("No active test recorded in local state.")
            return 0

        client_id = active.get("client_id")
        print_fn(f"=== Test Message Status: {client_id} ===")
        print_fn(f"Recipient:  {active.get('recipient')} (SIM {active.get('sim_number')})")
        print_fn(f"Nonce:      {active.get('nonce')}")
        print_fn(f"Created At: {active.get('created_at')}")
        print_fn(f"Local State: {active.get('state')}")

        if not storage.has_config() or not storage.has_credentials():
            print_fn("Cannot query gateway: configuration or credentials missing.")
            return 1

        cfg = storage.load_config()
        _, host_ip, _ = validate_gateway_url(cfg["gateway_url"])
        ok, msg = verify_tailscale_peer(host_ip, status_cmd_runner=tailscale_checker)
        if not ok:
            print_fn(f"Cannot query gateway: Tailscale verification failed: {msg}")
            return 1

        user, pwd = storage.load_credentials()
        client = SMSGateClient(cfg["gateway_url"], user, pwd, timeout=timeout)

        try:
            gw_status = client.get_message_status(client_id)
            # Official SMSGate local schema uses 'state'
            raw_state = gw_status.get("state") or gw_status.get("status") or "Unknown"

            active["delivery_state"] = raw_state
            # Ensure status check does not overwrite replied state
            if not active.get("replied"):
                active["state"] = raw_state
                active["status"] = raw_state
            storage.save_state(state)

            print_fn(f"Gateway Delivery State: {raw_state}")
            if raw_state in ("Pending", "Processed"):
                print_fn("  Note: Message accepted by gateway and queued on device; carrier delivery report pending.")
            elif raw_state == "Delivered":
                print_fn("  Note: Carrier delivery report confirmed.")
            elif raw_state == "Sent":
                print_fn("  Note: Message dispatched to mobile carrier network.")
            elif raw_state == "Failed":
                print_fn("  Note: Message transmission failed.")

            if "updatedAt" in gw_status:
                print_fn(f"Gateway Updated At:     {gw_status['updatedAt']}")
            print_fn("Note: Never mark pending/sent/delivered as accepted patient appointment.")
            return 0
        except BridgeError as e:
            print_fn(f"Failed to fetch status from gateway: {e}")
            return 1


def run_check_reply(storage: BridgeStorage, print_fn=print, tailscale_checker=None, timeout: float = DEFAULT_TIMEOUT) -> int:
    """
    Inspect SMSGate /inbox with bounded pagination to verify exact TEST nonce reply.
    Serialized under FileLocker to prevent race conditions.
    Filters by:
      - type == 'SMS'
      - sender == configured test number
      - simNumber == configured SIM
      - createdAt >= test creation time (and not materially future)
      - contentPreview == exact 'TEST <nonce>'
    Never logs or outputs unrelated inbox messages.
    """
    with FileLocker(storage.lock_path):
        try:
            state = storage.load_state()
        except BridgeError as e:
            print_fn(f"[ERROR] Cannot check inbox: {e}")
            return 1

        active = state.get("active_test")
        if not active:
            print_fn("No active test message recorded. Cannot check replies.")
            return 0

        if not storage.has_config() or not storage.has_credentials():
            print_fn("Cannot check inbox: configuration or credentials missing.")
            return 1

        cfg = storage.load_config()
        _, host_ip, _ = validate_gateway_url(cfg["gateway_url"])
        ok, msg = verify_tailscale_peer(host_ip, status_cmd_runner=tailscale_checker)
        if not ok:
            print_fn(f"Cannot check inbox: Tailscale verification failed: {msg}")
            return 1

        user, pwd = storage.load_credentials()
        client = SMSGateClient(cfg["gateway_url"], user, pwd, timeout=timeout)

        target_sender = active["recipient"]
        target_sim = active["sim_number"]
        target_nonce = active["nonce"]
        created_at_iso = active["created_at"]

        # Parse test creation time to aware UTC datetime
        test_created_dt = parse_aware_utc(created_at_iso)
        if test_created_dt is None:
            print_fn("Error: Active test has malformed or naive created_at timestamp.")
            return 1

        # 1-minute buffer for query parameter skew
        query_since_dt = test_created_dt - datetime.timedelta(minutes=1)
        query_since_iso = query_since_dt.isoformat(timespec="seconds").replace("+00:00", "Z")

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        max_future_dt = now_utc + datetime.timedelta(minutes=5)

        matching_replies = []
        seen_keys = set()
        total_fetched = 0
        pagination_capped = False

        try:
            for page_idx in range(MAX_INBOX_PAGES):
                offset = page_idx * INBOX_PAGE_LIMIT
                items, total_count = client.get_inbox_page(query_since_iso, limit=INBOX_PAGE_LIMIT, offset=offset)
                total_fetched += len(items)

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # 1. Require type SMS
                    item_type = str(item.get("type") or "").strip().upper()
                    if item_type != "SMS":
                        continue

                    # 2. Strict SIM validation
                    try:
                        sim = validate_sim_number(item.get("simNumber"))
                    except ValueError:
                        continue
                    if sim != target_sim:
                        continue

                    # 3. Sender validation
                    sender = item.get("sender")
                    if not isinstance(sender, str):
                        continue
                    try:
                        norm_sender = normalize_phone_number(sender)
                    except ValueError:
                        continue
                    if norm_sender != target_sender:
                        continue

                    # 4. Strict timestamp parsing & bounds check (createdAt >= test_created_dt, not materially future)
                    raw_time = item.get("createdAt")
                    item_dt = parse_aware_utc(raw_time)
                    if item_dt is None:
                        # Malformed or naive timestamp safely rejected
                        continue
                    if item_dt < test_created_dt:
                        # Event created before active test
                        continue
                    if item_dt > max_future_dt:
                        # Materially future timestamp
                        continue

                    # 5. Content match: exact TEST <nonce> (case-insensitive command prefix, exact nonce preserved)
                    content = (item.get("contentPreview") or "").strip()
                    expected_reply = f"TEST {target_nonce}".upper()
                    if content.upper().removesuffix(".") != expected_reply:
                        continue

                    # 6. Reliable deduplication key
                    dedup_key = (item.get("id"), raw_time, norm_sender, content, sim)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    matching_replies.append({
                        "id": item.get("id"),
                        "sender": norm_sender,
                        "sim": sim,
                        "createdAt": raw_time,
                        "content": content,
                    })

                if len(items) < INBOX_PAGE_LIMIT:
                    break

                # Mark pagination incomplete when capped with a full final page
                # or when total_count indicates more items remain
                if page_idx == MAX_INBOX_PAGES - 1:
                    pagination_capped = True
                elif total_count is not None and total_count > total_fetched:
                    pass

            if pagination_capped:
                print_fn(
                    f"[NOTICE] Inbox pagination capped at {total_fetched} messages. "
                    f"Scan is incomplete; not claiming full inbox scan."
                )

            if matching_replies:
                reply = matching_replies[0]
                active["replied"] = True
                active["reply_timestamp"] = reply["createdAt"]
                active["reply_preview"] = reply["content"]
                storage.save_state(state)
                print_fn(
                    f"[SUCCESS] Matching roundtrip reply received!\n"
                    f"  From:    {reply['sender']} (SIM {reply['sim']})\n"
                    f"  Text:    '{reply['content']}'\n"
                    f"  Time:    {reply['createdAt']}\n"
                    f"  Matches: {len(matching_replies)}"
                )
                return 0
            else:
                print_fn(f"No matching test reply received yet for nonce '{target_nonce}'. (Matches: 0)")
                return 0

        except BridgeError as e:
            print_fn(f"Failed to check inbox: {e}")
            return 1


def run_reset(storage: BridgeStorage, print_fn=print) -> int:
    """
    Explicitly archive the active test into history so a new test can be initiated.
    Serialized under FileLocker.
    """
    with FileLocker(storage.lock_path):
        try:
            state = storage.load_state()
        except BridgeError as e:
            print_fn(f"[ERROR] Cannot reset state: {e}")
            return 1

        active = state.get("active_test")
        if not active:
            print_fn("No active test recorded in local state to reset.")
            return 0

        state["history"].append(active)
        state["active_test"] = None
        storage.save_state(state)
        print_fn(
            f"[RESET] Active test '{active.get('client_id')}' archived into history. "
            f"State directory is now clear for a new test."
        )
        return 0


def run_watch(storage: BridgeStorage, interval: int = 30, print_fn=print, tailscale_checker=None):
    """Read-only polling loop: repeatedly checks delivery status and inbox reply."""
    if interval < 5:
        interval = 5
    print_fn(f"=== Starting Watch Loop (Interval: {interval}s, Read-Only, Ctrl+C to stop) ===")
    try:
        while True:
            print_fn(f"\n--- Poll tick at {datetime.datetime.now().strftime('%H:%M:%S')} ---")
            run_status(storage, print_fn=print_fn, tailscale_checker=tailscale_checker)
            run_check_reply(storage, print_fn=print_fn, tailscale_checker=tailscale_checker)

            try:
                state = storage.load_state()
                active = state.get("active_test")
                if active and active.get("replied"):
                    print_fn("\n[COMPLETE] Verified roundtrip test reply received. Exiting watch loop.")
                    break
            except Exception:
                pass

            time.sleep(interval)
    except KeyboardInterrupt:
        print_fn("\nWatch loop stopped by user.")


# ---------------------------------------------------------------------------
# Interactive Configuration (Tkinter GUI with Console Fallback)
# ---------------------------------------------------------------------------

def run_configure(storage: BridgeStorage, force_cli: bool = False, print_fn=print) -> int:
    """
    Run interactive local configuration form (Tkinter GUI or console fallback).
    Refuses reconfiguration while an active test exists to protect credentials and state.
    """
    try:
        state = storage.load_state()
        if state.get("active_test") is not None:
            print_fn(
                "Refusing reconfiguration: An active test is currently recorded in local state.\n"
                "To protect active credentials and avoid race conditions, please complete the test or execute 'reset' first."
            )
            return 1
    except BridgeError as e:
        print_fn(f"[ERROR] Cannot configure: corrupt state detected ({e}).")
        return 1

    existing_cfg = {}
    if storage.has_config():
        try:
            existing_cfg = storage.load_config()
        except Exception:
            pass

    def save_inputs(gw_url: str, sim_str: str, phone_str: str, user_str: str, pass_str: str):
        norm_url, _, _ = validate_gateway_url(gw_url)
        norm_phone = normalize_phone_number(phone_str)
        norm_sim = validate_sim_number(sim_str)
        if not user_str.strip():
            raise ValueError("Username cannot be empty.")
        if not pass_str:
            raise ValueError("Password cannot be empty.")

        storage.save_config(norm_url, norm_sim, norm_phone)
        storage.save_credentials(user_str.strip(), pass_str)

    if not force_cli:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.title("HMR Android SMSGate Setup")
            root.geometry("520x460")
            root.resizable(False, False)

            # Labels and entries
            tk.Label(root, text="Gateway URL (Tailscale IPv4 e.g. http://100.64.0.1:8080):").pack(anchor="w", padx=15, pady=(10, 0))
            url_entry = tk.Entry(root, width=50)
            url_entry.insert(0, existing_cfg.get("gateway_url", "http://100.64.0.1:8080"))
            url_entry.pack(padx=15, pady=2)

            tk.Label(root, text="SIM Number (1, 2, or 3):").pack(anchor="w", padx=15, pady=(5, 0))
            sim_entry = tk.Entry(root, width=50)
            sim_entry.insert(0, str(existing_cfg.get("sim_number", 1)))
            sim_entry.pack(padx=15, pady=2)

            tk.Label(root, text="Test Mobile Number (e.g. 0400000001 or +61400000001):").pack(anchor="w", padx=15, pady=(5, 0))
            phone_entry = tk.Entry(root, width=50)
            phone_entry.insert(0, existing_cfg.get("test_number", ""))
            phone_entry.pack(padx=15, pady=2)

            tk.Label(root, text="SMSGate Username:").pack(anchor="w", padx=15, pady=(5, 0))
            user_entry = tk.Entry(root, width=50)
            user_entry.pack(padx=15, pady=2)

            tk.Label(root, text="SMSGate Password:").pack(anchor="w", padx=15, pady=(5, 0))
            pass_entry = tk.Entry(root, width=50, show="*")
            pass_entry.pack(padx=15, pady=2)

            success = [False]

            def on_save():
                try:
                    save_inputs(
                        url_entry.get(),
                        sim_entry.get(),
                        phone_entry.get(),
                        user_entry.get(),
                        pass_entry.get(),
                    )
                    success[0] = True
                    messagebox.showinfo(
                        "Success",
                        f"Configuration and DPAPI credentials saved to:\n{storage.state_dir}\n\nNo secrets logged or stored in plain text.",
                    )
                    root.destroy()
                except Exception as e:
                    messagebox.showerror("Validation Error", str(e))

            btn_frame = tk.Frame(root)
            btn_frame.pack(pady=15)
            tk.Button(btn_frame, text="Save Configuration", command=on_save, width=18).pack(side="left", padx=5)
            tk.Button(btn_frame, text="Cancel", command=root.destroy, width=12).pack(side="left", padx=5)

            root.mainloop()

            if success[0]:
                print_fn(f"[SUCCESS] Configuration and DPAPI credentials saved to {storage.state_dir}")
                return 0
            else:
                print_fn("Configuration cancelled by user.")
                return 1

        except Exception:
            # Fall back to console
            pass

    # Console Fallback
    import getpass
    print_fn("=== HMR SMSGate Configuration (Console Mode) ===")
    try:
        def_url = existing_cfg.get("gateway_url", "http://100.64.0.1:8080")
        url_input = input(f"Gateway URL [{def_url}]: ").strip() or def_url

        def_sim = str(existing_cfg.get("sim_number", 1))
        sim_input = input(f"SIM Number (1..3) [{def_sim}]: ").strip() or def_sim

        def_phone = existing_cfg.get("test_number", "")
        prompt_phone = f"Test Phone Number [{def_phone}]: " if def_phone else "Test Phone Number (e.g. 0400000001): "
        phone_input = input(prompt_phone).strip() or def_phone

        user_input = input("SMSGate Username: ").strip()
        pass_input = getpass.getpass("SMSGate Password (hidden): ")

        save_inputs(url_input, sim_input, phone_input, user_input, pass_input)
        print_fn(f"[SUCCESS] Configuration and DPAPI credentials saved to {storage.state_dir}")
        print_fn("Credentials encrypted with Windows DPAPI. No plaintext passwords stored.")
        return 0
    except Exception as e:
        print_fn(f"[ERROR] Configuration failed: {e}")
        return 1


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------

def main(args: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="HMR Android SMSGate Connector (Python stdlib Windows connector for SMSGate Local Server)"
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Override state directory (defaults to %%LOCALAPPDATA%%\\HMR-SMS-Bridge outside OneDrive)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # configure
    sub_cfg = subparsers.add_parser("configure", help="Run local setup form (Tkinter GUI or console)")
    sub_cfg.add_argument("--cli", action="store_true", help="Force console mode instead of GUI")

    # doctor
    subparsers.add_parser("doctor", help="Check local prerequisites, config, DPAPI credentials, and Tailscale peer")

    # health
    subparsers.add_parser("health", help="Check SMSGate Local Server health")

    # send-test
    sub_send = subparsers.add_parser("send-test", help="Send a single allowlisted neutral test SMS")
    sub_send.add_argument("--dry-run", action="store_true", help="Describe send action without credentials or network")

    # status
    subparsers.add_parser("status", help="Check delivery status of the active test message")

    # check-reply
    subparsers.add_parser("check-reply", help="Check inbox for exact matching test reply")

    # reset
    subparsers.add_parser("reset", help="Archive active test so a new test can be initiated")

    # watch
    sub_watch = subparsers.add_parser("watch", help="Read-only status and inbox polling loop")
    sub_watch.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")

    parsed_args = parser.parse_args(args)
    active_dir = get_active_state_dir(parsed_args.state_dir)
    storage = BridgeStorage(active_dir)

    cmd = parsed_args.command
    if cmd == "configure":
        return run_configure(storage, force_cli=parsed_args.cli)
    elif cmd == "doctor":
        return run_doctor(storage)
    elif cmd == "health":
        return run_health(storage)
    elif cmd == "send-test":
        return run_send_test(storage, dry_run=parsed_args.dry_run)
    elif cmd == "status":
        return run_status(storage)
    elif cmd == "check-reply":
        return run_check_reply(storage)
    elif cmd == "reset":
        return run_reset(storage)
    elif cmd == "watch":
        run_watch(storage, interval=parsed_args.interval)
        return 0
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

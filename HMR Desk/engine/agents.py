"""Selectable local CLI and HTTP agents. Secrets are protected by Windows DPAPI."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlsplit
import db

STEPS = {"interview_assist", "report_draft", "report_assist"}

def defaults():
    """No developer paths or enabled clinical agents in a new installation."""
    return {"default": "", "per_step": {}, "agents": []}


def save(data):
    from jobs import atomic_json
    atomic_json(Path(db.DATA_DIR) / "agents.json", data)

def load():
    path = Path(db.DATA_DIR) / "agents.json"
    if not path.exists(): save(defaults())
    data = json.loads(path.read_text(encoding="utf-8"))
    # Existing configured integrations are preserved; never auto-install CLI agents.
    for a in data["agents"]: a.setdefault("route", default_route(a))
    return data


def default_route(a):
    cmd = a.get("command") or []
    program = re.split(r"[\\/]", cmd[0])[-1].lower() if isinstance(cmd, list) and cmd and isinstance(cmd[0], str) else ""
    return "skill" if a.get("type") == "cli" and program in ("claude", "claude.exe", "claude.cmd", "codex", "codex.exe", "codex.cmd") else "prompt"

def keypath(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}", name) or name.endswith((".", " ")): raise ValueError("invalid agent name")
    return Path(db.DATA_DIR) / "agent-keys" / (name + ".bin")

class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

def crypt(data, decrypt=False):
    if os.name != "nt": raise ValueError("DPAPI requires Windows")
    buf = ctypes.create_string_buffer(data)
    src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dst = Blob()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    if decrypt:
        ok = crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst))
    else:
        ok = crypt32.CryptProtectData(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst))
    if not ok: raise OSError("DPAPI operation failed")
    try: return ctypes.string_at(dst.data, dst.size)
    finally: kernel32.LocalFree(dst.data)

def validate(a):
    if not isinstance(a, dict): raise ValueError("invalid agent")
    keypath(a.get("name"))
    if type(a.get("enabled")) is not bool: raise ValueError("enabled must be boolean")
    typ = a.get("type")
    a.setdefault("route", default_route(a))
    if a["route"] not in ("skill", "prompt") or (typ == "api" and a["route"] != "prompt"): raise ValueError("invalid agent route")
    allowed = {"name", "type", "enabled", "note", "route"}
    if typ == "cli":
        allowed |= {"command", "env", "stdin", "model", "effort"}
        if "model" in a and (not isinstance(a["model"], str) or not a["model"]): raise ValueError("invalid model")
        if "effort" in a and a["effort"] not in ("minimal", "low", "medium", "high", "xhigh"): raise ValueError("invalid effort")
        cmd, env = a.get("command"), a.get("env")
        if not isinstance(cmd, list) or (a["enabled"] and not cmd) or any(not isinstance(x,str) or not x for x in cmd): raise ValueError("invalid command")
        if not isinstance(env,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not k or "=" in k for k,v in env.items()) or a.get("stdin") is not True: raise ValueError("invalid CLI configuration")
    elif typ == "api":
        allowed |= {"url", "model", "style"}
        url = a.get("url")
        if not isinstance(url,str): raise ValueError("invalid URL")
        u = urlsplit(url)
        if u.username or u.password or not u.hostname or u.fragment or not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1"))): raise ValueError("HTTPS required except localhost")
        if a.get("style") not in ("openai", "anthropic") or not isinstance(a.get("model"),str) or not a["model"]: raise ValueError("invalid API configuration")
    else: raise ValueError("invalid agent type")
    if set(a) - allowed or ("note" in a and not isinstance(a["note"],str)): raise ValueError("invalid agent fields")
    return a

def public(data):
    return {**data, "agents":[{**a, "has_key":keypath(a["name"]).is_file()} for a in data["agents"]]}

def put(body):
    if not isinstance(body,dict): raise ValueError("invalid agent")
    a = dict(body); key = a.pop("key", None)
    validate(a)
    if key is not None and (a["type"] != "api" or not isinstance(key,str) or not key): raise ValueError("invalid key")
    data = load()
    if key is not None:
        path = keypath(a["name"]); encrypted = crypt(key.encode("utf-8")); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(encrypted)
    data["agents"] = [x for x in data["agents"] if x["name"] != a["name"]] + [a]
    save(data)

def delete(name):
    data = load(); path = keypath(name)
    if not any(a["name"] == name for a in data["agents"]): raise ValueError("agent not found")
    data["agents"] = [a for a in data["agents"] if a["name"] != name]
    if data["default"] == name: data["default"] = None
    data["per_step"] = {k:v for k,v in data["per_step"].items() if v != name}
    save(data)
    if path.exists(): path.unlink()

def select(body):
    if not isinstance(body,dict) or not body or set(body) - {"default", "per_step"}: raise ValueError("invalid selection")
    data = load(); names = {a["name"] for a in data["agents"] if a["enabled"]}
    if "default" in body:
        if body["default"] not in names: raise ValueError("unknown or disabled agent")
        data["default"] = body["default"]
    if "per_step" in body:
        m = body["per_step"]
        if not isinstance(m,dict) or not set(m) <= STEPS or any(v is not None and v not in names for v in m.values()): raise ValueError("invalid step selection")
        for k,v in m.items():
            if v is None: data["per_step"].pop(k, None)
            else: data["per_step"][k] = v
    save(data)

def selected(step):
    data = load(); return data["per_step"].get(step, data["default"])

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def skill_run(a, prompt, cwd):
    env = os.environ.copy(); env.update(a["env"])
    cmd = a["command"]
    program = re.split(r"[\\/]", cmd[0])[-1].lower().removesuffix(".cmd").removesuffix(".exe")
    executable = shutil.which(cmd[0]) or cmd[0]
    if program == "claude":
        # Prompt on stdin: a multi-line argv is cut to its first line through claude.cmd on Windows.
        skills = Path(env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills"
        cmd = [executable, "-p", "--permission-mode", "acceptEdits", "--add-dir", str(skills),
               "--allowedTools", "Read,Glob,Grep,Write,Edit,Bash(python:*),Bash(py:*),WebSearch,WebFetch"]
        input_text = prompt
    elif program == "codex":
        cmd = [executable, "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(cwd), "-m", a.get("model", "gpt-6.1-terra"), "-c", 'model_reasoning_effort="' + a.get("effort", "high") + '"', "-"]
        input_text = prompt
    else: input_text = prompt
    try:
        result = subprocess.run(cmd, input=input_text, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=1800)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes): output = output.decode("utf-8", errors="replace")
        raise RuntimeError("agent command timed out\n" + "\n".join(output.splitlines()[-199:])) from None
    if result.returncode: raise RuntimeError("agent command failed (exit %s)\n%s" % (result.returncode, "\n".join(result.stdout.splitlines()[-199:])))
    return result.stdout


def get(name):
    a = next((a for a in load()["agents"] if a["name"] == name), None)
    if not a or not a["enabled"]: raise ValueError("unknown or disabled agent")
    return validate(a)


def run(name, prompt, test=False):
    a = get(name)
    if test and a["route"] == "skill":
        with tempfile.TemporaryDirectory() as cwd: return skill_run(a, prompt, cwd)
    if a["type"] == "cli":
        env = os.environ.copy(); env.update(a["env"])
        cmd = [shutil.which(a["command"][0]) or a["command"][0], *a["command"][1:]]  # claude/codex are .cmd launchers on Windows
        if len(cmd) >= 2 and cmd[-1] == '--print' and any('agy-profile.ps1' in x.lower() for x in cmd):
            # agy print mode takes no stdin; it reads a file when told to (checked 12 Nov), so long prompts fit.
            fd, prompt_file = tempfile.mkstemp(suffix='.txt', prefix='hmr-prompt-')
            with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(prompt)
            try:
                result = subprocess.run([*cmd, 'Read the file ' + prompt_file + ' and follow the instructions in it exactly. Reply with only what it asks for.'],
                                        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
            finally:
                os.unlink(prompt_file)
        else:
            result = subprocess.run(cmd, input=prompt, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        if result.returncode: raise RuntimeError("agent command failed (exit %s)\n%s" % (result.returncode, "\n".join(result.stderr.splitlines()[-199:])))
        return result.stdout
    path = keypath(name)
    key = crypt(path.read_bytes(), True).decode("utf-8") if path.exists() else ""
    headers = {"Content-Type":"application/json"}
    payload = {"model":a["model"], "messages":[{"role":"user", "content":prompt}]}
    if a["style"] == "anthropic":
        headers.update({"x-api-key":key, "anthropic-version":"2023-06-01"}); payload["max_tokens"] = 8192
    elif key: headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(a["url"], data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=600) as response: result = json.load(response)
        return result["content"][0]["text"] if a["style"] == "anthropic" else result["choices"][0]["message"]["content"]
    except Exception as exc: raise RuntimeError("agent API request failed: " + type(exc).__name__) from None

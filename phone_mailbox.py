#!/usr/bin/env python3
"""phone_mailbox.py -- Phone mailbox client -- fetch what the server wants to say, then dial and speak it.

Usage:
  python get_call.py                 # check once
  python get_call.py --loop 60       # check every 60 s
  python get_call.py --dry-run       # show what would be said, do not dial
  python get_call.py --reset         # forget cursor, replay everything
  python get_call.py --port COM5 --phone 1xxxxxxxxxx --save   # write call-config.txt

Config file (call-config.txt, next to this script, UTF-8):
  port=COM5
  phone=1xxxxxxxxxx
  script=ec20_uac_call.py
  url=http://.../outbox/messages.json

Each message is played only once (local cursor file call-last-id.txt).
"""
import argparse, json, os, sys, time, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_URL = "https://your-server.example.com/phone-mailbox/messages.json"  # ← 换成你自己的地址
DEFAULTS = {"script": "ec20_uac_call.py", "url": DEFAULT_URL}

def log(*a):
    print(*a, flush=True)

def load_config(path, port=None, phone=None):
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if v.strip():
                    cfg[k.strip()] = v.strip()
    if port:
        cfg["port"] = port
    if phone:
        cfg["phone"] = phone
    return cfg

def load_phones(path):
    """本机号码别名表：  me=138xxxxxxxx / work=139xxxxxxxx  (文件不进公网)"""
    phones = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() and v.strip():
                    phones[k.strip()] = v.strip()
    return phones


def resolve_phone(value, cfg, phones):
    """把消息里的 phone 字段解析成真实号码。
    允许：别名（走本机 phones.txt）或纯数字（本机命令行直接给）。
    别名查不到 -> 拒绝拨打（白名单作用），返回 (None, 原因)。"""
    v = (value or "").strip()
    if not v:
        return cfg.get("phone", ""), ""
    if v.isdigit():                       # 命令行直接给数字：允许（没经过公网）
        return v, ""
    if v in phones:
        return phones[v], ""
    return None, ("unknown phone alias '%s' -- add a line like %s=1xxxxxxxxxx to phones.txt" % (v, v))


def save_config(path, cfg):
    keep = ["port", "phone", "script", "url"]
    merged = dict(DEFAULTS); merged.update(cfg)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# phone mailbox client config\n")
        for k in keep:
            f.write("%s=%s\n" % (k, merged.get(k, "")))
    log("saved -> %s" % path)

def fetch(url):
    import urllib.request
    if url.startswith("file://") or os.path.exists(url):
        raw = open(url.replace("file://", ""), "rb").read()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "ec20-callbox/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
    return json.loads(raw.decode("utf-8"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "call-config.txt"))
    ap.add_argument("--loop", type=int, default=0, help="poll every N seconds")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--port"); ap.add_argument("--phone")
    ap.add_argument("--script", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--say-flags", default="", help="extra flags for ec20_uac_call.py")
    a = ap.parse_args()

    phones_path = os.path.join(HERE, "phones.txt")
    phones = load_phones(phones_path)
    cfg = load_config(a.config, a.port, a.phone)
    if a.script: cfg["script"] = a.script
    if a.url:    cfg["url"] = a.url

    if a.save or (a.port and a.phone and not os.path.exists(a.config)):
        save_config(a.config, cfg)

    missing = [k for k in ("port", "phone") if not cfg.get(k)]
    if missing:
        log("CONFIG PROBLEM: missing %s" % ", ".join(missing))
        log("  file: %s" % a.config)
        log("  easiest fix -- run this once (replace with your own values):")
        log("    python get_call.py --port COM5 --phone 1xxxxxxxxxx --save")
        return 2

    script = cfg.get("script") or "ec20_uac_call.py"
    script_path = script if os.path.isabs(script) else os.path.join(HERE, script)
    if not os.path.exists(script_path) and "--" not in script:
        log("MISSING SCRIPT: %s" % script_path)
        return 3

    cursor_path = os.path.join(HERE, "call-last-id.txt")
    cursor = 0
    if os.path.exists(cursor_path) and not a.reset:
        try:
            cursor = int(open(cursor_path, encoding="utf-8").read().strip() or 0)
        except ValueError:
            cursor = 0

    log("phone mailbox | cursor=%d | port=%s | phone=%s | aliases=%d"
        % (cursor, cfg["port"], cfg["phone"], len(phones)))
    if a.dry_run:
        log("(dry-run: will not dial)")

    def once(cur):
        try:
            box = fetch(cfg["url"])
        except Exception as e:
            log("fetch failed: %s" % e)
            return cur
        new = sorted([m for m in box.get("messages", []) if int(m["id"]) > cur],
                     key=lambda m: int(m["id"]))
        if not new:
            log("no new message")
            return cur
        extra = a.say_flags.split() if a.say_flags else []
        for m in new:
            log("")
            log("==> message #%s  (%s)" % (m["id"], m.get("created", "?")))
            log("    %s" % m["text"])
            if a.dry_run:
                continue          # 只看不拨：不推进游标，消息留给你下次真打
            target, why = resolve_phone(m.get("phone"), cfg, phones)
            if target is None:
                log("    REFUSED: %s" % why)
                log("    (message #%s skipped)" % m["id"])
                continue
            cmd = [sys.executable, script_path, "--say", m["text"],
                   "--port", cfg["port"], "--dial", target] + extra
            log("    dialing %s on %s ..." % (target, cfg["port"]))
            rc = subprocess.call(cmd)
            if rc != 0:
                log("    WARNING: ec20_uac_call.py exited %d (marking handled anyway)" % rc)
            cur = int(m["id"])
            with open(cursor_path, "w", encoding="utf-8") as f:
                f.write(str(cur))
            if len(new) > 1:
                time.sleep(5)
        return cur

    if a.loop > 0:
        log("polling every %ds -- Ctrl+C to stop" % a.loop)
        while True:
            cursor = once(cursor)
            time.sleep(a.loop)
    else:
        once(cursor)
        log("done")
    return 0

if __name__ == "__main__":
    sys.exit(main())

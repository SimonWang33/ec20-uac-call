#!/usr/bin/env python3
"""打电话信箱：往队列里放一条要念的话。

用法:
  python3 ec20_say.py "要念的话"
  python3 ec20_say.py "要念的话" --phone me2        # 号码别名（真号码只在用户电脑上）
  python3 ec20_say.py "要念的话" --at "2026-10-14 08:00"
  python3 ec20_say.py --clear                       # 清空信箱（只留最新一条时用）

注意:
  - 该文件是公网可读的（靠 16 位随机路径保护）→ 只能放"短提醒"，
    金额/人名/隐私内容不要放；号码只写别名，绝不写真实号码。
  - Caddy 以 caddy 用户运行，文件必须 644 / 目录 755，否则 403。
"""
import datetime, json, os, sys

MJ = os.environ.get("PHONE_MAILBOX_JSON", "/var/www/phone-mailbox/messages.json")
OB = os.path.dirname(MJ)


def _load():
    os.makedirs(OB, exist_ok=True)
    os.chmod(OB, 0o755)
    if not os.path.exists(MJ):
        return {"next_id": 1, "messages": []}
    return json.load(open(MJ, encoding="utf-8"))


def _save(d):
    tmp = MJ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644)          # Caddy(caddy 用户) 必须能读
    os.replace(tmp, MJ)


def put(text, at=None, phone=None):
    d = _load()
    mid = d["next_id"]; d["next_id"] += 1
    item = {"id": mid, "text": text, "at": at,
            "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if phone:
        item["phone"] = phone      # 只写别名，不写真实号码
    d["messages"].append(item)
    d["messages"] = d["messages"][-20:]
    _save(d)
    return mid


def clear():
    d = _load(); d["messages"] = []; _save(d)


def main():
    argv = sys.argv[1:]
    at = argv[argv.index("--at") + 1] if "--at" in argv else None
    phone = argv[argv.index("--phone") + 1] if "--phone" in argv else None
    if "--clear" in argv:
        clear(); print("信箱已清空"); return 0
    # 取第一个不是选项值的位置参数
    skip = set()
    for flag in ("--at", "--phone"):
        if flag in argv:
            skip.add(argv.index(flag) + 1)
    words = [a for i, a in enumerate(argv) if not a.startswith("--") and i not in skip]
    if not words:
        print(__doc__); return 1
    text = words[0]
    mid = put(text, at, phone)
    print("已放入信箱 #%d: %s%s" % (mid, text, ("（号码别名：%s）" % phone) if phone else "（用默认号码）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

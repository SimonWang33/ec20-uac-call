# -*- coding: utf-8 -*-
"""
EC20 UAC 通话测试（Windows）— 直接按移远官方 UAC 参数推送声音
官方参数：8000Hz / 16-bit / 单声道（部分模组 16000Hz）

用法：
  1) 看设备:      python ec20_uac_call.py --list
  2) 试音（最重要）: python ec20_uac_call.py --port COM5 --dial 1xxxxxxxxxx --tone
  3) 放自己的录音:  python ec20_uac_call.py --port COM5 --dial 1xxxxxxxxxx --wav my8k.wav
  4) 挂断:        python ec20_uac_call.py --port COM5 --hangup
可选： --rate 16000（改采样率）  --exclusive（WASAPI 独占模式）  --dev "AC Interface"

依赖： pip install pyserial sounddevice
"""
import argparse, os, sys, time, math, struct, subprocess, wave, array

def find_uac_device(exact=None):
    """在输出设备里找 UAC 音频，并按"像不像模块"排序打分。

    移远官方 UAC 参数：单声道 + 8000Hz（部分 16000Hz）→ 优先挑这类端点。
    """
    import sounddevice as sd
    cand = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_output_channels", 0) < 1:
            continue
        nm = d["name"]
        if exact:
            hit = exact.lower() in nm.lower()
        else:
            hit = any(k in nm.lower() for k in ("usb audio", "ac interface", "android", "quectel"))
        if not hit:
            continue
        ch = d["max_output_channels"]
        rate = float(d.get("default_samplerate") or 0)
        host = sd.query_hostapis(d["hostapi"])["name"]
        score = 0
        if ch == 1:                      # 官方是单声道
            score += 5
        if int(rate) in (8000, 16000):   # 官方采样率
            score += 4
        if "WASAPI" in host:
            score += 3
        elif "WDM-KS" in host:
            score += 1
        cand.append((score, i, d, host, ch, rate))
    cand.sort(key=lambda x: (-x[0], x[1]))
    return [i for _, i, _, _, _, _ in cand], cand          # (索引列表, 打分明细)

def cmd_list():
    import sounddevice as sd
    print("=== 所有输出设备 ===")
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_output_channels", 0) >= 1:
            print("  [%d] %-46s 通道=%d 默认采样率=%s  主机API=%s" % (
                i, d["name"][:46], d["max_output_channels"],
                d.get("default_samplerate"), sd.query_hostapis(d["hostapi"])["name"]))
    hits, cand = find_uac_device()
    print("\n=== 疑似 UAC 音频设备（按「像不像模块」排序）===")
    if cand:
        for score, i, d, host, ch, rate in cand[:6]:
            mark = "⭐ 首选" if (score, ) == (cand[0][0], ) else "      "
            print("  %s [%d] %-34s 通道=%d 采样率=%s  %s" % (mark, i, d["name"][:34], ch, int(rate), host))
        top = cand[0]
        print("\n👉 直接跑这个试音（号码换成你自己的另一张卡）：")
        print('   python .\\ec20_uac_call.py --port COM5 --dial 你的号码 --tone --dev %d' % top[1])
        print("   （不行就把 --dev %d 换成别的索引，或加 --rate 16000 / --exclusive）" % top[1])
    else:
        print("  ⚠️ 没找到，请把上面完整列表发我")

def at(ser, cmd, wait=1.0, quiet=False):
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode())
    time.sleep(wait)
    out = ser.read_all().decode(errors="ignore").strip()
    if not quiet:
        print("  > %-28s → %s" % (cmd, out.replace("\n", " / ")[:120] or "(无回显)"))
    return out

def make_tone(rate, seconds=6.0, freq=1000.0, amp=0.45):
    """生成单声道 16-bit 正弦测试音（官方格式：8k/16bit/mono）。"""
    n = int(rate * seconds)
    buf = array.array("h")
    step = 2.0 * math.pi * freq / rate
    for i in range(n):
        # 前 200ms/后 200ms 淡入淡出，避免爆音
        g = min(1.0, i / (0.2 * rate), (n - i) / (0.2 * rate))
        buf.append(int(32767 * amp * g * math.sin(step * i)))
    return buf.tobytes()

def load_wav(path, rate):
    """读 WAV，必要时线性重采样到目标采样率、单声道、16-bit。"""
    with wave.open(path, "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise SystemExit("只支持 16-bit WAV；请先转成 16bit")
    a = array.array("h"); a.frombytes(raw)
    if ch > 1:                                        # 下混单声道
        a = array.array("h", [sum(a[i:i+ch]) // ch for i in range(0, len(a) - ch + 1, ch)])
    if sr != rate and sr > 0:                         # 线性重采样
        out = array.array("h"); ratio = sr / float(rate); total = int(len(a) / ratio)
        for i in range(total):
            x = i * ratio; i0 = int(x); frac = x - i0
            v = a[i0] if i0 + 1 >= len(a) else a[i0] + (a[i0+1] - a[i0]) * frac
            out.append(int(max(-32768, min(32767, v))))
        a = out
    return a.tobytes(), rate

def _ladders(dev, rate, channels=1, dtype="int16"):
    """同一端点用几种写法依次尝试（绕过 sounddevice 0.5.x 的参数握手问题）。"""
    return [
        ("basic", dict(samplerate=rate, channels=channels, dtype=dtype, device=dev)),
        ("latency=high", dict(samplerate=rate, channels=channels, dtype=dtype, device=dev, latency="high")),
        ("blocksize=800", dict(samplerate=rate, channels=channels, dtype=dtype, device=dev, blocksize=800)),
        ("device=(None,dev)", dict(samplerate=rate, channels=channels, dtype=dtype, device=(None, dev))),
        ("rate=float", dict(samplerate=float(rate), channels=channels, dtype="int16", device=dev)),
    ]


def play(bytes_, rate, dev, exclusive=False, seconds=None):
    """把 PCM 推进 UAC 端点：写法逐个降级试，成功即用。"""
    import sounddevice as sd
    if isinstance(bytes_, tuple):            # 兼容 load_wav() 的 (data, rate)
        bytes_, rate = bytes_[0], bytes_[1]
    if not isinstance(bytes_, (bytes, bytearray, memoryview)):
        bytes_ = bytes(bytes_)
    last = None
    for name, kw in _ladders(dev, rate):
        if exclusive:
            try:
                kw["extra_settings"] = sd.WasapiSettings(exclusive=True)
            except Exception:
                pass
        try:
            stream = sd.RawOutputStream(**kw)
            break
        except Exception as e:
            last = "%s → %s" % (name, str(e).split("[")[0].strip()[:110])
            print("   ✗ 写法 %-20s 失败：%s" % (name, str(e)[:90]))
            stream = None
    if stream is None:
        print("  ⚠️ 所有写法都失败；最后一次：%s" % last)
        print("     👉 跑 `--diag` 把完整诊断发我")
        return
    print("  ▶ 播放中（写法：%s）：%s  %d Hz / 16bit / 单声道" % (name, str(dev)[:30], rate))
    try:
        with stream:
            chunk = rate * 2 // 20
            for off in range(0, len(bytes_), chunk):
                stream.write(bytes_[off:off + chunk])
        print("  ■ 播放完毕")
    except Exception as e:
        print("  ⚠️ 写入失败：", str(e)[:140])


def cmd_diag():
    """一键诊断：输出版本、默认参数、以及每种写法能否打开这个端点。"""
    import sounddevice as sd
    print("sounddevice 版本:", getattr(sd, "__version__", "?"))
    print("PortAudio 版本:", getattr(sd, "get_portaudio_version", lambda: "?")())
    print("default.extra_settings =", repr(sd.default.extra_settings),
          "  type=", type(sd.default.extra_settings).__name__)
    print("default.latency =", repr(sd.default.latency), " default.device =", repr(sd.default.device))
    hits, cand = find_uac_device()
    if not hits:
        print("⚠️ 没找到 UAC 设备"); return
    dev = hits[0]
    print("\n目标设备 [%d] %s" % (dev, cand[0][2]["name"]))
    print("\n写法                     结果")
    print("-----------------------  ----")
    for name, kw in _ladders(dev, 8000):
        try:
            with sd.RawOutputStream(**kw) as st:
                st.write(b"\x00" * 1600)
            print("  %-22s ✅ 可打开" % name)
        except Exception as e:
            print("  %-22s ✗ %s" % (name, str(e).split("[")[0].strip()[:60]))
    print("\n👉 把上面整段发我（含版本号与每行结果）")


def build_sapi_ps1(text, out_wav, voice="", rate=None):
    """生成"用 Windows 自带语音合成 WAV"的 PowerShell 脚本文本（纯函数，便于测试）。"""
    t = text.replace("'", "''")                      # PowerShell 单引号转义
    o = out_wav.replace("'", "''")
    v = ("$s.SelectVoice('%s');" % voice.replace("'", "''")) if voice else ""
    r = ("$s.Rate=%d;" % rate) if rate is not None else ""
    withfmt = ("$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000,"
               "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
               "[System.Speech.AudioFormat.AudioChannel]::Mono);"
               "$s.SetOutputToWaveFile('%s',$f);" % o)
    nofmt = "$s.SetOutputToWaveFile('%s');" % o
    return ("$ErrorActionPreference='Stop';"
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            + v + r +
            "try{" + withfmt + "}catch{" + nofmt + "}"      # SAPI 不支持 8k 时退回默认格式
            "$s.Speak('%s');" % t +
            "$s.Dispose();Write-Host 'ok'")


def say_to_wav(text, out="say8k.wav", voice="", rate=None):
    """用 Windows 自带语音(SAPI)生成 8000Hz/16bit/单声道 WAV —— 不需要任何额外 Python 包。"""
    if os.name != "nt":
        print("⚠️ --say 只能在 Windows 上用（走系统自带语音 SAPI）"); return None
    ps = build_sapi_ps1(text, os.path.abspath(out), voice, rate)
    tmp = os.path.join(os.path.dirname(os.path.abspath(out)), "_say.ps1")
    with open(tmp, "w", encoding="utf-8-sig") as f:      # BOM：保证中文被正确读取
        f.write(ps)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        print("⚠️ 生成语音失败：", (r.stderr or r.stdout or "")[:240]); return None
    print("✅ 已生成语音（8000Hz/16bit/单声道）：%s（%d 字节）" % (out, os.path.getsize(out)))
    return out


def cmd_voices():
    """列出系统可用的语音（中文音色）。"""
    ps = ("Add-Type -AssemblyName System.Speech;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "$s.GetInstalledVoices()|%%{Write-Host ($_.VoiceInfo.Name+'  ['+$_.VoiceInfo.Culture+']')}")
    r = subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr[:200])


def cmd_probe(dev_name=None):
    """逐个试采样率/通道，找出这个 UAC 端点真正接受的格式。"""
    import sounddevice as sd
    hits, cand = find_uac_device(dev_name)
    if not hits:
        print("⚠️ 没找到 UAC 设备；可用 --dev 指定索引"); return
    dev = hits[0]
    print("探测设备 [%d] %s\n" % (dev, cand[0][2]["name"]))
    print("采样率  通道  结果")
    print("------  ----  ----")
    for rate in (8000, 16000, 32000, 44100, 48000):
        for ch in (1, 2):
            try:
                with sd.RawOutputStream(samplerate=rate, channels=ch, dtype="int16", device=dev):
                    print("  %5d   %d    ✅ 可打开" % (rate, ch))
            except Exception as e:  # noqa: BLE001
                print("  %5d   %d    ✗ %s" % (rate, ch, str(e).split("[")[0].strip()[:44]))
    print("\n👉 只有 ✅ 的组合才是这个端点真正支持的；官方 UAC 参数是 8000/单声道")


def cmd_rec(seconds=5.0, dev_name=None, out="uac_rec.wav"):
    """录一段（通话时用来验证「下行音频」到底有没有送进来）。"""
    import sounddevice as sd, wave
    hits, cand = find_uac_device(dev_name)
    dev = hits[0] if hits else None
    info = sd.query_devices(dev) if dev is not None else None
    if info:
        print("录制设备: [%s] %s   输入通道=%d" % (dev, info["name"], info.get("max_input_channels", 0)))
        if info.get("max_input_channels", 0) < 1:
            print("⚠️ 这个端点没有输入通道（只有播放）→ 模块不提供「下行音频」的录音路径")
            return
    raw, used = b"", None
    for rate in (8000, 16000):                    # 下行常见 8k(NB)/16k(WB)
        try:
            with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16", device=dev) as stream:
                frames = []
                for _ in range(int(seconds * rate / 800)):
                    data, _ = stream.read(800)
                    frames.append(bytes(data))
                raw, used = b"".join(frames), rate
            break
        except Exception as e:  # noqa: BLE001
            print("  %d Hz 打不开：%s" % (rate, str(e).split("[")[0].strip()[:60]))
    if used is None:
        print("⚠️ 录制失败（两种采样率都打不开）"); return
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(used); w.writeframes(raw)
    peak = max((abs(int.from_bytes(raw[i:i+2], "little", signed=True)) for i in range(0, min(len(raw), 16000), 2)), default=0)
    print("已保存 %s（%d 字节）  峰值电平=%d" % (out, len(raw), peak))
    print("👉 峰值≈0 = 完全静音（下行没送进来）；峰值>300 = 有真实声音")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--probe", action="store_true", help="试出设备真正支持的采样率")
    ap.add_argument("--rec", type=float, default=0, help="录制 N 秒（通话时验证下行音频）")
    ap.add_argument("--port", default="COM5", help="AT 串口，如 COM5")
    ap.add_argument("--dial"); ap.add_argument("--hangup", action="store_true")
    ap.add_argument("--tone", action="store_true"); ap.add_argument("--wav")
    ap.add_argument("--dev", default=None, help="音频设备名片段或索引")
    ap.add_argument("--rate", type=int, default=8000)
    ap.add_argument("--exclusive", action="store_true")
    ap.add_argument("--keep", action="store_true", help="播完不挂断")
    ap.add_argument("--no-qpcmv", action="store_true", help="不自动发 AT+QPCMV")
    ap.add_argument("--say", help="要念出来的文字（用 Windows 自带语音合成，再打进电话）")
    ap.add_argument("--voice", default="", help="指定语音名（--voices 可列出）")
    ap.add_argument("--voices", action="store_true", help="列出系统可用语音")
    ap.add_argument("--diag", action="store_true", help="一键诊断：逐种写法试打开端点")
    a = ap.parse_args()
    if a.probe:
        cmd_probe(a.dev); return
    if a.diag:
        cmd_diag(); return
    if a.voices:
        cmd_voices(); return
    if a.say:
        w = say_to_wav(a.say, a.wav or "say8k.wav", a.voice)
        if not w:
            return
        a.wav = w
        if not a.dial:
            print("\n（只生成语音；要打出去就再加 --port COMx --dial 号码）"); return
    if a.rec:
        if a.port and not a.no_qpcmv:
            try:
                import serial
                ser = serial.Serial(a.port, 115200, timeout=1); time.sleep(0.3)
                at(ser, "AT+QPCMV=1,2", wait=1)
                cmd_rec(a.rec, a.dev)
                at(ser, "AT+QPCMV=0", wait=1)
                ser.close(); return
            except Exception as e:
                print("（启用 QPCMV 失败，继续直接录）", str(e)[:80])
        cmd_rec(a.rec, a.dev); return
    if a.list or not (a.dial or a.hangup):
        cmd_list(); return
    import serial
    dev = a.dev
    if dev is None:
        hits, cand = find_uac_device()
        if not hits:
            print("⚠️ 没找到 UAC 输出设备，先跑 --list 并把列表发我"); return
        dev = hits[0]
        sc = cand[0]
        print("自动选中音频设备 [%d] %s（通道=%d 采样率=%dHz %s）"
              % (dev, sc[2]["name"], sc[4], int(sc[5]), sc[3]))
    elif str(dev).isdigit():
        dev = int(dev)
    ser = serial.Serial(a.port, 115200, timeout=1)
    time.sleep(0.3)
    print("=== 模块自检 ===")
    at(ser, "ATI"); at(ser, 'AT+CPIN?'); at(ser, 'AT+QCFG="ims"')
    if a.hangup:
        at(ser, "AT+CHUP"); ser.close(); return
    if not a.no_qpcmv:
        print("\n=== 启用 UAC 语音（AT+QPCMV=1,2 —— 官方必需步骤）===")
        at(ser, "AT+QPCMV=?", wait=1)
        at(ser, "AT+QPCMV=1,2", wait=1)
        at(ser, "AT+QPCMV?", wait=1)
    print("\n=== 拨号（语音必须带分号）===")
    at(ser, "ATD%s;" % a.dial, wait=4)
    at(ser, "AT+CLCC", wait=1, quiet=True)
    print("\n=== 推声音（官方参数：%d Hz / 16bit / 单声道）===" % a.rate)
    if a.tone:
        data = make_tone(a.rate)
    else:
        data, _ = load_wav(a.wav, a.rate)          # ← 这里以前漏了解包（bug 根因）
    try:
        play(data, a.rate, dev, a.exclusive)
    except Exception as e:
        print("  ⚠️ 播放失败:", e)
        print("     提示：试 `--probe` 看这个端点接受哪些采样率；或 `--exclusive` 走独占模式")
    if not a.keep:
        print("\n=== 挂断 + 关闭 UAC 语音（官方 Step 8，不关的话下一通会没声音）===")
        at(ser, "AT+CHUP")
        if not a.no_qpcmv:
            at(ser, "AT+QPCMV=0", wait=1)
    ser.close()
    print("\n👉 问一下对方：听到「嘟——」的测试音了吗？听到了就说明 UAC 链路通了 ✅")

if __name__ == "__main__":
    main()

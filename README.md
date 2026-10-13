# 用 4G 模块让电脑打电话（EC20 / Windows / Python）

让一台 **Windows 电脑**通过 4G 模块直接拨号，并把**文字用电脑合成的语音念给对方听**；
再进一步，做成「**电话信箱**」——服务器上写一句话，家里电脑自动拨号念出来（让 AI 主动给你打电话）。

> **实测结论**：这条路走通了 —— 对端手机能听到电脑合成的完整中文语音。
> 公开案例里 EC20 的 UAC 语音几乎全在 Linux（Asterisk + chan-quectel），Windows 侧很少见，
> 所以把过程和踩过的坑都记在这里。

---

## 1. 它能做什么

| 能力 | 命令 |
|---|---|
| 拨号 + 推测试音（验证链路） | `python ec20_uac_call.py --tone --port COM5 --dial 你的号码` |
| **念一段话打过去**（TTS） | `python ec20_uac_call.py --say "要念的话" --port COM5 --dial 你的号码` |
| 播放自备录音 | `python ec20_uac_call.py --wav foo.wav --port COM5 --dial 你的号码` |
| 挂断 / 诊断 | `--hangup` / `--list` / `--probe` / `--diag` / `--rec 5` |
| 电话信箱（服务器 → 电脑自动拨打） | `python phone_mailbox.py`（或 `tools/9-get-call-loop.bat` 常驻） |

**已知限制**：当前只做「电脑 → 对方」的说话方向；实测的 Windows 端点上没有可用的**录音（上行）**通道，
所以「听对方说什么」还没做（`--rec` 可以用来确认端点到底有没有输入通道）。

---

## 2. 硬件与前置

* 4G 模块：Quectel **EC20**（USB 版，含 UAC 音频接口）
* 一张**自己的**手机卡（实测中国移动卡可注册 VoLTE；电信卡因固件档位缺 IMS 参数不可行）
* Windows 10/11 电脑
* Python 3.8+
* 依赖：`pyserial`、`sounddevice`（无 numpy 也可运行）
  ```powershell
  python -m pip install pyserial sounddevice
  ```

> ⚠️ 模块请插在**手机卡归属国境内**的电脑上。把国内卡插到境外服务器上长期使用会走国际漫游，产生费用且不合规。

---

## 3. 快速开始

```powershell
# 1) 找到模块的音频端点（模块那个应该是 通道=1、默认采样率=8000、WASAPI）
python ec20_uac_call.py --list

# 2) 找到 AT 串口（设备管理器 → 端口(COM 和 LPT)），先确认能通信
#    ATI            → 返回模块型号
#    AT+CPIN?       → +CPIN: READY

# 3) 先跑测试音（这一步成功 = 链路通了）
python ec20_uac_call.py --tone --port COM5 --dial 你的号码

# 4) 念一句话打过去
python ec20_uac_call.py --say "你好，这是一通来自电脑的测试电话" --port COM5 --dial 你的号码
```

脚本会自动完成一整套流程（这是踩坑之后的最终顺序）：

```
ATI → AT+CPIN? → AT+QCFG="ims" → AT+QPCMV=? → AT+QPCMV=1,2 → AT+QPCMV?
→ ATD<号码>;  （通话建立）
→ 把 8000Hz/16bit/单声道 PCM 推进 UAC 端点
→ AT+CHUP → AT+QPCMV=0
```

---

## 4. 完整实验过程

### Step 1 · 认识模块：USB 设备与接口
模块插上后会在设备管理器里出现若干接口（AT 口 / 数据口 / 音频口）。
UAC 音频接口的特征是硬件 ID 形如：

```
USB\VID_2C7C&PID_0125&REV_xxxx&MI_05
        └ Quectel  └ 音频接口(AC Interface)
```

`MI_05` 就是那个 `扬声器 (AC Interface)` 端点。

### Step 2 · 确认 UAC 功能已打开

```
AT+QCFG="USBCFG"
```
返回 **7 个参数**（如 `0x2C7C,0x0125,1,1,1,1,1,0,1`）表示支持 UAC；**最后一位 = 1 表示 UAC 已开启**。

> ⚠️ **不要改 VID/PID**（`0x2C7C,0x0125`）——改了会认不出设备。

### Step 3 · SIM 与网络

```
AT+CPIN?          → +CPIN: READY
AT+COPS?          → 已注册的运营商
AT+CEREG?         → 0,1（已附着 4G）
AT+CSQ            → 信号质量
```

### Step 4 · ⭐ VoLTE 注册（决定能不能打电话）

```
# 先看当前配置
AT+QMBNCFG="List"
AT+QCFG="ims"                     → +QCFG: "ims",0,0    ← 0,0 = 没注册上

# 移动卡：选对应档位 → 打开 IMS → 重启协议栈
AT+QMBNCFG="AutoSel",0            ← 关掉自动选择，避免档位被钉死
AT+QMBNCFG="Select","Volte_OpenMkt-Commercial-CMCC"
AT+QCFG="ims",1
AT+CFUN=1,1                       ← 重启（会断一下）
AT+QCFG="ims"                     → +QCFG: "ims",1,1    ← 🎉 VoLTE 注册成功
```

**坑**：`AT+QIM​SREG?` 在部分固件上直接 `ERROR`（不支持），要改用 `AT+QCFG="ims"` 看状态。
**坑**：`AutoSel,0` 会把档位钉死，**换卡后必须显式重选档位**，否则新卡注册不上。

### Step 5 · ⭐⭐ 最容易漏的一步：UAC 语音功能要单独启用

**UAC「设备」打开，不等于 UAC「语音功能」启用。**
官方《LTE Standard UAC Application Note》明确写着要先执行：

```
AT+QPCMV=?            → +QPCMV: (0,1),(0-2)
AT+QPCMV=1,2          → OK        ← 1=启用，2=UAC 模式
AT+QPCMV?             → +QPCMV: 1,2
```

* 参数**不保存**，模块重启后失效 → 每次拨号前重发（脚本已自动做）
* 官方 Step：通话结束 `ATH`/`AT+CHUP` 之后要执行 **`AT+QPCMV=0`** 关掉，
  否则**下一通会没有声音**（脚本已自动做）

> 这一步没做的典型现象：设备管理器里能看到音频端点，但**对方什么也听不到**。

### Step 6 · 音频格式必须匹配

模块的 UAC 是**电话带宽**：

```
8000 Hz · 16-bit · 单声道 · 每 40ms 640 字节
```

Windows 默认 48000 Hz 立体声**不匹配** → 模块拿不到音频。
实测那个端点只接受 `8000 Hz`（`16000` 会报 `Invalid sample rate`）。
自备音频请先转成 8000Hz/16bit/mono，脚本也会自动重采样。

### Step 7 · 让电脑说话（TTS）

用 Windows 自带的 SAPI（**不需要额外安装任何东西**），直接生成 8000Hz/16bit/mono 的 WAV：

```powershell
Add-Type -AssemblyName System.Speech
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
  8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToWaveFile("say8k.wav", $fmt)
$s.Speak("你好，这是一通来自电脑的测试电话")
$s.Dispose()
```

脚本的 `--say` 就是把这段（含"某些机器不接受 8000Hz 就退回默认格式"的兜底）跑一遍，
再把 WAV 推给模块。

### Step 8 · 拨号与挂断

```
ATD<号码>;        ← ⚠️ 结尾的**分号必须有**，否则被当成数据呼叫 → NO CARRIER
AT+CLCC           → 查看通话状态
AT+CHUP           → 挂断
AT+QPCMV=0        → 关闭 UAC 语音（不关的话下一通没声音）
```

### Step 9 · 电话信箱：让服务器"打"给你

```
[服务器] 往 messages.json 写一条  ──HTTP──▶  [你的电脑] phone_mailbox.py 轮询
                                                    │  有新的 → 调 ec20_uac_call.py --say
                                                    ▼
                                              拨号并念出来
```

* 每条消息有自增 `id`，电脑端用本地游标 `call-last-id.txt` 去重 → **每条只会念一次**
* 号码**不上公网**：本机 `phones.txt` 存别名表（`me=138…`），服务器只写别名 `"phone":"me"`
  * 未登记的别名会被**拒绝拨打**（自带白名单）
* `--dry-run` 只显示不拨打，**也不会推进游标**（不会"吃掉"消息）

---

## 5. 踩坑清单（现象 → 根因 → 解决）

| # | 现象 | 根因 | 解决 |
|---|---|---|---|
| 1 | 能拨通，但**对方听不到任何声音** | UAC 语音功能没启用（只打开了 UAC 设备） | 拨号前 `AT+QPCMV=1,2` |
| 2 | 第一通正常，**第二通没声音** | 上一次通话没关掉 PCM 通道 | 挂断后 `AT+QPCMV=0` |
| 3 | `AT+QIMSREG?` 返回 `ERROR` | 固件不支持该指令 | 改用 `AT+QCFG="ims"` |
| 4 | `ATD号码` 返回 `NO CARRIER` | 缺少结尾分号，被当成数据呼叫 | 必须 `ATD<号码>;` |
| 5 | 电信卡怎么都注册不上 IMS | 该档位缺 IMS 参数（CDMA/2G 已退网） | 换移动/联通卡 |
| 6 | 换了张卡后注册不上 | `AT+QMBNCFG="AutoSel",0` 把档位钉死了 | 换卡后显式 `Select` 对应档位 |
| 7 | `pip install` 报 `from versions: none` | 公司网络访问不了 PyPI（不是 Python 的问题） | 换镜像源，或用离线 wheel |
| 8 | 播放报 `initializer for ctype 'void *' must be a cdata pointer, not tuple` | **不是库的问题**：调用方把 `(数据, 采样率)` 元组整个当数据传了进去 | 解包 `data, rate = load_wav(...)`；函数内加类型兜底 |
| 9 | 脚本里中文全变乱码 | 中文 Windows 的 `cmd`／PowerShell 5.1 按 **GBK** 读脚本，而文件是 UTF-8 | `.bat`/`.ps1` 一律**纯 ASCII**；中文只放在**数据**里，运行时按 UTF-8 显式读取 |
| 10 | 浏览器访问 `403 Forbidden` | 文件权限 600，而 Web 服务以**另一个用户**运行 | 目录 755、文件 644 |
| 11 | `--dry-run` 之后消息不见了 | 游标推进写在"是否真的拨打"判断之外 | dry-run 时 `continue`，不推进游标 |
| 12 | 保存配置后仍报 `missing url` | 默认值只写进了文件、没填进内存里的配置 | 默认值在**加载时就铺好** |
| 13 | 改代码后某命令直接崩（`NameError`） | 顶部少 import；甚至误删了一整个函数 | 发布前做**未定义名静态扫描** + **每个 CLI 分支冒烟测试** + 三处一致性校验 |
| 14 | 打不同号码时，号码有泄漏风险 | 号码会写进公网可读的消息文件 | 改用**别名**：真号码只在本机 `phones.txt` 解析 |
| 15 | 脚本在同一目录找不到被调用的脚本 | 子脚本按**自己所在目录**解析相对路径 | 保持 `phone_mailbox.py` 与 `ec20_uac_call.py` 同目录 |

> 第 8 条特别值得记：当时连库源码都翻了一遍去找"参数握手 bug"，最后发现是**自己脚本的元组没解包**。
> 教训：**先证明自己的输入是对的，再怀疑第三方库。**

---

## 6. 项目结构

```
.
├── ec20_uac_call.py          # 主脚本：AT 控制 + UAC 推流 + TTS 播报
├── phone_mailbox.py          # 电话信箱客户端：轮询消息 → 自动拨号念出
├── server/put_message.py     # 服务端：往信箱里放一条消息（支持号码别名）
├── tools/                    # Windows 双击脚本与 PowerShell 包装（纯 ASCII）
│   ├── 1-list-devices.bat    #   列音频端点
│   ├── 2-test-tone.bat       #   测试音（最快验证链路）
│   ├── 8-get-call.bat        #   取一次信箱
│   └── 9-get-call-loop.bat   #   每 60 秒轮询（全自动）
├── examples/
│   ├── call-config.example.txt   # 端口 / 号码 / 信箱地址
│   └── phones.example.txt        # 号码别名表（本地白名单）
└── .gitignore                # 已经帮你忽略 phones.txt / call-config.txt / *.wav …
```

---

## 7. 安全与合规（务必遵守）

* 只用**自己**的卡、拨**自己**的号码。
* **不要**做批量外呼、不要对外提供拨号服务、不要搭建 GOIP／话务中转类设备。
  在国内，未经许可的这类用途可能触及《网络安全法》及相关法规。
* 电话信箱的文件里**不要**放金额、姓名、隐私内容；号码只写别名。
* 生产使用请自行做好访问控制：信箱地址应使用不可猜的路径或加鉴权，并及时清理消息。

---

## 8. License

MIT

# libfprint-realtek-3274-9011

让 **Microarray / Realtek MOC 指纹传感器 `3274:9011`**（"Generic Realtek USB2.0
Finger Print Bridge"）在 Linux 上可用。该传感器见于 **机械革命 无界14** 等机型。

上游 libfprint 的 `realtek` 驱动**本来就能识别**这颗传感器，但录入必然失败。
本仓库给出逆向得到的根因、让 `fprintd` 端的 `enroll` / `verify` 完整跑通的补丁，
以及推导过程所用的工具。

[English](README.md) | **简体中文**

---

> ## ⚠️ 请先读这一段
>
> ### 本项目由 AI Agent 制作
>
> 这里的所有内容 —— 协议分析、补丁、脚本、文档 —— 都由 **AI 编码 agent**
> 在人类指导下完成，方式是逆向一个 Windows 驱动包并对真实硬件做探测。
>
> **请认真对待由此带来的后果：**
>
> - **未经上游审核。** 没有任何 maintainer 审计过这个补丁。
> - **它改动的是认证组件。** `libfprint` 位于 `fprintd` → PAM 这条链路上，
>   这里的 bug 可能影响你登录的方式。
> - **只在一台设备上验证过**（`3274:9011`，一台笔记本）。
>   没测过 `3274:9003`、没测过 `3274:9008`、也没测过其他 Realtek MOC 型号。
> - **推理可能有错。** 下面的结论都有实测数据支撑，但请把它们当作
>   **待验证的论断**，而不是既成事实。
>
> ### 不要盲目照抄命令
>
> 运行前请先读 `install.sh` 和 `build.sh`。它们会把一个库装进系统库目录
> 并重启 `fprintd`。请自己留好备份、想清楚怎么回滚。
>
> ### 无关联声明
>
> 与 Realtek、Microarray、机械革命、libfprint 项目均无关联。
> 相关商标归各自所有者。

---

## 状态

在 Arch Linux 上实测（kernel 7.3.4，`libfprint 1.94.100`，`fprintd 1.94.5`），
此前也在 Fedora 44 上验证过：

| 能力 | 状态 | 证据 |
|---|---|---|
| libfprint 识别设备 | ✅ | `Device name: Realtek USB2.0 Finger Print Bridge` |
| 初始化 / 读模板表 | ✅ | 10 槽 × 35 字节，状态 `0x00` |
| **fprintd 录入** | ✅ | 8 × `enroll-stage-passed` → `enroll-completed` |
| **fprintd 比对** | ✅ | `Verify result: verify-match (done)` |
| fprintd 列表 | ✅ | `#0: right-index-finger` |
| 清空存储 | ✅ | `Clear storage successful!` |
| KDE 锁屏（Plasma 6.8） | ✅ | 显示指纹图标，按手指解锁 |
| Plasma Login Manager | ⚙️ | 需按下方配置 PAM；空密码框按 Enter 后按手指 |

```
$ fprintd-list $USER
Fingerprints for user ... on Realtek USB2.0 Finger Print Bridge (press):
 - #0: right-index-finger

$ fprintd-verify $USER
Verify result: verify-match (done)
```

录入只需要 **8 次有效按压**。旧代码会再要第 9 次，且第 9 次被拒就导致整轮录入
失败，本仓库已修复。

---

## 硬件

```
idVendor   0x3274
idProduct  0x9011
Product    "Realtek USB2.0 Finger Print Bridge"
接口       0xFF / 0x02 / 0x00（厂商自定义）
端点       0x01 OUT bulk、0x82 IN bulk（0x83/0x84 中断端点未使用）
```

这是 **Match-on-Chip（MOC）** 传感器：指纹在芯片内采集**并**比对，不导出图像。
libfprint 因此不暴露 `CAPTURE` 特性 —— 这是硬件固有限制，不是功能缺失。

---

## 根因

上游 `libfprint/drivers/realtek/realtek.c` 对所有型号统一发送：

```c
co_select_system.param[0] = 0x01;   /* 命令 05 13 */
```

**在 `3274:9011` 上，`param = 1` 会把片上模板存储区锁住。**
实机逐值测量（每次试验前都让设备处于干净状态），紧接着发
`GET_TEMPLATE (45 0e)` 请求 350 字节：

| `select_os` `param[0]` | `GET_TEMPLATE` 状态 |
|---|---|
| 不发 / `0` / `2` … `11` | `0x00` ✅ |
| **`1`** | **`0x01` ❌** |

存储区被锁后，`GET_TEMPLATE` 还会拒绝返回超过 35 字节（一条记录），
于是驱动读不到模板表、找不到空槽，以 `Status check failed` 中止。
恢复是即时的：`select_os(1)` 之后跟一条 `select_os(0)` 或 `select_os(2)` 即可。

> **关于一个流传的说法：** 你可能见过「需要 0→1→2→3 四步 `select_os` 握手」。
> 那个序列恰好**以 `3` 结尾**（即停在一个"非 1"的参数上），这才是它看起来有效的
> 原因。握手本身并非必需，**决定一切的是参数取值**。

### 本仓库修复的其他问题

1. **所有 SSM 完成回调里的悬垂 `GError`。** `fp_enroll_ssm_done`、
   `fp_verify_ssm_done`、`fp_init_ssm_done`、`fp_delete_ssm_done` 都用
   `fpi_ssm_get_error (ssm)` 覆盖了回调参数 `error`。这个 GError 会在回调返回、
   SSM 随即销毁时被释放，`fprintd` 之后读取 `error->message` 就是释放后使用，
   录入完成时直接段错误（`SIGSEGV`）。现改为使用调用方持有副本的 `error` 参数。
2. **录入多要一次采样。** 第 8 次有效采样后驱动仍重新进入采集状态，而下一次采样
   一旦被拒就以 `Enrollment failed (status 0x02)` 使整轮录入失败。现改为第 8 次
   有效采样后直接进入重复检查。
3. **USB reset 会让句柄失效。** `dev_probe()` 与 `dev_init()` 都调用了
   `g_usb_device_reset()`。该传感器在 reset 时会重新枚举，`GUsbDevice` 句柄随即
   失效，导致间歇性 `USB error ... Operation timed out`。去掉两处 reset 后探测
   与打开均稳定；初始化序列本身已能把传感器置于已知状态。
4. **轮询无限速。** 采集状态轮询会立即重入同一状态，实测约
   **每秒 8000 次 USB 事务**（11 秒产生 45MB 调试日志）。已改为 20ms 间隔。

### 以及一处设备侧清理

传感器出厂时槽 0 里已有一条预置记录，会让同一手指的录入报 `duplicate`。
它**不是后门** —— 里面只是 UID/索引而非生物特征，且 libfprint 还会用
`fp_print_equal()` 与用户已存指纹比对，因此它无法让任何人通过认证。
用 `delete_record(0xff)` 清掉即可（见 `tools/`），或直接走 `fprintd` 录入。

完整协议细节见 **[docs/PROTOCOL.md](docs/PROTOCOL.md)**。

---

## 补丁

`realtek-3274-9011.patch` —— 4 个文件，**+66 / −51**，可干净应用到上游 libfprint
**v1.94.100**（已用 `patch --dry-run` 验证）。

| 文件 | 改动 |
|---|---|
| `libfprint/drivers/realtek/realtek.c` | 新增 `3274:9011` 并带 `REALTEK_QUIRK_SELECT_OS_0`；去掉两处 reset；限制轮询频率；修复四个 SSM 完成回调；第 8 次有效采样后结束录入 |
| `libfprint/drivers/realtek/realtek.h` | `FP_RTK_CAPTURE_POLL_MS 20` |
| `data/autosuspend.hwdb` | 新增 `usb:v3274p9011*` |
| `tests/meson.build` | 用当前 meson 构建 v1.94.100 所需的一行 `foreach` 修复 |

quirk 由 `driver_data` 门控，**其他 Realtek 型号行为不变**。

---

## 构建与安装

需要：`meson`、`ninja`、`gcc`、`pkg-config`，以及 `glib2`、`gusb`、`libusb`、
`libgudev`、`openssl`、`pixman` 的开发包。缺什么 `build.sh` 会给出 Fedora /
Debian / Arch 对应的包名。

```bash
git clone https://github.com/suq-weer/libfprint-realtek-3274-9011
cd libfprint-realtek-3274-9011

./build.sh                 # 拉取上游 v1.94.100 + 打补丁 + 构建（不需要 root）
sudo ./install.sh          # 或：pkexec ./install.sh
```

`install.sh` 会：

- 把现有库备份到 `/var/backups/libfprint-2.so.2.0.0.pre-9011`；
- 安装打过补丁的 `libfprint-2.so.2.0.0`（Fedora/Arch 为 `/usr/lib64`，
  Debian/Ubuntu 为 `/usr/lib/x86_64-linux-gnu`）；
- 执行 `ldconfig`，重载 udev/hwdb，并重启 `fprintd`。

然后录入并验证：

```bash
fprintd-enroll $USER       # 按传感器 8 次
fprintd-verify $USER
fprintd-list   $USER
```

### 可选：指纹登录

补丁只修驱动。登录/解锁还需要配置 PAM：

- **KDE 锁屏** —— `kscreenlocker` 自带的 `/usr/lib/pam.d/kde-fingerprint`
  已包含 `pam_fprintd`，无需配置。
- **Plasma Login Manager** —— 先从 `/usr/lib/pam.d/` 复制一份
  `/etc/pam.d/plasmalogin`，加入 `auth sufficient pam_fprintd.so`。在空密码框
  按 **Enter** 启动扫描；登录界面目前没有指纹提示文字。
- **SDDM** —— 同样在 `/etc/pam.d/sddm` 加一行。SDDM 会要求先输入密码，
  密码被丢弃后由传感器接管。

修改 PAM 会改变登录方式。请保持一个 root 终端可用，并备份原文件。

### 卸载 / 回滚

```bash
sudo cp -a /var/backups/libfprint-2.so.2.0.0.pre-9011 \
           /usr/lib/libfprint-2.so.2.0.0     # 按实际路径调整
sudo ldconfig && sudo systemctl restart fprintd
```

或重装发行版自带的包：

```bash
sudo pacman -S libfprint              # Arch
sudo dnf reinstall libfprint          # Fedora
sudo apt install --reinstall libfprint-2-2   # Debian / Ubuntu
```

---

## 边界 —— 本项目**不做**什么

- **不附带登录管理器配置。** PAM 配置是可选手动步骤（见上）。
- **不提供图像采集。** Match-on-chip 硬件，没有图像可采。
- **`identify`（1:N）与单条 `delete` 未单独实测。**
  已实测：`enroll`、`verify`、`list`、`clear_storage`。
- **刻意未启用 `3274:9008`。** Windows INF 里它和 `9011` 同属一个驱动，但手边
  没有该硬件，故补丁不声称支持。
- **仅一台机器、一台设备。** 时序相关行为在其他主机/内核上可能不同。
- **无任何担保。** 见 LICENSE。

---

## 目录结构

| 路径 | 说明 |
|---|---|
| `realtek-3274-9011.patch` | 补丁本体 |
| `build.sh` / `install.sh` | 拉取、打补丁、构建、安装 |
| `docs/PROTOCOL.md` | 逆向得到的 USB 协议 |
| `docs/SECURITY-NOTES.md` | 预置模板与供应链相关说明 |
| `tools/rtk.py` | 协议工作台（init / 模板读写 / 任意命令） |
| `tools/rtk2.py` | 逐包抓取版，带管道重同步 |
| `tools/rtk_probe.c` | 独立 libusb 验证程序 |
| `tools/rtk_enroll.py` | 原始片上录入（需要手指） |
| `tools/ghidra_wbdi_usb.java` | 定位 USB 层所用的 Ghidra 脚本 |
| `udev/60-fingerprint-3274-9011.rules` | 给登录用户 uaccess 权限（调试便利） |

Windows 驱动包（`MicroarrayMocWbdi.dll` 等）**未包含在内** —— 那是厂商的专有
二进制，本仓库只做分析引用，不再分发。

---

## 致谢与许可

- 补丁与工具：**LGPL-2.1-or-later**，与 libfprint 一致。见 [LICENSE](LICENSE)。
- 基于 [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint)（版权归
  其贡献者），特别是其中的 `realtek` 驱动（© Realtek Corp.）—— 绝大部分工作
  由它完成。
- 参考的先期观察：「四步握手」一说来自
  [xiaomaogou66/Mechrevo-Wujie14-Unlock](https://github.com/xiaomaogou66/Mechrevo-Wujie14-Unlock)。
  本仓库修正了该解释，并额外修复了上述 bug。
- 原始分析与工具：[RChips22/libfprint-realtek-3274-9011](https://github.com/RChips22/libfprint-realtek-3274-9011)；
  本 fork 增加了 `fprintd` 端录入相关修复。

如果这个项目帮到了你，最有价值的事是**把这个 quirk 推到上游 libfprint**，
这样大家就不必再自己编译。

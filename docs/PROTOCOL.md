# Microarray / Realtek MOC 指纹传感器 (3274:9011) USB 协议

本文档记录在本机上**实测验证**过的协议内容。所有结论均有对应的实机抓包/响应数据，
未经验证的推测会明确标注。

- 目标设备：`3274:9011` "Generic Realtek USB2.0 Finger Print Bridge"
- Windows 驱动包（`Drivers/`）内部标识：`RtsMocWbdi`，PDB 路径
  `E:\SW_FP\WIN_DRIVER\rtswbdi\RtsMocBase\RtsMocWbdiBase\CBioDev.cpp`
- 属于 Realtek MOC（Match-on-Chip）家族，与 libfprint 内置 `realtek` 驱动同源，
  但固件行为有差异（见 §4）

---

## 1. USB 描述符

```
idVendor   0x3274
idProduct  0x9011
bDeviceClass 0xEF / SubClass 0x02 / Protocol 0x01（IAD）
bcdUSB     0x0201
Serial     201801010001
Product    "Realtek USB2.0 Finger Print Bridge"
Manufacturer "Generic"
```

单一接口：

| 字段 | 值 |
|---|---|
| bInterfaceNumber | 0 |
| bInterfaceClass | 0xFF (Vendor Specific) |
| bInterfaceSubClass | 0x02 |
| bInterfaceProtocol | 0x00 |

端点：

| 地址 | 方向 | 类型 | wMaxPacketSize | 用途 |
|---|---|---|---|---|
| `0x01` | OUT | Bulk | 512 | 命令 + 写入数据 |
| `0x82` | IN | Bulk | 512 | 响应数据 + 状态 |
| `0x83` | IN | Interrupt | 16 | 不被本驱动使用 |
| `0x84` | IN | Interrupt | 16 | 不被本驱动使用 |

> 注意：`0x83`/`0x84` 两个中断端点在本驱动路径中未被使用；
> 与 `3274:8012`（mafpmoc 驱动，用 EP 0x03/0x83/0x82）是**不同**的端点布局。

---

## 2. 命令格式

所有 bulk 命令为固定 **12 字节**结构（小端）：

```c
struct rtk_cmd_bulk {
  uint8_t cmd[2];       /* [0] 高 2 位 = 类型, [1] = 操作码 */
  uint8_t param[4];     /* 参数 */
  uint8_t addr[4];      /* 地址（本设备实测被固件忽略） */
  uint8_t data_len[2];  /* 数据阶段长度，小端 */
};
```

`cmd[0]` 高 2 位决定命令类型：

| 值 | 类型 | 流程 |
|---|---|---|
| `0x05` → 0 | BULK_ONLY | 发送命令 → 读 1 个状态包 |
| `0x45` → 1 | BULK_READ | 发送命令 → 读数据包(长度=data_len) → 读状态包 |
| `0x85` → 2 | BULK_WRITE | 发送命令 → 写数据 → 读状态包 |

**响应帧**（实测）：

- 数据包：长度由命令的 `data_len` 决定
- 状态包：**固定 5 字节**，`byte[0]` 为状态码

```
成功: 00 00 00 00 00
失败: 01 f7 ff ff ff      (状态码 0x01)
```

---

## 3. 初始化序列

```
1. 控制传输   bmRequestType=0xC0 (Vendor, Device→Host, Device)
             bRequest=0x07  wValue=0x000D  wIndex=0x0000  wLength=8
   ← 8 字节设备信息： 26 00 00 00 ff ff ff ff

2. bulk  05 13  param[0]=0x00   "select system"       ← 见 §4，参数必须是 0
   ← 00 00 00 00 00

3. bulk  45 0d  data_len=2      "get enroll num"
   ← 数据 0d 0a ；状态 00 00 00 00 00
      byte[1] = 0x0a = 10 → 模板槽位数
```

实际驱动还会先执行一次 USB reset 并 claim interface 0。

> 若 `select system` 发送 `param[0]=0x01`，第 3 步之后的模板表读取会失败（§4）。
> **`select system` 并非可选项，但参数取值决定模板存储区是否可访问。**

---

## 4. 关键差异：`select system` 参数

上游 libfprint `realtek` 驱动对所有型号统一发送 `param[0] = 0x01`。
在 3274:9011 上这会导致**模板存储区被锁**。

实测（每次先 USB reset，再发一条 `select_os(param)`，紧接 `GET_TEMPLATE(350)`）：

| `param[0]` | `GET_TEMPLATE` 状态 |
|---|---|
| 不发该命令 | `0x00` ✅ |
| 0 | `0x00` ✅ |
| **1** | **`0x01` ❌** |
| 2 … 11 | `0x00` ✅ |

- `select_os(1)` 之后，用 `select_os(0)` 或 `select_os(2)` 可立即恢复。
- 该影响**只限于模板表读取**：`enroll_begin` / `start_capture` / `finish_capture`
  在四种配置下响应完全一致（`data = 01 00 00 00 00`，表示无手指）。

这解释了三个现象：

1. 未打补丁的驱动录入必定停在 `Status check failed`；
2. 参考项目 xiaomaogou66/Mechrevo-Wujie14-Unlock 的「0→1→2→3 四步握手」之所以有效，
   是因为它**最后一步停在 3**（非 1），并非握手本身必需；
3. 因此正确的最小修法是**把该型号的参数改为 0**，而不是增加握手步骤。

#### 修正前的读取上限

在 `param[0]=1`（模板区被锁）状态下，`GET_TEMPLATE` 的 `data_len` 上限被压到 **35**
（正好一条记录）：`data_len ≤ 35` 返回状态 `0x00`，`≥ 36` 返回 `0x01`。
选择 system 0 后，`data_len = 350`（整表）正常返回 `0x00`。

---

## 5. 模板存储区

`GET_TEMPLATE` = `45 0e`，`data_len = 35 × 10 = 350`：

```
10 个槽位 × 35 字节 = 350 字节
```

单条记录结构（由驱动 `fp_print_from_data` / `fp_list_cb` 反推）：

| 偏移 | 长度 | 含义 |
|---|---|---|
| 0 | 1 | 有效标志（0 = 空槽） |
| 1 | 1 | 未知 |
| 2 | 1 | 手指标识（`0xFF` = SUB_FINGER_01） |
| 3 | 28 | UID（`DEFAULT_UID_LEN`） |
| 31 | 4 | 尾部 |

本机初始状态（已清空）示例——**曾有一个预置记录占用槽 0**：

```
slot 0: 01 01 f5 a8 d7 54 bb 80 55 38 cf 25 86 33 c8 2d
        9d e7 54 a5 70 1f b5 16 35 0d 74 0c e9 7a 91 38 7a c4 9a
slot 1..9: 全 0
```

### 安全说明

该记录**只是 UID/索引，不含指纹特征**；特征比对在芯片内完成，生物特征不出芯片。
libfprint 收到芯片返回的记录后，还会用 `fp_print_equal()` 与该用户已存的指纹逐字段比较：

```c
case FPI_PRINT_RAW:
  return g_variant_equal (self->data, other->data);   /* finger + UID 必须完全相等 */
```

因此预置记录**无法用于认证**（其 UID 从未写入任何用户的 fprintd 数据库）。
它的实际影响是功能性的：占用槽位，使片上匹配器在录入同指时返回 `duplicate`。

清空方式：`delete_record` = `05 0f`，`param[0] = 0xff` 清空全部。

---

## 6. 采集 / 录入流程

```
enroll_begin       05 20  param[0]=槽位号
   ↓
start_capture      05 05
   ↓
finish_capture     45 06  data_len=5     ← 轮询直到 data[0] == 0（检测到手指）
   ↓
accept_sample      45 08  data_len=9, param[0]=0x04 (=ENROLL)
   ↓  （重复 8 次：按下 → 抬起）
check_duplicate    45 10  data_len=0x22
   ↓
commit             85 21  param[0]=0xFF, data_len=32 + 32 字节 UID
   ↓
cancel_capture     05 07  param[0]=0x04
```

其它已确认操作码：

| 命令 | 含义 |
|---|---|
| `05 07` | cancel capture |
| `05 11` | update template |
| `05 13` | select system（见 §4） |
| `45 0d` | get enroll num |
| `45 0e` | get template（读模板表） |
| `45 22` | identify feature |

> `finish_capture` 的轮询在原始上游实现中是**无延迟忙等**（实测约 8000 次/秒 USB 事务）。
> 本仓库的补丁加入 20ms 间隔。

---

## 7. 状态码

驱动 `FpRtkInStatus` 枚举（`realtek.h`）：

| 值 | 含义 |
|---|---|
| 0x00 | SUCCESS |
| 0x01 | TOO_HIGH（模板区被锁时 `GET_TEMPLATE` 返回此值） |
| 0x02 … 0x0A | TOO_LOW / TOO_LEFT / TOO_RIGHT / TOO_FAST / TOO_SLOW / POOR_QUALITY / TOO_SKEWED / TOO_SHORT / MERGE_FAILURE |
| 0x0B | MATCH_FAIL |
| 0x0C | CMD_ERR |

---

## 8. 复现用工具

本仓库 `src/` 下：

| 文件 | 用途 |
|---|---|
| `rtk.py` | 高层协议工作台（init / 模板读写 / 任意命令） |
| `rtk2.py` | 逐包抓取版，带管道重同步，用于确认响应分帧 |
| `rtk_probe.c` | 独立 libusb 验证程序（复刻 realtek 驱动初始化） |
| `rtk_enroll.py` | 原始录入流程（需要手指） |

设备节点权限：`/dev/bus/usb/003/00x` 默认仅 root 可写，
`60-fingerprint-3274-9011.rules` 通过 `uaccess` 授予当前登录用户访问权限。

# Knowledge Item: pi_water_remote_runtime

## 环境概览
此知识项用于持久化存储 `pi_water` 项目在特定现场（非实验室）环境下的远程运行参数。

## 核心配置
- **Host**: `192.168.121.119` (pi-zero2)
- **User**: `feng`
- **SSH Port**: `22` (已打通免密认证)
- **SSH Key**: `ED25519`
    - 本地私钥: `$env:USERPROFILE\.ssh\id_ed25519`
    - 公钥指纹: `SHA256:FVAP1MLYQ/OOza8Lln8G2VZUWJh8s1iXpRSiCGrZvzA`
- **Remote Root**: `/home/feng/pi_water`
- **Python Path**: `/usr/bin/python3`

## 服务信息
- **Systemd Service**: `piwater.service`
- **Log Source**: `journalctl -u piwater`
- **Working Dir**: `/home/feng/pi_water`

## 常用操作模板 (PowerShell)
### 1. 快速代码同步
`Compress-Archive -Path "pi_water\*" -DestinationPath "pi_water.zip" -Force; scp pi_water.zip feng@192.168.121.119:/home/feng/; ssh feng@192.168.121.119 "unzip -o pi_water.zip -d pi_water; sudo systemctl restart piwater"`

### 2. 实时日志观测
`ssh feng@192.168.121.119 "journalctl -u piwater -f"`
## 技术逻辑沉淀
### 1. 信号防抖机制 (180s/3min)
- **原理**: 针对液位传感器的瞬时波动，引入 `stabilize_start_time`。
- **逻辑**: 信号必须连续 180s 保持有效，系统才进入 `active` 状态。
- **价值**: 避免了水泵因一过性干扰而频繁启停。

### 2. 精准采样算法 (0.75 Safety Factor)
- **目标**: 将 3 次采样动作压缩在总时长的 75% 内完成，留出 25% 的流干容错空间。
- **公式**: 休息间隔 $R = \frac{(T \times 0.75 - 30s)}{2}$。
- **应用**: 系统根据 MQTT 下发的 $T$ 值实时重算 $R$，$T$ 越长，$R$ 越长，确保时序比例恒定。

### 3. MQTT 高级交互
- **分通道日志**: `pi_water/log/{1,2,3}`，消息正文剥离元数据，实现极致压缩。
- **动态配置**: 订阅 `pi_water/config/duration/+`。
- **事件拍照**: 检测到泵启动边沿后触发 2s 延时任务。

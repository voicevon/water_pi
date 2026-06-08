# pi_water — 树莓派液位检测与水泵控制系统

## 系统架构

```
Android App  ←─ MQTT ─→  树莓派 (main.py)
                              ├─ water_gpio.py    GPIO / 液位传感器 / 水泵
                              ├─ water_camera.py  USB 摄像头（持久连接）
                              ├─ water_mqtt.py    MQTT 客户端（自动重连重订阅）
                              └─ water_config.py  系统配置
```

## 硬件接线

| 功能 | GPIO (BCM) |
|------|-----------|
| 液位传感器 通道 1 | 17 |
| 液位传感器 通道 2 | 27 |
| 液位传感器 通道 3 | 22 |
| 水泵控制 通道 1 | 5 |
| 水泵控制 通道 2 | 6 |
| 水泵控制 通道 3 | 13 |
| 状态 LED | 26 |
| 摄像头 | /dev/video0 |

- 传感器触发电平：LOW（有液体时拉低）
- 水泵启动电平：LOW（继电器低电平有效）

## 安装与部署

### 1. 克隆代码

```bash
git clone <repo_url> /home/feng/pi_water
cd /home/feng/pi_water
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置密码（重要）

```bash
cp .env.example .env
nano .env          # 填入真实 MQTT_PASSWORD
```

`.env` 文件内容示例：
```
MQTT_BROKER=voicevon.vicp.io
MQTT_PORT=1883
MQTT_USERNAME=von
MQTT_PASSWORD=your_real_password
```

### 4. 安装为 systemd 服务

```bash
cd scripts
bash install_service.sh
```

### 5. 常用运维命令

```bash
# 查看实时日志
journalctl -u piwater.service -f

# 重启服务
sudo systemctl restart piwater.service

# 停止服务
sudo systemctl stop piwater.service
```

## MQTT 主题列表

| 主题 | 方向 | 说明 |
|------|------|------|
| `pi_water/photo` | Pi → App | 照片原始数据（retain） |
| `pi_water/photo/status` | Pi → App | 拍照结果 ACK（JSON） |
| `pi_water/cmd/photo` | App → Pi | 触发拍照指令 |
| `pi_water/system/info` | Pi → App | 三行文本：时间/启动时间/运行时长 |
| `pi_water/system/status` | Pi → App | JSON 系统状态（每 30s 更新） |
| `pi_water/log/1` `2` `3` | Pi → App | 各通道实时操作日志 |
| `pi_water/config/duration/1` `2` `3` | App → Pi | 远程设置通道采样总时长（分钟） |
| `pi_water/config/pump_time/1` `2` `3` | App → Pi | 远程设置泵工作时间（秒） |

### `pi_water/system/status` JSON 结构示例

```json
{
  "timestamp": "2026-06-08T10:00:00",
  "uptime_seconds": 3600,
  "mqtt_connected": true,
  "camera_available": true,
  "channels": [
    { "id": 1, "active": true,  "stage": 2, "pump_on": false, "on_count": 2, "detected": true },
    { "id": 2, "active": false, "stage": -1, "pump_on": false, "on_count": 0, "detected": false },
    { "id": 3, "active": false, "stage": -1, "pump_on": false, "on_count": 0, "detected": false }
  ]
}
```

## 采样逻辑说明

每通道采样流程：
1. **稳定期**：液位传感器持续触发满 3 分钟后正式开始
2. **采样序列**：3 次泵工作 + 2 次休息，在 `预期总时长 × 75%` 的时间窗口内完成
3. **抽空**：信号消失满 3 分钟后触发第 4 次抽空（清空管道）
4. **复位**：抽空完成且无信号后重置

远程配置值域限制：
- 采样时长：10 ～ 480 分钟
- 泵工作时间：5 ～ 120 秒

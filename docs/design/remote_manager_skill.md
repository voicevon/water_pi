# Skill: Remote Project Manager

## 描述
此技能提供了一套标准化的流程，用于在本地 Windows 环境与远程 Linux (Raspberry Pi) 环境之间进行高效的协同开发。它依赖于 SSH 免密连接和配套的环境 KI。

## 核心能力
### 1. `Sync-Project(local_dir, remote_host, remote_dir)`
- **步骤**: 本地打包 -> SCP 传输 -> 远程覆盖解压。
- **校验**: 在执行前检查 `target_dir` 是否存在，防止误覆盖。

### 2. `Manage-Service(remote_host, service_name, action)`
- **动作**: `start`, `stop`, `restart`, `status`, `enable`。
- **实现**: 调用远程 `systemctl` 指令。

### 3. `Capture-Logs(remote_host, service_name)`
- **实现**: `ssh -t` 开启交互式 TTY 并执行 `journalctl -f`。

### 4. Python MQTT 工业模式 (MQTT-Pattern)
- **动态订阅**: 使用 `+` 通配符批量订阅配置主题（如 `.../config/duration/+`）。
- **注册机制**: 通过 `set_callback` 实现解耦，将 MQTT 消息准确路由至具体通道实例（如 `SamplingChannel.update_config`）。
- **消息压缩**: 日志主题分层（Log-Channeling），剔除消息体中的重复元数据以节约带宽。

## 最佳实践
- **持久化上下文**: 在切换任务或重新开启会话时，务必先读取项目的 `remote_runtime` KI。
- **原子化更新**: 始终先执行代码同步，再执行服务重启。
- **安全性锚点**: 在定时逻辑中引入 `safety_factor` (如 0.75)，防止采样时间线超出物理液量极限。

#!/usr/bin/env python3
"""
树莓派液位检测与水泵控制系统 - 主程序
功能：三通道液位检测、水泵控制、照片拍摄与 MQTT 传输

修复说明（相对上一版本）：
  BUG-02  PhotoScheduler.photo_count 加线程锁
  BUG-03  相机持久化，拍照无冷启动延迟（见 water_camera.py）
  BUG-04  MQTT 重连后自动重订阅（见 water_mqtt.py）
  BUG-05  远程配置值域校验，防止非法值导致泵失控
  DESIGN-02 删除危险的 __del__，改用 atexit 注册清理
  DESIGN-04 实现 safety_factor（前 75% 时间窗口内完成采样）
  DESIGN-05 PhotoScheduler 防抖，多通道并发只触发一次拍照
  MISSING-02 实现 pi_water/cmd/photo 指令处理 + pi_water/photo/status ACK
  MISSING-04 monitor_thread 每 30s 发布 JSON 状态到 pi_water/system/status
  P2  reset() 补全缺失字段；删除废弃 actual_duration 字段；简化 _boot_self_check
"""

import json
import time
import logging
import logging.handlers
import sys
import os
import atexit
from datetime import datetime
from threading import Thread, Event, Timer, Lock
import fcntl

from water_config import get_default_config, SystemConfig
from water_camera import CameraManager
from water_mqtt import MQTTManager
from water_gpio import WaterController


class PhotoScheduler:
    """事件驱动拍照器类
    修复：
      - 防抖：相同时间窗口内多次触发只执行一次（DESIGN-05）
      - 线程安全：photo_count 加锁保护（BUG-02）
      - 拍照完成后向 status_topic 发布结果 ACK（MISSING-02）
    """

    def __init__(self, camera_manager, mqtt_manager,
                 topic="pi_water/photo",
                 status_topic="pi_water/photo/status"):
        self.camera_manager = camera_manager
        self.mqtt_manager = mqtt_manager
        self.topic = topic
        self.status_topic = status_topic
        self.logger = logging.getLogger(self.__class__.__name__)
        self.photo_count = 0
        self._pending = False    # 防抖标志：已有待执行任务时跳过重复触发
        self._lock = Lock()      # 保护 photo_count 的线程锁

    def trigger_delayed_photo(self, delay=2.0):
        """延迟触发单次拍照（含防抖：有挂起任务时直接返回）"""
        if self._pending:
            self.logger.info("已有待执行的拍照任务，跳过重复触发")
            return
        self._pending = True
        self.logger.info(f"开启 {delay}s 延时拍照定时器...")
        Timer(delay, self._take_photo).start()

    def stop(self):
        """停止调度器（预留接口）"""
        self.logger.info("PhotoScheduler 已停止")

    def _take_photo(self):
        """执行拍照、发布照片原始数据及 ACK 状态（单次）"""
        success = False
        error_msg = ""
        try:
            if not self.camera_manager.is_available():
                error_msg = "摄像头不可用"
                self.logger.warning(f"拍照取消：{error_msg}")
                return

            photo_path = self.camera_manager.capture_photo()
            if photo_path and os.path.exists(photo_path):
                with self._lock:
                    self.photo_count += 1
                    count = self.photo_count

                with open(photo_path, 'rb') as f:
                    photo_data = f.read()

                if self.mqtt_manager.publish_message(self.topic, photo_data, qos=0, retain=True):
                    self.logger.info(f"事件驱动照片 #{count} 已发送: {photo_path}")
                    success = True
                else:
                    error_msg = "MQTT 发送失败"
                    self.logger.error(f"事件驱动照片 #{count} 发送失败")
            else:
                error_msg = "拍照物理执行失败"
                self.logger.error(error_msg)

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"拍照任务异常: {e}")
        finally:
            self._pending = False
            # 向 Android 端发布拍照结果 ACK
            ack = {"success": True} if success else {"success": False, "error": error_msg}
            self.mqtt_manager.publish_message(
                self.status_topic,
                json.dumps(ack, ensure_ascii=False),
                qos=0,
                retain=False
            )


class SamplingChannel:
    """单个采样通道的状态管理"""

    def __init__(self, channel_id, expected_duration, pump_work_time=10,
                 safety_factor=0.75, stabilization_time=180,
                 log_callback=None, log_topic=None):
        self.channel_id = channel_id
        self.expected_duration = expected_duration
        self.pump_work_time = pump_work_time
        self.safety_factor = safety_factor          # 现已在 _calculate_stages 中使用
        self.stabilization_time = stabilization_time
        self.log_callback = log_callback
        self.log_topic = log_topic

        self.on_count = 0
        self.off_count = 0

        # 计算动态采样序列
        self._calculate_stages()

        self.current_stage = -1       # -1: 空闲/稳定中, 0-4: 对应 stage_times, 6: 抽空, 999: 终结
        self.next_action_time = 0
        self.active = False
        self.is_detected = False
        self.stabilize_start_time = 0
        self.start_time = 0
        self.last_pump_state = False
        self.last_on_time = 0

        # 抽空逻辑变量
        self.signal_lost_time = 0        # 信号消失的开始时间
        self.evacuation_triggered = False  # 是否已触发第四次抽空
        self.evacuation_done = False       # 第四次抽空是否已完成

        self.logger = logging.getLogger(f"{self.__class__.__name__}_{channel_id}")

    def _calculate_stages(self):
        """基于预期总时长和安全系数更新采样时间序列。

        设计目标：所有采样动作在 expected_duration × safety_factor 的时间窗口内完成。
        该窗口从液位稳定触发后算起，扣除稳定等待时间及 3 次泵工作时间后，
        剩余时间均分为 2 次休息间隔。
        """
        available_time = self.expected_duration * self.safety_factor - self.stabilization_time
        rest_time = (available_time - self.pump_work_time * 3) / 2
        if rest_time < 0:
            rest_time = 0
        self.stage_times = [
            self.pump_work_time, rest_time,
            self.pump_work_time, rest_time,
            self.pump_work_time
        ]

    def update_expected_duration(self, new_duration):
        """动态更新预期时长并重算阶段时间"""
        self.expected_duration = new_duration
        self._calculate_stages()
        duration_min = new_duration / 60.0
        msg = f"总时更新:{int(duration_min)}分"
        self.logger.info(f"通道 {self.channel_id + 1} 总时长更新: {int(duration_min)}分")
        self._send_remote_log(msg)

    def update_pump_work_time(self, new_pump_time):
        """动态更新泵启动时长并重算阶段时间"""
        self.pump_work_time = new_pump_time
        self._calculate_stages()
        msg = f"泵时更新:{int(new_pump_time)}秒"
        self.logger.info(f"通道 {self.channel_id + 1} 泵时更新: {int(new_pump_time)}秒")
        self._send_remote_log(msg)

    def _send_remote_log(self, message):
        """发送远程文本日志（严格适配 3行 × 7汉字显示）"""
        if self.log_callback and self.log_topic:
            timestamp = datetime.now().strftime('%m月%d日 %H:%M')
            channel_label = f"通道{self.channel_id + 1}:"
            full_msg = f"{timestamp}\n{channel_label}\n{message}"
            self.log_callback(self.log_topic, full_msg)

    def reset(self):
        """重置通道到初始状态（所有运行时字段全量清零）"""
        self.current_stage = -1
        self.next_action_time = 0
        self.active = False
        self.is_detected = False
        self.stabilize_start_time = 0
        self.on_count = 0
        self.off_count = 0
        self.start_time = 0           # 补全：之前 reset 未清零
        self.last_pump_state = False  # 补全：之前 reset 未清零
        self.last_on_time = 0
        self.signal_lost_time = 0
        self.evacuation_triggered = False
        self.evacuation_done = False

    def process_sensor(self, detected):
        """处理传感器实时状态，包含 180 秒信号消失后的第 4 次抽空逻辑"""
        now = time.time()
        logs_to_send = []

        # ── 1. 信号探测逻辑 ──
        if detected:
            self.signal_lost_time = 0  # 重置信号消失计时
            if not self.is_detected:
                self.is_detected = True
                self.stabilize_start_time = now
                msg = "检测触发:待稳"
                self.logger.info(msg)
                logs_to_send.append(msg)
            elif not self.active:
                if now - self.stabilize_start_time >= self.stabilization_time:
                    self.active = True
                    self.start_time = now
                    self.current_stage = 0
                    self.next_action_time = now + self.stage_times[0]
                    msg = "稳期通:启采样"
                    self.logger.info(msg)
                    logs_to_send.append(msg)
        else:
            if self.is_detected:
                self.is_detected = False
                msg = "信号丢:等抽空" if self.active else "信号丢:计重置"
                self.logger.info(msg)
                logs_to_send.append(msg)

            # 核心：信号消失满 180 秒后触发第 4 次抽空
            if self.active and not self.evacuation_triggered:
                if self.signal_lost_time == 0:
                    self.signal_lost_time = now
                elif now - self.signal_lost_time >= 180:
                    self.evacuation_triggered = True
                    msg = "失踪3分:抽空"
                    self.logger.info(msg)
                    logs_to_send.append(msg)
                    if self.current_stage < 6:
                        self.current_stage = 6
                        self.next_action_time = now + self.pump_work_time

        # ── 2. 采样序列逻辑（含第 4 次抽空）──
        if self.active:
            if self.current_stage == 6:  # 特殊的第 4 次抽空阶段
                if now >= self.next_action_time:
                    self.evacuation_done = True
                    msg = "抽空完:管道空"
                    self.logger.info(msg)
                    logs_to_send.append(msg)
                    self.current_stage = 999  # 终结
            elif now >= self.next_action_time:
                if self.current_stage < len(self.stage_times):
                    self.current_stage += 1
                    if self.current_stage >= len(self.stage_times):
                        if not self.evacuation_triggered:
                            msg = "采样完:等号丢"
                            self.logger.info(msg)
                            logs_to_send.append(msg)
                        else:
                            self.current_stage = 999
                    else:
                        self.next_action_time = now + self.stage_times[self.current_stage]

        # ── 3. 决定水泵电平 ──
        # 抽空阶段(6) 或采样工作段(0, 2, 4) 时泵运行
        needs_pump = self.active and (self.current_stage == 6 or self.current_stage in [0, 2, 4])
        if needs_pump != self.last_pump_state:
            self.last_pump_state = needs_pump
            if needs_pump:
                self.last_on_time = now
                self.on_count += 1
                logs_to_send.append(f"泵启:第{self.on_count}次")
            else:
                self.off_count += 1
                p_dur = int(now - self.last_on_time) if self.last_on_time > 0 else 0
                logs_to_send.append(f"关:{self.off_count}次第{p_dur}秒")

        # ── 4. 同 Tick 消息合并发布 ──
        if logs_to_send:
            self._send_remote_log(" | ".join(logs_to_send))

        # ── 5. 任务终结与复位 ──
        if (self.current_stage == 999 or self.evacuation_done) and not detected:
            msg = "任务终:已复位"
            self.logger.info(msg)
            self._send_remote_log(msg)
            self.reset()

        return needs_pump


class WaterControlSystem:
    """水控制系统主类"""

    def __init__(self, config=None):
        self.config = config or get_default_config()
        self.logger = self._setup_logging()
        self._cleaned_up = False  # 幂等清理标志

        self.camera_manager = CameraManager()
        self.mqtt_manager = MQTTManager(
            self.config['mqtt_broker'],
            self.config['mqtt_port'],
            self.config['mqtt_username'],
            self.config['mqtt_password']
        )
        self.water_controller = WaterController(
            self.config['liquid_level_pins'],
            self.config['pump_pins'],
            self.config.get('led_pin'),
            self.config.get('pump_on', 0),
            self.config.get('pump_off', 1),
            self.config.get('sensor_trigger_level', 0)
        )
        self.photo_scheduler = PhotoScheduler(
            self.camera_manager,
            self.mqtt_manager,
            topic=self.config['photo_topic'],
            status_topic=self.config.get('photo_status_topic', 'pi_water/photo/status')
        )

        # 初始化通道状态（适配高级定时逻辑与分通道日志）
        self.channels = []
        log_prefix = self.config.get('log_topic_prefix', 'pi_water/log')
        for i in range(len(self.config['liquid_level_pins'])):
            expected_dur = (
                self.config['channel_expected_durations'][i]
                if i < len(self.config['channel_expected_durations']) else 3600
            )
            self.channels.append(SamplingChannel(
                i,
                expected_dur,
                self.config.get('pump_work_time', 10),
                self.config.get('safety_factor', 0.75),
                self.config.get('stabilization_time', 180),
                log_callback=self.mqtt_manager.publish_message,
                log_topic=f"{log_prefix}/{i + 1}"
            ))

        # 配置 MQTT 订阅回调
        self.mqtt_manager.set_callback(self._on_mqtt_message)

        duration_topic = self.config.get('duration_config_topic', 'pi_water/config/duration/+')
        self.mqtt_manager.subscribe(duration_topic)

        pump_time_topic = self.config.get('pump_time_config_topic', 'pi_water/config/pump_time/+')
        self.mqtt_manager.subscribe(pump_time_topic)

        # 订阅拍照指令主题（Android 端下发）
        photo_cmd_topic = self.config.get('photo_cmd_topic', 'pi_water/cmd/photo')
        self.mqtt_manager.subscribe(photo_cmd_topic)

        self.running = False
        self.monitor_thread = None
        self.stop_event = Event()
        self.start_time = time.time()
        self.start_at_str = datetime.now().strftime('%m月%d日 %H:%M')

        # 注册退出清理（替代危险的 __del__）
        atexit.register(self.cleanup)

        # 初始发布启动时间信息
        self._publish_info_msg()

        self.logger.info("水控制系统初始化完成 (6阶段采样 + 远程动态配置 + 拍照指令模式)")

    def _on_mqtt_message(self, topic, payload):
        """处理来自 MQTT 的消息（动态配置 + 拍照指令）"""
        try:
            # ── 拍照指令 pi_water/cmd/photo ──
            photo_cmd_topic = self.config.get('photo_cmd_topic', 'pi_water/cmd/photo')
            if topic == photo_cmd_topic:
                self.logger.info("收到远程拍照指令，立即触发拍照")
                self.photo_scheduler.trigger_delayed_photo(delay=0)
                return

            # ── 采样时长配置 pi_water/config/duration/X ──
            if "config/duration/" in topic:
                channel_str = topic.split('/')[-1]
                if channel_str.isdigit():
                    idx = int(channel_str) - 1
                    if 0 <= idx < len(self.channels):
                        duration_min = float(payload)
                        min_d = self.config.get('min_duration_min', 10)
                        max_d = self.config.get('max_duration_min', 480)
                        if not (min_d <= duration_min <= max_d):
                            self.logger.warning(
                                f"时长值 {duration_min} 超出合理范围 [{min_d}, {max_d}] 分钟，已忽略"
                            )
                            return
                        new_duration_sec = duration_min * 60
                        self.channels[idx].update_expected_duration(new_duration_sec)
                        self.logger.info(
                            f"远程指令：更新通道 {idx + 1} 时长至 {duration_min}分钟 ({new_duration_sec}秒)"
                        )

            # ── 泵启动时间配置 pi_water/config/pump_time/X ──
            elif "config/pump_time/" in topic:
                channel_str = topic.split('/')[-1]
                if channel_str.isdigit():
                    idx = int(channel_str) - 1
                    if 0 <= idx < len(self.channels):
                        new_pump_time = float(payload)
                        min_p = self.config.get('min_pump_sec', 5)
                        max_p = self.config.get('max_pump_sec', 120)
                        if not (min_p <= new_pump_time <= max_p):
                            self.logger.warning(
                                f"泵时长 {new_pump_time} 超出合理范围 [{min_p}, {max_p}] 秒，已忽略"
                            )
                            return
                        self.channels[idx].update_pump_work_time(new_pump_time)
                        self.logger.info(
                            f"远程指令：更新通道 {idx + 1} 泵启动时长至 {new_pump_time}秒"
                        )

        except ValueError:
            self.logger.error(f"配置消息格式错误（非数值）: topic={topic}, payload={payload}")
        except Exception as e:
            self.logger.error(f"处理远程配置消息失败: {e}")

    def _boot_self_check(self):
        """开机自检：启动后 60 秒拍摄一张照片（复用 PhotoScheduler，避免代码重复）"""
        self.logger.info("开机自检定时器已设置：60 秒后将拍摄自检照片")
        self.photo_scheduler.trigger_delayed_photo(delay=60.0)

    def _setup_logging(self):
        file_handler = logging.handlers.RotatingFileHandler(
            self.config['log_file'],
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8'
        )
        console_handler = logging.StreamHandler(sys.stdout)

        logging.basicConfig(
            level=self.config['log_level'],
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[file_handler, console_handler]
        )
        return logging.getLogger(self.__class__.__name__)

    def monitor_loop(self):
        """主监控循环"""
        self.logger.info("开始监控循环 - 6阶段采样与上升沿触发拍照")

        led_state = False
        loop_counter = 0
        last_pump_states = [False] * len(self.channels)
        last_info_time = 0
        last_status_time = 0

        # 开机自检：启动后 60 秒拍摄一张照片
        self._boot_self_check()

        while not self.stop_event.is_set():
            try:
                # 每 5 秒切换一次指示灯状态（对应 1s 循环）
                loop_counter += 1
                if loop_counter >= 5:
                    led_state = not led_state
                    self.water_controller.control_led(led_state)
                    loop_counter = 0

                for i, channel in enumerate(self.channels):
                    is_detected = self.water_controller.read_liquid_level(i)
                    needs_pump = channel.process_sensor(is_detected)

                    # 拍照逻辑：捕获上升沿（水泵开启瞬间触发延时拍照）
                    if needs_pump and not last_pump_states[i]:
                        self.logger.info(f"检测到 #{i + 1} 通道启动，触发 2s 延时拍照")
                        self.photo_scheduler.trigger_delayed_photo(delay=2.0)

                    last_pump_states[i] = needs_pump
                    self.water_controller.control_pump(i, needs_pump)

                now = time.time()

                # 每 30 秒发布一次 JSON 系统状态（供 Android 端解析）
                if now - last_status_time >= 30:
                    self._publish_status_msg()
                    last_status_time = now

                # 每 60 秒发布一次文本诊断信息（降低频率，腾出带宽给实时警报）
                if now - last_info_time >= 60:
                    self._publish_info_msg()
                    last_info_time = now

                time.sleep(1)

            except Exception as e:
                self.logger.error(f"监控循环异常: {e}")
                time.sleep(5)

    def _publish_info_msg(self):
        """发布包含 Clock、StartAt、Uptime 的三行文本诊断信息"""
        try:
            uptime_seconds = int(time.time() - self.start_time)
            days, rem = divmod(uptime_seconds, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, _ = divmod(rem, 60)

            info_msg = (
                f"{datetime.now().strftime('%m月%d日 %H:%M')}\n"
                f"{self.start_at_str}\n"
                f"{days}天 {hours}小时 {minutes}分钟"
            )
            self.mqtt_manager.publish_message(self.config['info_topic'], info_msg)
        except Exception as e:
            self.logger.error(f"发布诊断信息异常: {e}")

    def _publish_status_msg(self):
        """发布 JSON 格式系统状态到 pi_water/system/status（供 Android 端解析）"""
        try:
            status = {
                "timestamp": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                "uptime_seconds": int(time.time() - self.start_time),
                "mqtt_connected": self.mqtt_manager.is_connected(),
                "camera_available": self.camera_manager.is_available(),
                "channels": [
                    {
                        "id": i + 1,
                        "active": ch.active,
                        "stage": ch.current_stage,
                        "pump_on": ch.last_pump_state,
                        "on_count": ch.on_count,
                        "detected": ch.is_detected,
                    }
                    for i, ch in enumerate(self.channels)
                ],
            }
            self.mqtt_manager.publish_message(
                self.config['status_topic'],
                status,   # MQTTManager.publish_message 自动将 dict 序列化为 JSON
                qos=0,
                retain=True
            )
        except Exception as e:
            self.logger.error(f"发布系统状态异常: {e}")

    def start(self):
        """启动监控"""
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        self.monitor_thread = Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.logger.info("系统已启动")

    def stop(self):
        """停止监控"""
        if not self.running:
            return
        self.running = False
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10)
        self.photo_scheduler.stop()
        self.water_controller.stop_all_pumps()
        self.logger.info("系统已停止")

    def cleanup(self):
        """清理资源（幂等，可安全多次调用）"""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self.stop()
        self.mqtt_manager.cleanup()
        self.camera_manager.cleanup()
        self.water_controller.cleanup()
        self.logger.info("资源已完成清理")


def check_single_instance(pid_file="/tmp/piwater.pid"):
    """使用文件锁确保只有一个实例运行"""
    f = open(pid_file, 'w')
    try:
        fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.write(str(os.getpid()))
        f.flush()
        return f
    except IOError:
        f.close()
        return None


def main():
    """主函数"""
    pid_f = check_single_instance()
    if not pid_f:
        print("\n[错误] 另一个程序实例已经在运行中 (PID 文件被锁定)。")
        print("请检查是否有遗留进程: pgrep -af python3")
        sys.exit(1)

    system = None
    try:
        system = WaterControlSystem()
        system.start()
        print("系统已启动，按 Ctrl+C 停止...")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n用户中断程序")
    except Exception as e:
        print(f"系统运行异常: {e}")
    finally:
        if system:
            system.cleanup()
        if pid_f:
            pid_f.close()
            try:
                os.remove("/tmp/piwater.pid")
            except OSError:
                pass


if __name__ == "__main__":
    main()
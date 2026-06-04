#!/usr/bin/env python3
"""
树莓派液位检测与水泵控制系统 - 主程序
功能：三通道液位检测、水泵控制、照片拍摄与MQTT传输
"""

import json
import time
import logging
import logging.handlers
import sys
import os
from datetime import datetime
from threading import Thread, Event, Timer
import fcntl

# 导入自定义模块
from water_config import get_default_config, SystemConfig
from water_camera import CameraManager
from water_mqtt import MQTTManager
from water_gpio import WaterController


class PhotoScheduler:
    """事件驱动拍照器类"""
    
    def __init__(self, camera_manager, mqtt_manager, topic="pi_water/photo"):
        self.camera_manager = camera_manager
        self.mqtt_manager = mqtt_manager
        self.topic = topic
        self.logger = logging.getLogger(self.__class__.__name__)
        self.photo_count = 0
    
    def trigger_delayed_photo(self, delay=2.0):
        """延迟触发单次拍照"""
        self.logger.info(f"开启 {delay}s 延时拍照定时器...")
        Timer(delay, self._take_photo).start()
    
    def stop(self):
        """停止调度器（当前无持久资源，预留接口）"""
        self.logger.info("PhotoScheduler 已停止")

    def _take_photo(self):
        """执行拍照并发送MQTT消息 (单次)"""
        try:
            if not self.camera_manager.is_available():
                self.logger.warning("摄像头不可用，取消拍照")
                return
            
            photo_path = self.camera_manager.capture_photo()
            if photo_path and os.path.exists(photo_path):
                self.photo_count += 1
                
                with open(photo_path, 'rb') as f:
                    photo_data = f.read()
                
                if self.mqtt_manager.publish_message(self.topic, photo_data, qos=0, retain=True):
                    self.logger.info(f"事件驱动照片 #{self.photo_count} 已发送: {photo_path}")
                else:
                    self.logger.error(f"事件驱动照片 #{self.photo_count} 发送失败")
            else:
                self.logger.error("拍照物理执行失败")
                
        except Exception as e:
            self.logger.error(f"拍照任务异常: {e}")


class SamplingChannel:
    """单个采样通道的状态管理"""
    def __init__(self, channel_id, expected_duration, pump_work_time=10, safety_factor=0.75, stabilization_time=180, log_callback=None, log_topic=None):
        self.channel_id = channel_id
        self.expected_duration = expected_duration
        self.pump_work_time = pump_work_time
        self.safety_factor = safety_factor
        self.stabilization_time = stabilization_time
        self.log_callback = log_callback
        self.log_topic = log_topic
        
        self.on_count = 0
        self.off_count = 0
        
        # 计算动态采样序列
        self._calculate_stages()
        
        self.current_stage = -1  # -1: 空闲/稳定中, 0-4: 对应 stage_times
        self.next_action_time = 0
        self.active = False
        self.is_detected = False
        self.stabilize_start_time = 0
        self.start_time = 0
        self.actual_duration = 0
        self.last_pump_state = False
        self.last_on_time = 0
        
        # --- 新增抽空逻辑变量 ---
        self.signal_lost_time = 0      # 信号消失的开始时间
        self.evacuation_triggered = False  # 是否已触发第四次抽空
        self.evacuation_done = False       # 第四次抽空是否已完成
        
        self.logger = logging.getLogger(f"{self.__class__.__name__}_{channel_id}")
    
    def _calculate_stages(self):
        """基于当前预期总时长更新采样时间序列。
        公式：停止时间 = (总时长 - 180) * 0.25
        """
        rest_time = (self.expected_duration - 180) * 0.25
        if rest_time < 0: rest_time = 0
        self.stage_times = [self.pump_work_time, rest_time, self.pump_work_time, rest_time, self.pump_work_time]

    def update_expected_duration(self, new_duration):
        """动态更新预期时长并重算阶段时间"""
        self.expected_duration = new_duration
        self._calculate_stages()
        duration_min = new_duration / 60.0
        # 满足 7 汉字限制
        msg = f"总时更新:{int(duration_min)}分"
        self.logger.info(f"通道 {self.channel_id+1} 总时长更新: {int(duration_min)}分")
        self._send_remote_log(msg)

    def update_pump_work_time(self, new_pump_time):
        """动态更新泵启动时长并重算阶段时间"""
        self.pump_work_time = new_pump_time
        self._calculate_stages()
        # 满足 7 汉字限制
        msg = f"泵时更新:{int(new_pump_time)}秒"
        self.logger.info(f"通道 {self.channel_id+1} 泵时更新: {int(new_pump_time)}秒")
        self._send_remote_log(msg)

    def _send_remote_log(self, message):
        """发送远程文本日志 (严格适配 3行 x 7汉字 显示)"""
        if self.log_callback and self.log_topic:
            # 第一行: 时间 (03月06日 18:51)
            timestamp = datetime.now().strftime('%m月%d日 %H:%M')
            # 第二行: 通道号
            channel_label = f"通道{self.channel_id+1}:"
            # 第三行: 动作内容 (需外部控制在 7 汉字内)
            full_msg = f"{timestamp}\n{channel_label}\n{message}"
            self.log_callback(self.log_topic, full_msg)
    

    def reset(self):
        """重置通道到初始状态"""
        self.current_stage = -1
        self.next_action_time = 0
        self.active = False
        self.is_detected = False
        self.stabilize_start_time = 0
        self.on_count = 0
        self.off_count = 0
        self.last_on_time = 0
        self.signal_lost_time = 0
        self.evacuation_triggered = False
        self.evacuation_done = False
    def process_sensor(self, detected):
        """处理传感器实时状态，包含 120秒信号消失后的第 4 次抽空逻辑"""
        now = time.time()
        logs_to_send = []
        
        # 1. 信号探测逻辑
        if detected:
            self.signal_lost_time = 0 # 重置信号消失计时
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
                if not self.active:
                    msg = "信号丢:计重置"
                    self.logger.info(msg)
                    logs_to_send.append(msg)
                else:
                    msg = "信号丢:等抽空"
                    self.logger.info(msg)
                    logs_to_send.append(msg)
            
            # --- 核心新增：信号消失满 180 秒(3分钟)后的抽空触发 ---
            if self.active and not self.evacuation_triggered:
                if self.signal_lost_time == 0:
                    self.signal_lost_time = now
                elif now - self.signal_lost_time >= 180:
                    self.evacuation_triggered = True
                    msg = "失踪3分:抽空"
                    self.logger.info(msg)
                    logs_to_send.append(msg)
                    # 强行切入到第 4 次启动
                    if self.current_stage < 6: 
                        self.current_stage = 6 
                        self.next_action_time = now + self.pump_work_time

        # 2. 采样序列逻辑 (包括第 4 次抽空)
        if self.active:
            if self.current_stage == 6: # 特殊的第 4 次抽空阶段
                if now >= self.next_action_time:
                    self.evacuation_done = True
                    msg = "抽空完:管道空"
                    self.logger.info(msg)
                    logs_to_send.append(msg)
                    self.current_stage = 999 # 终结
            elif now >= self.next_action_time:
                if self.current_stage < len(self.stage_times):
                    self.current_stage += 1
                    if self.current_stage >= len(self.stage_times):
                        if not self.evacuation_triggered:
                            msg = "采样完:等号丢"
                            self.logger.info(msg)
                            logs_to_send.append(msg)
                            # 保持 active, 让其在信号消失后的逻辑中触发第 4 次
                        else:
                            # 如果此时已经触发了抽空逻辑，本应不走这里，但做个保险
                            self.current_stage = 999
                    else:
                        self.next_action_time = now + self.stage_times[self.current_stage]

        # 3. 决定水泵电平
        # 抽空阶段(6) 或者是 采样阶段中的工作段(0, 2, 4)
        needs_pump = (self.active and (self.current_stage == 6 or self.current_stage in [0, 2, 4]))
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
            
        # 4. 同 Tick 消息合并发布
        if logs_to_send:
            combined_msg = " | ".join(logs_to_send)
            self._send_remote_log(combined_msg)

        # 5. 最终任务终结与复位
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
            topic=self.config['photo_topic']
        )
        
        # 初始化通道状态 (适配高级定时逻辑与分通道日志)
        self.channels = []
        log_prefix = self.config.get('log_topic_prefix', 'pi_water/log')
        for i in range(len(self.config['liquid_level_pins'])):
            expected_dur = self.config['channel_expected_durations'][i] if i < len(self.config['channel_expected_durations']) else 3600
            pump_time = self.config.get('pump_work_time', 10)
            self.channels.append(SamplingChannel(
                i, 
                expected_dur, 
                pump_time,
                self.config.get('safety_factor', 0.75),
                self.config.get('stabilization_time', 180),
                log_callback= self.mqtt_manager.publish_message,
                log_topic=f"{log_prefix}/{i+1}"
            ))
        
        # 配置MQTT订阅回调
        self.mqtt_manager.set_callback(self._on_mqtt_message)
        duration_topic = self.config.get('duration_config_topic', 'pi_water/config/duration/+')
        self.mqtt_manager.subscribe(duration_topic)
        
        pump_time_topic = self.config.get('pump_time_config_topic', 'pi_water/config/pump_time/+')
        self.mqtt_manager.subscribe(pump_time_topic)
        
        self.running = False
        self.monitor_thread = None
        self.stop_event = Event()
        self.start_time = time.time()
        self.start_at_str = datetime.now().strftime('%m月%d日 %H:%M')
        
        # 初始异步发布启动时间信息 (三行合一)
        self._publish_info_msg()
        
        self.logger.info("水控制系统初始化完成 (6阶段采样 + 远程动态配置模式)")
    
    def _on_mqtt_message(self, topic, payload):
        """处理来自MQTT的消息 (动态配置)"""
        try:
            # 识别是否为时长配置主题: pi_water/config/duration/X
            if "config/duration/" in topic:
                channel_str = topic.split('/')[-1]
                if channel_str.isdigit():
                    idx = int(channel_str) - 1
                    if 0 <= idx < len(self.channels):
                        # 用户下发数值即为分钟，内部逻辑按秒处理
                        duration_min = float(payload)
                        new_duration_sec = duration_min * 60
                        self.channels[idx].update_expected_duration(new_duration_sec)
                        self.logger.info(f"远程指令：更新通道 {idx+1} 时长至 {duration_min}分钟 ({new_duration_sec}秒)")
            
            # 识别是否为泵启动时间配置主题: pi_water/config/pump_time/X
            elif "config/pump_time/" in topic:
                channel_str = topic.split('/')[-1]
                if channel_str.isdigit():
                    idx = int(channel_str) - 1
                    if 0 <= idx < len(self.channels):
                        # 用户下发数值即为秒
                        new_pump_time = float(payload)
                        self.channels[idx].update_pump_work_time(new_pump_time)
                        self.logger.info(f"远程指令：更新通道 {idx+1} 泵启动时长至 {new_pump_time}秒")
        except Exception as e:
            self.logger.error(f"处理远程配置消息失败: {e}")

    def _boot_self_check(self):
        """开机自检：启动后60秒拍摄一张照片并通过MQTT发送"""
        def take_boot_photo():
            try:
                self.logger.info("开机自检：开始拍摄自检照片...")
                if not self.camera_manager.is_available():
                    self.logger.warning("开机自检：摄像头不可用，跳过自检拍照")
                    return
                
                photo_path = self.camera_manager.capture_photo()
                if photo_path and os.path.exists(photo_path):
                    with open(photo_path, 'rb') as f:
                        photo_data = f.read()
                    
                    if self.mqtt_manager.publish_message(self.config['photo_topic'], photo_data, qos=0, retain=True):
                        self.logger.info(f"开机自检照片已发送: {photo_path}")
                    else:
                        self.logger.error("开机自检照片发送失败")
                else:
                    self.logger.error("开机自检：拍照物理执行失败")
            except Exception as e:
                self.logger.error(f"开机自检拍照异常: {e}")
        
        # 启动后60秒执行一次自检拍照
        Timer(60.0, take_boot_photo).start()
        self.logger.info("开机自检定时器已设置：60秒后将拍摄自检照片")

    def _setup_logging(self):
        file_handler = logging.handlers.RotatingFileHandler(
            self.config['log_file'], 
            maxBytes=5*1024*1024, 
            backupCount=3, 
            encoding='utf-8'
        )
        console_handler = logging.StreamHandler(sys.stdout)
        
        logging.basicConfig(
            level=self.config['log_level'],
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[file_handler, console_handler]
        )
        logger = logging.getLogger(self.__class__.__name__)
        return logger
    
    def monitor_loop(self):
        """主监控循环"""
        self.logger.info("开始监控循环 - 6阶段采样与上升沿触发拍照")
        
        led_state = False
        loop_counter = 0
        last_pump_states = [False] * len(self.channels)
        last_info_time = 0
        
        # 开机自检：启动后60秒拍摄一张照片
        self._boot_self_check()
        
        while not self.stop_event.is_set():
            try:
                # 每 5 秒切换一次指示灯状态 (对应 1s 循环)
                loop_counter += 1
                if loop_counter >= 5:
                    led_state = not led_state
                    self.water_controller.control_led(led_state)
                    loop_counter = 0

                for i, channel in enumerate(self.channels):
                    # 读取液位并处理逻辑
                    is_detected = self.water_controller.read_liquid_level(i)
                    needs_pump = channel.process_sensor(is_detected)
                    
                    # 拍照逻辑：捕获上升沿 (水泵开启瞬间)
                    if needs_pump and not last_pump_states[i]:
                        self.logger.info(f"检测到 # {i+1} 通道启动，触发 2秒 延时拍照")
                        self.photo_scheduler.trigger_delayed_photo(delay=2.0)
                    
                    last_pump_states[i] = needs_pump
                    
                    # 更新水泵状态 (WaterController 内部有 State Guard)
                    self.water_controller.control_pump(i, needs_pump)
                
                # 每 60 秒发布一次系统诊断信息 (降低频率，腾出带宽给实时警报)
                now = time.time()
                if now - last_info_time >= 60:
                    self._publish_info_msg()
                    last_info_time = now

                # 休眠 1 秒以保持稳定采样
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"监控循环异常: {e}")
                time.sleep(5)
    
    def _publish_info_msg(self):
        """发布包含 Clock, StartAt, Uptime 的三行诊断信息"""
        try:
            now = time.time()
            uptime_seconds = int(now - self.start_time)
            days, rem_sec = divmod(uptime_seconds, 86400)
            hours, rem_sec = divmod(rem_sec, 3600)
            minutes, _ = divmod(rem_sec, 60)
            
            uptime_str = f"{days}天 {hours}小时 {minutes}分钟"
            clock_str = datetime.now().strftime('%m月%d日 %H:%M')
            
            # 拼接三行字符串 (移除标签)
            info_msg = (
                f"{clock_str}\n"
                f"{self.start_at_str}\n"
                f"{uptime_str}"
            )
            self.mqtt_manager.publish_message(self.config['info_topic'], info_msg)
        except Exception as e:
            self.logger.error(f"发布诊断信息异常: {e}")

    def start(self):
        """启动监控"""
        if self.running:
            return
            
        self.running = True
        self.stop_event.clear()
        
        self.monitor_thread = Thread(target=self.monitor_loop)
        self.monitor_thread.start()
        self.logger.info("系统已启动")
    
    def stop(self):
        """停止监控"""
        if not self.running:
            return
            
        self.running = False
        self.stop_event.set()
        
        if self.monitor_thread:
            self.monitor_thread.join()
        
        self.photo_scheduler.stop()
        self.water_controller.stop_all_pumps()
        self.logger.info("系统已停止")
    
    def cleanup(self):
        """清理资源"""
        self.stop()
        self.mqtt_manager.cleanup()
        self.camera_manager.cleanup()
        self.water_controller.cleanup()
        self.logger.info("资源已完成清理")
        
    def __del__(self):
        if hasattr(self, 'running') and self.running:
            self.cleanup()

def check_single_instance(pid_file="/tmp/piwater.pid"):
    """使用文件锁确保只有一个实例运行"""
    f = open(pid_file, 'w')
    try:
        fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.write(str(os.getpid()))
        f.flush()
        return f
    except IOError:
        f.close()   # 获取锁失败时关闭文件句柄，避免泄漏
        return None

def main():
    """主函数"""
    # 确保单实例运行
    pid_f = check_single_instance()
    if not pid_f:
        print("\n[错误] 另一个程序实例已经在运行中 (PID文件被锁定)。")
        print("请检查是否有遗留的进程: pgrep -af python3")
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
            except:
                pass

if __name__ == "__main__":
    main()
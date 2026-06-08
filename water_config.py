#!/usr/bin/env python3
"""
水控制系统配置模块
包含所有系统配置常量和设置。
MQTT 凭据通过环境变量注入（由 systemd EnvironmentFile 或手动 export 提供），
避免明文密码硬编码在源码中。
"""

import logging
import os


class SystemConfig:
    """系统配置类"""

    # 正常工作模式
    MODE_NORMAL = "normal"

    # GPIO 引脚配置
    LIQUID_LEVEL_PINS = [17, 27, 22]   # 液位传感器 GPIO 引脚
    PUMP_PINS = [5, 6, 13]             # 水泵控制 GPIO 引脚
    LED_PIN = 26                       # 系统状态 LED 引脚

    # GPIO 逻辑电平定义
    PUMP_ON = 0                        # GPIO.LOW  - 启动
    PUMP_OFF = 1                       # GPIO.HIGH - 停止
    SENSOR_TRIGGER_LEVEL = 0           # GPIO.LOW  - 检测到液体（活跃）

    # 高级定时配置
    STABILIZATION_TIME = 180           # 稳定触发时间（3 分钟，秒）
    SAFETY_FACTOR = 0.75               # 安全系数：采样在总时长的前 75% 内完成
    # 通道预期总时长（秒）：次氯酸钠(1.5h), 碳源(2.0h), 氯化铁(40m)
    CHANNEL_EXPECTED_DURATIONS = [5400, 7200, 2400]

    # 泵工作时间配置（秒）
    PUMP_WORK_TIME = 10
    PUMP_REST_TIME_SHORT = 1800
    PUMP_REST_TIME_LONG = 3600

    # 拍照配置
    PHOTO_INTERVAL = 5                              # 拍照间隔（秒，保留配置项）
    PHOTO_TOPIC = "pi_water/photo"                  # 照片发布主题
    PHOTO_CMD_TOPIC = "pi_water/cmd/photo"          # 拍照指令主题（Android 下发）
    PHOTO_STATUS_TOPIC = "pi_water/photo/status"    # 拍照结果回报主题
    LOG_TOPIC_PREFIX = "pi_water/log"               # 远程日志主题前缀（后接 /1 /2 /3）
    DURATION_CONFIG_TOPIC = "pi_water/config/duration/+"   # 采样时长配置订阅主题
    PUMP_TIME_CONFIG_TOPIC = "pi_water/config/pump_time/+" # 泵启动时长配置订阅主题
    DISABLE_PHOTO = False

    # MQTT 配置（从环境变量读取；仅 BROKER/PORT 提供默认值，PASSWORD 必须注入）
    MQTT_BROKER = os.environ.get("MQTT_BROKER", "voicevon.vicp.io")
    MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
    MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "von")
    MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")   # 生产环境必须通过环境变量注入
    STATUS_TOPIC = "pi_water/system/status"
    INFO_TOPIC = "pi_water/system/info"

    # 日志配置
    LOG_LEVEL = logging.INFO
    LOG_FILE = "water_control_oo.log"

    # 摄像头配置
    DEFAULT_CAMERA_DEVICE = 0
    CAMERA_WIDTH = 640
    CAMERA_HEIGHT = 480
    CAMERA_FPS = 30
    CAMERA_BUFFERSIZE = 1

    # 文件路径配置
    DEFAULT_PHOTO_DIR = "/tmp"

    # 远程配置值域限制（防止非法值导致硬件异常）
    MIN_DURATION_MIN = 10       # 最短采样时长：10 分钟
    MAX_DURATION_MIN = 480      # 最长采样时长：8 小时
    MIN_PUMP_SEC = 5            # 最短泵工作时间：5 秒
    MAX_PUMP_SEC = 120          # 最长泵工作时间：120 秒


def get_default_config():
    """获取默认配置字典"""
    return {
        # GPIO 引脚配置
        'liquid_level_pins': SystemConfig.LIQUID_LEVEL_PINS,
        'pump_pins': SystemConfig.PUMP_PINS,
        'led_pin': SystemConfig.LED_PIN,
        'pump_on': SystemConfig.PUMP_ON,
        'pump_off': SystemConfig.PUMP_OFF,

        # 高级定时配置
        'stabilization_time': SystemConfig.STABILIZATION_TIME,
        'safety_factor': SystemConfig.SAFETY_FACTOR,
        'channel_expected_durations': SystemConfig.CHANNEL_EXPECTED_DURATIONS,
        'pump_work_time': SystemConfig.PUMP_WORK_TIME,
        'pump_rest_time_short': SystemConfig.PUMP_REST_TIME_SHORT,
        'pump_rest_time_long': SystemConfig.PUMP_REST_TIME_LONG,

        # 拍照配置
        'photo_interval': SystemConfig.PHOTO_INTERVAL,
        'photo_topic': SystemConfig.PHOTO_TOPIC,
        'photo_cmd_topic': SystemConfig.PHOTO_CMD_TOPIC,
        'photo_status_topic': SystemConfig.PHOTO_STATUS_TOPIC,
        'disable_photo': SystemConfig.DISABLE_PHOTO,
        'sensor_trigger_level': SystemConfig.SENSOR_TRIGGER_LEVEL,

        # MQTT 配置
        'mqtt_broker': SystemConfig.MQTT_BROKER,
        'mqtt_port': SystemConfig.MQTT_PORT,
        'mqtt_username': SystemConfig.MQTT_USERNAME,
        'mqtt_password': SystemConfig.MQTT_PASSWORD,
        'status_topic': SystemConfig.STATUS_TOPIC,
        'info_topic': SystemConfig.INFO_TOPIC,
        'log_topic_prefix': SystemConfig.LOG_TOPIC_PREFIX,
        'duration_config_topic': SystemConfig.DURATION_CONFIG_TOPIC,
        'pump_time_config_topic': SystemConfig.PUMP_TIME_CONFIG_TOPIC,

        # 日志配置
        'log_level': SystemConfig.LOG_LEVEL,
        'log_file': SystemConfig.LOG_FILE,

        # 摄像头配置
        'default_camera_device': SystemConfig.DEFAULT_CAMERA_DEVICE,
        'camera_width': SystemConfig.CAMERA_WIDTH,
        'camera_height': SystemConfig.CAMERA_HEIGHT,
        'camera_fps': SystemConfig.CAMERA_FPS,
        'camera_buffersize': SystemConfig.CAMERA_BUFFERSIZE,

        # 文件路径配置
        'default_photo_dir': SystemConfig.DEFAULT_PHOTO_DIR,

        # 值域限制
        'min_duration_min': SystemConfig.MIN_DURATION_MIN,
        'max_duration_min': SystemConfig.MAX_DURATION_MIN,
        'min_pump_sec': SystemConfig.MIN_PUMP_SEC,
        'max_pump_sec': SystemConfig.MAX_PUMP_SEC,
    }
#!/usr/bin/env python3
"""
水控制系统配置模块
包含所有系统配置常量和设置
"""

import logging

# 系统配置常量
class SystemConfig:
    """系统配置类"""
    
    # 正常工作模式
    MODE_NORMAL = "normal"
    
    # GPIO引脚配置
    LIQUID_LEVEL_PINS = [17, 27, 22]  # 液位传感器GPIO引脚
    PUMP_PINS = [5, 6, 13]            # 水泵控制GPIO引脚
    LED_PIN = 26                      # 系统状态LED引脚
    
    # GPIO逻辑电平定义
    PUMP_ON = 0  # GPIO.LOW - 启动
    PUMP_OFF = 1 # GPIO.HIGH - 停止
    SENSOR_TRIGGER_LEVEL = 0 # GPIO.LOW - 检测到液体 (活跃)
    
    # 高级定时配置
    STABILIZATION_TIME = 180          # 稳定触发时间 (3分钟)
    SAFETY_FACTOR = 0.75              # 安全系数 (仅在总时长的前75%时间内完成采样)
    # 通道预期总时长 (秒): 次氯酸钠(1.5h), 碳源(2.0h), 氯化铁(40m)
    CHANNEL_EXPECTED_DURATIONS = [5400, 7200, 2400]
    
    # 兼容旧代码的变量 (可选保留)
    PUMP_WORK_TIME = 10
    PUMP_REST_TIME_SHORT = 1800
    PUMP_REST_TIME_LONG = 3600
    
    # 拍照配置
    PHOTO_INTERVAL = 5                # 拍照间隔（5秒）
    PHOTO_TOPIC = "pi_water/photo"    # 照片MQTT主题
    LOG_TOPIC_PREFIX = "pi_water/log" # 远程日志MQTT主题前缀 (后接 /1, /2, /3)
    DURATION_CONFIG_TOPIC = "pi_water/config/duration/+" # 采样时长配置订阅主题
    PUMP_TIME_CONFIG_TOPIC = "pi_water/config/pump_time/+" # 泵启动时长配置订阅主题
    DISABLE_PHOTO = False             # 调试完成：恢复拍照
    
    # MQTT配置
    MQTT_BROKER = "voicevon.vicp.io"
    MQTT_PORT = 1883
    MQTT_USERNAME = "von"
    MQTT_PASSWORD = "von123456"
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

# 默认配置字典
def get_default_config():
    """获取默认配置"""
    return {
        # GPIO引脚配置
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
        'disable_photo': SystemConfig.DISABLE_PHOTO,
        'sensor_trigger_level': SystemConfig.SENSOR_TRIGGER_LEVEL,
        
        # MQTT配置
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
        'default_photo_dir': SystemConfig.DEFAULT_PHOTO_DIR
    }
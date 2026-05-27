#!/usr/bin/env python3
"""
MQTT管理模块
MQTT客户端管理类
"""

import paho.mqtt.client as mqtt
import json
import time
import logging


class MQTTManager:
    """MQTT客户端管理类"""
    
    def __init__(self, broker, port, username, password, client_id=None):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id or f"pi_water_{int(time.time())}"
        
        self.client = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialize()
    
    def _initialize(self):
        """初始化MQTT客户端"""
        try:
            self.client = mqtt.Client(client_id=self.client_id)
            self.client.username_pw_set(self.username, self.password)
            
            # 设置连接回调
            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    self.logger.info("✅ MQTT连接成功")
                else:
                    self.logger.error(f"❌ MQTT连接失败，返回码: {rc}")
            
            def on_disconnect(client, userdata, rc):
                self.logger.info(f"MQTT断开连接，返回码: {rc}")
            
            self.client.on_connect = on_connect
            self.client.on_disconnect = on_disconnect
            
            # 设置消息回调
            def on_message(client, userdata, msg):
                try:
                    payload = msg.payload.decode()
                    self.logger.debug(f"收到MQTT消息: {msg.topic} -> {payload}")
                    if hasattr(self, 'message_callback') and self.message_callback:
                        self.message_callback(msg.topic, payload)
                except Exception as e:
                    self.logger.error(f"处理MQTT消息异常: {e}")
            
            self.client.on_message = on_message
            
            # 连接并等待结果
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            
            # 等待连接确认
            time.sleep(2)
            
            if self.client.is_connected():
                self.logger.info(f"✅ MQTT客户端初始化成功 (Broker: {self.broker}:{self.port})")
            else:
                self.logger.warning(f"⚠️ MQTT客户端初始化完成但未连接 (Broker: {self.broker}:{self.port})")
                
        except Exception as e:
            self.logger.error(f"MQTT初始化失败: {e}")
            self.client = None
    
    def publish_message(self, topic, message, qos=0, retain=True):
        """发布MQTT消息"""
        if self.client is None:
            self.logger.warning("MQTT客户端未初始化")
            return False
            
        try:
            if isinstance(message, dict):
                message = json.dumps(message)
            
            result = self.client.publish(topic, message, qos=qos, retain=retain)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.logger.debug(f"MQTT消息发送成功到 {topic} (retain={retain})")
                return True
            else:
                self.logger.error(f"MQTT消息发送失败: {result.rc}")
                return False
        except Exception as e:
            self.logger.error(f"MQTT消息发送异常: {e}")
            return False
    
    def set_callback(self, callback):
        """设置消息处理回调函数"""
        self.message_callback = callback
    
    def subscribe(self, topic, qos=0):
        """订阅主题"""
        if self.client:
            self.client.subscribe(topic, qos)
            self.logger.info(f"已订阅主题: {topic}")
            return True
        return False
        
    def is_connected(self):
        """检查MQTT连接状态"""
        return self.client is not None and self.client.is_connected()
    
    def cleanup(self):
        """清理MQTT资源"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            self.logger.info("MQTT客户端已断开连接")
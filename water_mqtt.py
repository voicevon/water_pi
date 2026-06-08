#!/usr/bin/env python3
"""
MQTT 管理模块
修复：
  1. 断线重连后自动重订阅所有已注册主题（BUG-04）
  2. 二进制 payload（如照片回环）不再触发 UnicodeDecodeError（DESIGN-06）
  3. 断开连接时区分主动/意外，日志更清晰
"""

import paho.mqtt.client as mqtt
import json
import time
import logging


class MQTTManager:
    """MQTT 客户端管理类"""

    def __init__(self, broker, port, username, password, client_id=None):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id or f"pi_water_{int(time.time())}"
        # 记录所有已订阅的 (topic, qos)，用于断线重连后自动重订阅
        self._subscribed_topics: list[tuple[str, int]] = []

        self.client = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialize()

    def _initialize(self):
        """初始化 MQTT 客户端"""
        try:
            self.client = mqtt.Client(client_id=self.client_id)
            self.client.username_pw_set(self.username, self.password)

            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    self.logger.info("✅ MQTT 连接成功")
                    # 断线重连后重新订阅所有已注册主题
                    for topic, qos in self._subscribed_topics:
                        client.subscribe(topic, qos)
                        self.logger.info(f"🔄 重订阅主题: {topic}")
                else:
                    self.logger.error(f"❌ MQTT 连接失败，返回码: {rc}")

            def on_disconnect(client, userdata, rc):
                if rc != 0:
                    self.logger.warning(f"⚠️ MQTT 意外断开（rc={rc}），将自动重连...")
                else:
                    self.logger.info("MQTT 正常断开连接")

            def on_message(client, userdata, msg):
                try:
                    # 尝试 UTF-8 解码；二进制 payload（如照片回环）直接丢弃，防止崩溃
                    try:
                        payload = msg.payload.decode('utf-8')
                    except UnicodeDecodeError:
                        self.logger.debug(
                            f"收到二进制消息: {msg.topic} ({len(msg.payload)} bytes)，已忽略"
                        )
                        return
                    self.logger.debug(f"收到 MQTT 消息: {msg.topic} -> {payload}")
                    if hasattr(self, 'message_callback') and self.message_callback:
                        self.message_callback(msg.topic, payload)
                except Exception as e:
                    self.logger.error(f"处理 MQTT 消息异常: {e}")

            self.client.on_connect = on_connect
            self.client.on_disconnect = on_disconnect
            self.client.on_message = on_message

            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()

            # 等待连接确认
            time.sleep(2)

            if self.client.is_connected():
                self.logger.info(f"✅ MQTT 客户端初始化成功 (Broker: {self.broker}:{self.port})")
            else:
                self.logger.warning(
                    f"⚠️ MQTT 客户端初始化完成但未连接 (Broker: {self.broker}:{self.port})"
                )

        except Exception as e:
            self.logger.error(f"MQTT 初始化失败: {e}")
            self.client = None

    def publish_message(self, topic, message, qos=0, retain=True):
        """发布 MQTT 消息（dict 自动序列化为 JSON）"""
        if self.client is None:
            self.logger.warning("MQTT 客户端未初始化")
            return False

        try:
            if isinstance(message, dict):
                message = json.dumps(message, ensure_ascii=False)

            result = self.client.publish(topic, message, qos=qos, retain=retain)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.logger.debug(f"MQTT 消息发送成功: {topic} (retain={retain})")
                return True
            else:
                self.logger.error(f"MQTT 消息发送失败: {result.rc}")
                return False
        except Exception as e:
            self.logger.error(f"MQTT 消息发送异常: {e}")
            return False

    def set_callback(self, callback):
        """设置消息处理回调函数"""
        self.message_callback = callback

    def subscribe(self, topic, qos=0):
        """订阅主题，并记录以便断线重连后自动重订阅"""
        if self.client:
            self.client.subscribe(topic, qos)
            # 避免重复记录同一 topic
            if not any(t == topic for t, _ in self._subscribed_topics):
                self._subscribed_topics.append((topic, qos))
            self.logger.info(f"已订阅主题: {topic}")
            return True
        return False

    def is_connected(self):
        """检查 MQTT 连接状态"""
        return self.client is not None and self.client.is_connected()

    def cleanup(self):
        """清理 MQTT 资源"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            self.logger.info("MQTT 客户端已断开连接")
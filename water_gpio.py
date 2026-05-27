#!/usr/bin/env python3
"""
GPIO控制模块
水泵控制器类
"""

import RPi.GPIO as GPIO
import logging


class WaterController:
    """水泵控制器类"""
    
    def __init__(self, liquid_level_pins, pump_pins, led_pin=None, pump_on=0, pump_off=1, sensor_trigger_level=0):
        self.liquid_level_pins = liquid_level_pins
        self.pump_pins = pump_pins
        self.led_pin = led_pin
        self.PUMP_ON = pump_on
        self.PUMP_OFF = pump_off
        self.SENSOR_TRIGGER_LEVEL = sensor_trigger_level
        self.pump_states = [None] * len(pump_pins)  # 初始化为 None 以强制第一次设置生效
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialize_gpio()
    
    def _initialize_gpio(self):
        """初始化GPIO引脚"""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            # 设置液位传感器引脚为输入（上拉）
            for pin in self.liquid_level_pins:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                self.logger.info(f"液位传感器引脚 {pin} 初始化完成")
            
            # 设置水泵控制引脚为输出（默认设置为停止状态）
            for pin in self.pump_pins:
                GPIO.setup(pin, GPIO.OUT, initial=self.PUMP_OFF)
                self.logger.info(f"水泵控制引脚 {pin} 初始化完成 (默认停止)")
                
            # 设置LED引脚为输出
            if self.led_pin is not None:
                GPIO.setup(self.led_pin, GPIO.OUT, initial=GPIO.LOW)
                self.logger.info(f"LED指示灯引脚 {self.led_pin} 初始化完成")
                
        except Exception as e:
            self.logger.error(f"GPIO初始化失败: {e}")
            raise
    
    def read_liquid_level(self, channel):
        """读取指定通道的液位状态 (返回输入电平)"""
        if 0 <= channel < len(self.liquid_level_pins):
            pin = self.liquid_level_pins[channel]
            # 根据配置的触发电平判断是否检测到液体 (LOW 表示触发)
            return GPIO.input(pin) == self.SENSOR_TRIGGER_LEVEL
        return False
    
    def control_pump(self, channel, state):
        """控制指定通道的水泵 (带状态变更守卫，防止重复写入导致闪烁)"""
        if 0 <= channel < len(self.pump_pins):
            # 仅在状态确实发生变化时才操作硬件
            if self.pump_states[channel] != state:
                pin = self.pump_pins[channel]
                # 根据原子化定义输出电平
                target_level = self.PUMP_ON if state else self.PUMP_OFF
                GPIO.output(pin, target_level)
                
                self.pump_states[channel] = state
                self.logger.info(f"通道{channel+1}水泵逻辑变更 -> {'启动' if state else '停止'} (电平: {target_level})")
    
    def stop_all_pumps(self):
        """停止所有水泵"""
        for channel in range(len(self.pump_pins)):
            self.control_pump(channel, False)
        self.logger.info("所有水泵已停止")
    
    def control_led(self, state):
        """控制LED指示灯状态"""
        if self.led_pin is not None:
            GPIO.output(self.led_pin, GPIO.HIGH if state else GPIO.LOW)
            
    def cleanup(self):
        """清理GPIO资源"""
        self.stop_all_pumps()
        GPIO.cleanup()
        self.logger.info("GPIO资源已清理")
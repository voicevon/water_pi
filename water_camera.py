#!/usr/bin/env python3
"""
摄像头管理模块
基于OpenCV进行简单的图像捕获
"""

import cv2
import time
import logging
import os
from datetime import datetime

class CameraManager:
    """摄像头管理类"""
    
    def __init__(self, device_id=0):
        self.device_id = device_id
        self.logger = logging.getLogger(self.__class__.__name__)
        
    def capture_photo(self, save_dir="/tmp"):
        """拍摄照片并保存"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        filepath = os.path.join(save_dir, filename)
        
        device_path = f"/dev/video{self.device_id}"
        cap = cv2.VideoCapture(device_path, cv2.CAP_V4L2)
        
        if not cap.isOpened():
            self.logger.error(f"无法打开摄像头: {device_path}")
            return None
            
        try:
            # 基础设置
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            
            # 预热
            time.sleep(2)
            
            cap.grab()
            ret, frame = cap.retrieve()
            
            if ret and frame is not None and frame.size > 0:
                cv2.imwrite(filepath, frame)
                self.logger.info(f"拍照成功: {filepath}")
                return filepath
            else:
                self.logger.error("捕获图像帧失败")
                return None
        except Exception as e:
            self.logger.error(f"拍照发生异常: {e}")
            return None
        finally:
            cap.release()
            
    def is_available(self):
        """检查摄像头是否可用"""
        device_path = f"/dev/video{self.device_id}"
        cap = cv2.VideoCapture(device_path, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.release()
            return True
        return False
        
    def cleanup(self):
        """清理资源（如有持续打开的句柄）"""
        pass
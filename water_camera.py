#!/usr/bin/env python3
"""
摄像头管理模块（持久化连接模式）
修复：
  1. 相机初始化时预热一次，后续拍照无冷启动延迟（BUG-03）
  2. 拍照后自动清理 30 分钟前的旧文件，防止 tmpfs 耗尽（RISK-05）
  3. 帧捕获失败时自动重置连接
"""

import cv2
import time
import logging
import os
from datetime import datetime

# 旧照片保留时长（秒），超过此时间自动删除
PHOTO_MAX_AGE_SECONDS = 1800  # 30 分钟


class CameraManager:
    """摄像头管理类（持久化连接，避免重复冷启动延迟）"""

    def __init__(self, device_id=0):
        self.device_id = device_id
        self.cap = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._open_camera()

    def _open_camera(self):
        """打开摄像头并完成一次性预热（仅首次调用时等待 2 秒）"""
        device_path = f"/dev/video{self.device_id}"
        cap = cv2.VideoCapture(device_path, cv2.CAP_V4L2)
        if not cap.isOpened():
            self.logger.warning(f"摄像头 {device_path} 打开失败，将在拍照时重试")
            cap.release()
            self.cap = None
            return

        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # 预热：只在首次打开时等待，后续拍照无需再等
        time.sleep(2)
        self.cap = cap
        self.logger.info(f"摄像头 {device_path} 已初始化（持久连接模式）")

    def capture_photo(self, save_dir="/tmp"):
        """拍摄照片并保存。持久连接模式下无冷启动延迟。"""
        # 若摄像头未就绪，尝试重新打开
        if not self.is_available():
            self.logger.warning("摄像头未就绪，尝试重新初始化...")
            self._open_camera()
            if not self.is_available():
                return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(save_dir, f"photo_{timestamp}.jpg")

        try:
            self.cap.grab()
            ret, frame = self.cap.retrieve()

            if ret and frame is not None and frame.size > 0:
                cv2.imwrite(filepath, frame)
                self.logger.info(f"拍照成功: {filepath}")
                self._cleanup_old_photos(save_dir)
                return filepath
            else:
                self.logger.error("捕获图像帧失败，重置摄像头连接")
                self._reset_camera()
                return None
        except Exception as e:
            self.logger.error(f"拍照发生异常: {e}")
            self._reset_camera()
            return None

    def _reset_camera(self):
        """重置摄像头连接（帧捕获异常时调用）"""
        if self.cap:
            self.cap.release()
            self.cap = None
        self._open_camera()

    def _cleanup_old_photos(self, save_dir, max_age_seconds=PHOTO_MAX_AGE_SECONDS):
        """清理超过 max_age_seconds 的旧照片文件，防止 tmpfs 耗尽"""
        try:
            now = time.time()
            for fname in os.listdir(save_dir):
                if fname.startswith("photo_") and fname.endswith(".jpg"):
                    fpath = os.path.join(save_dir, fname)
                    if now - os.path.getmtime(fpath) > max_age_seconds:
                        os.remove(fpath)
                        self.logger.debug(f"已清理旧照片: {fpath}")
        except Exception as e:
            self.logger.warning(f"清理旧照片时出错: {e}")

    def is_available(self):
        """检查摄像头是否可用"""
        return self.cap is not None and self.cap.isOpened()

    def cleanup(self):
        """释放摄像头资源"""
        if self.cap:
            self.cap.release()
            self.cap = None
            self.logger.info("摄像头资源已释放")
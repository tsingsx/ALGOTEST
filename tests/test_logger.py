#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：日志模块的测试代码
开发规划：测试日志配置和记录功能
"""

import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from loguru import logger

from core.logger import setup_logging, get_logger
from core.config import Settings

class TestLogger(unittest.TestCase):
    """日志模块测试类"""
    
    def setUp(self):
        """测试前准备"""
        # 创建临时日志目录
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temp_dir.name) / "logs"
        self.log_dir.mkdir(exist_ok=True)
        
        # 备份原始logger
        self.original_handlers = logger._core.handlers.copy()
    
    def tearDown(self):
        """测试后清理"""
        # 恢复原始logger
        logger._core.handlers = self.original_handlers
        
        # 清理临时目录
        self.temp_dir.cleanup()
    
    @patch("core.logger.get_settings")
    def test_setup_logging(self, mock_get_settings):
        """测试日志系统初始化"""
        # 模拟配置
        mock_settings = MagicMock(spec=Settings)
        mock_settings.log_level = "DEBUG"
        mock_settings.log_file = str(self.log_dir / "test_{time}.log")
        mock_settings.log_rotation = "1 MB"
        mock_settings.log_retention = "1 day"
        mock_get_settings.return_value = mock_settings
        
        # 清除现有处理器
        logger.remove()
        
        # 初始化日志系统
        setup_logging()
        
        # 验证处理器数量（控制台+文件）
        self.assertEqual(len(logger._core.handlers), 2)
        
        # 测试日志记录
        logger.debug("测试调试日志")
        logger.info("测试信息日志")
        logger.warning("测试警告日志")
        logger.error("测试错误日志")
        
        # 验证日志文件是否创建
        log_files = list(self.log_dir.glob("*.log"))
        self.assertGreater(len(log_files), 0)
    
    def test_get_logger(self):
        """测试获取带有上下文的logger"""
        # 清除现有处理器
        logger.remove()
        
        # 添加测试处理器
        test_messages = []
        logger.add(lambda msg: test_messages.append(msg.record["message"]))
        
        # 获取带有上下文的logger
        test_logger = get_logger("test_module")
        
        # 记录日志
        test_logger.info("测试信息")
        
        # 验证日志内容
        self.assertIn("测试信息", test_messages)
        
        # 检查绑定的上下文
        bound_logger = logger.bind(name="test_module")
        bound_logger.info("绑定测试")
        self.assertIn("绑定测试", test_messages)
    
    def test_log_levels(self):
        """测试不同日志级别"""
        # 清除现有处理器
        logger.remove()
        
        # 添加测试处理器
        test_messages = []
        logger.add(lambda msg: test_messages.append(msg), level="WARNING")
        
        # 获取logger
        test_logger = get_logger()
        
        # 记录不同级别的日志
        test_logger.debug("调试信息")
        test_logger.info("普通信息")
        test_logger.warning("警告信息")
        test_logger.error("错误信息")
        
        # 验证只有WARNING及以上级别的日志被记录
        self.assertEqual(len(test_messages), 2)
        self.assertTrue(any("警告信息" in msg for msg in test_messages))
        self.assertTrue(any("错误信息" in msg for msg in test_messages))
        self.assertFalse(any("调试信息" in msg for msg in test_messages))
        self.assertFalse(any("普通信息" in msg for msg in test_messages))

if __name__ == "__main__":
    unittest.main() 
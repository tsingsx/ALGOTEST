#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：工具函数模块的测试代码
开发规划：测试各种工具函数的功能
"""

import os
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from core.utils import (
    generate_unique_id,
    save_json_file,
    load_json_file,
    calculate_md5,
    format_timestamp,
    make_request,
    ensure_dir,
    read_file,
    write_file
)

class TestUtils(unittest.TestCase):
    """工具函数模块测试类"""
    
    def setUp(self):
        """测试前准备"""
        # 创建临时目录
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)
    
    def tearDown(self):
        """测试后清理"""
        # 清理临时目录
        self.temp_dir.cleanup()
    
    def test_generate_unique_id(self):
        """测试生成唯一ID"""
        # 生成ID
        id1 = generate_unique_id()
        id2 = generate_unique_id()
        
        # 验证ID不同
        self.assertNotEqual(id1, id2)
        
        # 测试带前缀的ID
        prefix_id = generate_unique_id("test_")
        self.assertTrue(prefix_id.startswith("test_"))
        
        # 验证ID格式
        self.assertRegex(id1, r"^\d+_[a-f0-9]{12}$")
    
    def test_save_load_json_file(self):
        """测试JSON文件保存和加载"""
        # 测试数据
        test_data = {
            "name": "测试数据",
            "values": [1, 2, 3, 4, 5],
            "nested": {
                "key": "value"
            }
        }
        
        # 文件路径
        file_path = self.test_dir / "test_data.json"
        
        # 保存文件
        result = save_json_file(test_data, str(file_path))
        self.assertTrue(result)
        self.assertTrue(file_path.exists())
        
        # 加载文件
        loaded_data = load_json_file(str(file_path))
        self.assertEqual(loaded_data, test_data)
        
        # 测试加载不存在的文件
        non_existent_result = load_json_file(str(self.test_dir / "non_existent.json"))
        self.assertIsNone(non_existent_result)
    
    def test_calculate_md5(self):
        """测试计算MD5哈希值"""
        # 创建测试文件
        file_path = self.test_dir / "test_md5.txt"
        with open(file_path, "w") as f:
            f.write("测试内容")
        
        # 计算MD5
        md5_hash = calculate_md5(str(file_path))
        self.assertIsNotNone(md5_hash)
        self.assertEqual(len(md5_hash), 32)  # MD5哈希值长度为32个字符
        
        # 测试计算不存在文件的MD5
        non_existent_md5 = calculate_md5(str(self.test_dir / "non_existent.txt"))
        self.assertIsNone(non_existent_md5)
    
    def test_format_timestamp(self):
        """测试格式化时间戳"""
        # 测试指定时间戳
        timestamp = 1609459200  # 2021-01-01 00:00:00 UTC
        formatted = format_timestamp(timestamp)
        
        # 由于时区差异，我们只检查日期部分
        self.assertTrue(formatted.startswith("2021-01-01"))
        
        # 测试自定义格式
        custom_format = format_timestamp(timestamp, "%Y/%m/%d")
        self.assertEqual(custom_format, "2021/01/01")
        
        # 测试当前时间戳
        current_format = format_timestamp()
        self.assertIsNotNone(current_format)
        self.assertRegex(current_format, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
    
    @patch("core.utils.requests.request")
    def test_make_request(self, mock_request):
        """测试发送HTTP请求"""
        # 模拟响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"result": "success"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_request.return_value = mock_response
        
        # 发送请求
        result = make_request("https://example.com/api", method="POST", data={"key": "value"})
        
        # 验证结果
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["content"], '{"result": "success"}')
        self.assertEqual(result["headers"], {"Content-Type": "application/json"})
        self.assertTrue(result["success"])
        
        # 验证请求参数
        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["url"], "https://example.com/api")
        self.assertEqual(kwargs["data"], '{"key": "value"}')
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})
        
        # 测试请求异常
        mock_request.side_effect = Exception("连接错误")
        error_result = make_request("https://example.com/api")
        self.assertEqual(error_result["status_code"], 0)
        self.assertEqual(error_result["content"], "连接错误")
        self.assertFalse(error_result["success"])
    
    def test_ensure_dir(self):
        """测试确保目录存在"""
        # 测试创建目录
        test_path = self.test_dir / "test_dir" / "nested"
        result = ensure_dir(str(test_path))
        self.assertTrue(result)
        self.assertTrue(test_path.exists())
        
        # 测试已存在的目录
        result2 = ensure_dir(str(test_path))
        self.assertTrue(result2)
    
    def test_read_write_file(self):
        """测试读写文件"""
        # 测试写入文件
        file_path = self.test_dir / "test_file.txt"
        content = "测试内容\n第二行"
        
        result = write_file(content, str(file_path))
        self.assertTrue(result)
        self.assertTrue(file_path.exists())
        
        # 测试读取文件
        read_content = read_file(str(file_path))
        self.assertEqual(read_content, content)
        
        # 测试读取不存在的文件
        non_existent_content = read_file(str(self.test_dir / "non_existent.txt"))
        self.assertIsNone(non_existent_content)

if __name__ == "__main__":
    unittest.main() 
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
测试解析命令函数
"""

import os
import sys
import unittest
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Dict, Any, List

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.execution_agent import parse_command, CommandStrategy, ExecutionState


class TestParseCommand(unittest.IsolatedAsyncioTestCase):
    """测试解析命令函数，使用IsolatedAsyncioTestCase支持异步测试"""

    def setUp(self):
        """测试前设置"""
        # 初始状态
        self.base_state = {
            "task_id": "TASK12345",
            "case_id": None,
            "algorithm_image": "test_image:latest",
            "dataset_url": None,
            "test_cases": [
                {
                    "id": 1,
                    "task_id": "TASK12345",
                    "case_id": "TC12345",
                    "document_id": "DOC12345",
                    "input_data": {
                        "name": "测试用例1",
                        "purpose": "测试算法基本功能",
                        "steps": "执行python main.py --test"
                    },
                    "expected_output": {
                        "expected_result": "程序正常退出，返回码为0",
                        "validation_method": "检查返回码"
                    }
                }
            ],
            "current_case_index": 0,
            "command_strategy": None,
            "execution_result": None,
            "errors": [],
            "status": "loaded",
            "container_ready": False
        }
        
        # 模拟的命令策略
        self.mock_command_strategy = CommandStrategy(
            tool="execute_command",
            parameters={"command": "python main.py --test"},
            description="执行Python脚本进行测试"
        )

    @patch('agents.execution_agent.ZhipuAIClient')
    async def test_parse_command_success(self, mock_zhipu_client):
        """测试成功解析命令"""
        # 模拟ZhipuAIClient.parse_command的行为
        mock_client_instance = MagicMock()
        mock_client_instance.parse_command = AsyncMock(return_value=self.mock_command_strategy)
        mock_zhipu_client.return_value = mock_client_instance
        
        # 执行函数
        state = await parse_command(self.base_state)
        
        # 验证结果
        self.assertEqual(state["status"], "parsed")
        self.assertEqual(state["case_id"], "TC12345")
        self.assertEqual(state["command_strategy"].tool, "execute_command")
        self.assertEqual(state["command_strategy"].parameters["command"], "python main.py --test")
        
        # 验证调用
        mock_zhipu_client.assert_called_once()
        mock_client_instance.parse_command.assert_called_once_with("执行python main.py --test", [])

    @patch('agents.execution_agent.ZhipuAIClient')
    async def test_parse_command_empty_steps(self, mock_zhipu_client):
        """测试测试步骤为空的情况"""
        # 修改状态中的测试步骤为空
        state_with_empty_steps = dict(self.base_state)
        state_with_empty_steps["test_cases"][0]["input_data"]["steps"] = ""
        
        # 执行函数
        state = await parse_command(state_with_empty_steps)
        
        # 验证结果
        self.assertEqual(state["status"], "error")
        self.assertTrue(any("测试步骤为空" in error for error in state["errors"]))
        
        # 验证没有调用ZhipuAIClient
        mock_zhipu_client.assert_not_called()

    @patch('agents.execution_agent.ZhipuAIClient')
    async def test_parse_command_api_error(self, mock_zhipu_client):
        """测试API调用失败的情况"""
        # 模拟ZhipuAIClient.parse_command抛出异常
        mock_client_instance = MagicMock()
        mock_client_instance.parse_command = AsyncMock(side_effect=Exception("API调用失败"))
        mock_zhipu_client.return_value = mock_client_instance
        
        # 执行函数
        state = await parse_command(self.base_state)
        
        # 验证结果
        self.assertEqual(state["status"], "error")
        self.assertTrue(any("API调用失败" in error for error in state["errors"]))
        
        # 验证调用
        mock_zhipu_client.assert_called_once()
        mock_client_instance.parse_command.assert_called_once()

    @patch('agents.execution_agent.ZhipuAIClient')
    async def test_parse_command_no_test_cases(self, mock_zhipu_client):
        """测试没有测试用例的情况"""
        # 创建没有测试用例的状态
        state_without_cases = dict(self.base_state)
        state_without_cases["test_cases"] = []
        
        # 执行函数
        state = await parse_command(state_without_cases)
        
        # 验证结果
        self.assertEqual(state["status"], "error")
        self.assertTrue(any("没有可执行的测试用例" in error for error in state["errors"]))
        
        # 验证没有调用ZhipuAIClient
        mock_zhipu_client.assert_not_called()


if __name__ == "__main__":
    unittest.main() 
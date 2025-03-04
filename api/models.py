#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：API模型定义，包括请求和响应的数据模型
开发规划：使用Pydantic模型定义API接口的请求和响应数据结构
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class TestCase(BaseModel):
    """测试用例响应模型"""
    id: str = Field(..., description="测试用例ID")
    name: str = Field(..., description="测试名称")
    purpose: str = Field(..., description="测试目的")
    steps: str = Field(..., description="测试步骤")
    expected_result: str = Field(..., description="预期结果")
    validation_method: str = Field(..., description="验证方法")


class TestCasesResponse(BaseModel):
    """测试用例生成响应模型"""
    message: str = Field(..., description="响应消息")
    test_cases: List[TestCase] = Field(..., description="生成的测试用例列表")

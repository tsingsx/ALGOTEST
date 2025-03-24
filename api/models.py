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
    id: str = Field(description="测试用例ID")
    name: str = Field(description="测试名称")
    purpose: str = Field(description="测试目的")
    steps: str = Field(description="测试步骤")
    expected_result: str = Field(description="预期结果")
    validation_method: str = Field(description="验证方法")
    document_id: str = Field(description="所属文档ID")
    actual_output: Optional[str] = Field(None, description="实际输出结果")
    result_analysis: Optional[str] = Field(None, description="结果分析")
    is_passed: Optional[bool] = Field(None, description="是否通过测试")
    status: Optional[str] = Field("pending", description="执行状态")


class TestCasesResponse(BaseModel):
    """测试用例生成响应模型"""
    message: str = Field(description="响应消息")
    test_cases: List[TestCase] = Field(description="生成的测试用例列表")


class DocumentUploadResponse(BaseModel):
    """文档上传响应模型"""
    message: str = Field(description="响应消息")
    document_id: str = Field(description="文档ID")
    filename: str = Field(description="文件名")
    file_path: str = Field(description="文件路径")


class DocumentAnalysisRequest(BaseModel):
    """文档分析请求模型"""
    document_id: str = Field(description="文档ID")


class AlgorithmImageRequest(BaseModel):
    """算法镜像请求模型"""
    algorithm_image: str = Field(description="算法镜像地址")


class DatasetUrlRequest(BaseModel):
    """数据集地址请求模型"""
    dataset_url: str = Field(description="数据集地址")


class TestCaseCreateRequest(BaseModel):
    """测试用例创建请求模型"""
    name: str = Field(description="测试名称")
    purpose: str = Field(description="测试目的")
    steps: str = Field(description="测试步骤")
    expected_result: str = Field(description="预期结果")
    validation_method: str = Field(description="验证方法")
    document_id: str = Field(description="所属文档ID")


class TestCaseUpdateRequest(BaseModel):
    """测试用例更新请求模型"""
    name: Optional[str] = Field(None, description="测试名称")
    purpose: Optional[str] = Field(None, description="测试目的")
    steps: Optional[str] = Field(None, description="测试步骤")
    expected_result: Optional[str] = Field(None, description="预期结果")
    validation_method: Optional[str] = Field(None, description="验证方法")
    document_id: Optional[str] = Field(None, description="所属文档ID")


class MessageResponse(BaseModel):
    """通用消息响应模型"""
    message: str = Field(description="响应消息")

class TestTaskItem(BaseModel):
    """测试任务项模型"""
    id: int = Field(description="任务ID")
    task_id: str = Field(description="任务唯一标识")
    document_id: Optional[str] = Field(None, description="文档ID")
    requirement_doc: Optional[str] = Field(None, description="需求文档内容")
    algorithm_image: Optional[str] = Field(None, description="算法镜像")
    dataset_url: Optional[str] = Field(None, description="数据集URL")
    container_name: Optional[str] = Field(None, description="容器名称")
    status: str = Field(description="任务状态")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="更新时间")
    test_cases_count: int = Field(description="测试用例数量")

class TestTasksResponse(BaseModel):
    """测试任务列表响应模型"""
    message: str = Field(description="响应消息")
    tasks: List[TestTaskItem] = Field(description="测试任务列表")

class DockerSetupResponse(BaseModel):
    """Docker容器设置响应模型"""
    message: str = Field(description="响应消息")
    success: bool = Field(description="是否成功")
    task_id: str = Field(description="任务ID")
    container_name: Optional[str] = Field(None, description="容器名称")
    error: Optional[str] = Field(None, description="错误信息")

class TestExecutionResponse(BaseModel):
    """测试执行响应模型"""
    message: str = Field(description="响应消息")
    success: bool = Field(description="是否成功")
    task_id: str = Field(description="任务ID")
    cases_total: int = Field(description="测试用例总数")
    cases_executed: int = Field(description="已执行的测试用例数")
    cases_passed: int = Field(description="通过的测试用例数")
    cases_failed: int = Field(description="失败的测试用例数")
    execution_time: float = Field(description="执行时间(秒)")
    error: Optional[str] = Field(None, description="错误信息")

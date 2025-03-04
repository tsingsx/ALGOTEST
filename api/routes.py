#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：API路由定义，包括测试用例生成接口
开发规划：实现从需求文档直接生成测试用例的功能
"""

import os
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.logger import get_logger
from agents.analysis_agent import read_pdf_content, generate_test_cases as agent_generate_test_cases

# 创建路由器
router = APIRouter(prefix="/api", tags=["tests"])

# 获取日志记录器
log = get_logger("api")

class DocRequest(BaseModel):
    """需求文档请求模型"""
    doc_path: str = Field(..., description="需求文档路径，相对于data/pdfs/目录")


@router.post("/generate-testcases")
async def generate_testcases_from_doc(
    doc_request: DocRequest
):
    """
    直接从需求文档生成测试用例，不创建测试任务
    
    - **doc_path**: 需求文档路径，相对于data/pdfs/目录
    """
    # 检查需求文档是否存在
    full_doc_path = os.path.join("data", "pdfs", doc_request.doc_path)
    if not os.path.exists(full_doc_path):
        raise HTTPException(status_code=404, detail=f"需求文档不存在: {doc_request.doc_path}")
    
    log.info(f"开始从文档生成测试用例: {full_doc_path}")
    
    try:
        # 创建初始状态
        from core.utils import generate_unique_id
        state = {
            "task_id": generate_unique_id("TEMP"),
            "requirement_doc_path": full_doc_path,
            "algorithm_image": "temp_image",  # 临时值，不会实际使用
            "dataset_url": None,
            "pdf_content": None,
            "test_cases": None,
            "errors": [],
            "status": "created"
        }
        
        # 读取PDF内容
        state = read_pdf_content(state)
        if state["status"] == "error":
            raise HTTPException(status_code=500, detail=f"读取PDF内容失败: {state['errors']}")
        
        # 生成测试用例
        state = agent_generate_test_cases(state)
        if state["status"] == "error":
            raise HTTPException(status_code=500, detail=f"生成测试用例失败: {state['errors']}")
        
        # 获取测试用例
        test_cases = state.get("test_cases", [])
        if not test_cases:
            return {"message": "未生成测试用例", "test_cases": []}
        
        # 格式化测试用例数据
        formatted_test_cases = []
        for case in test_cases:
            test_case = {
                "id": case["id"],
                "name": case["name"],
                "purpose": case["purpose"],
                "steps": case["steps"],
                "expected_result": case["expected_result"],
                "validation_method": case["validation_method"]
            }
            formatted_test_cases.append(test_case)
        
        log.success(f"测试用例生成成功，共{len(formatted_test_cases)}个测试用例")
        
        return {
            "message": f"成功从文档生成{len(formatted_test_cases)}个测试用例",
            "test_cases": formatted_test_cases
        }
    except Exception as e:
        log.error(f"生成测试用例异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成测试用例异常: {str(e)}")

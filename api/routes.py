#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：API路由定义，包括测试用例生成接口
开发规划：实现从需求文档直接生成测试用例的功能
"""

import os
import tempfile
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from core.logger import get_logger
from agents.analysis_agent import read_pdf_content, generate_test_cases as agent_generate_test_cases

# 创建路由器
router = APIRouter(prefix="/api", tags=["tests"])

# 获取日志记录器
log = get_logger("api")


@router.post("/generate-testcases")
async def generate_testcases_from_doc(
    file: UploadFile = File(..., description="算法需求文档文件（PDF格式）")
):
    """
    直接从上传的需求文档生成测试用例，不创建测试任务
    
    - **file**: 上传的PDF格式需求文档
    """
    # 检查文件类型
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只支持PDF格式的需求文档")
    
    log.info(f"开始从上传文档生成测试用例: {file.filename}")
    
    try:
        # 创建临时文件保存上传的PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            # 读取上传的文件内容并写入临时文件
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        # 创建初始状态
        from core.utils import generate_unique_id
        state = {
            "task_id": generate_unique_id("TEMP"),
            "requirement_doc_path": temp_file_path,
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
            # 删除临时文件
            os.unlink(temp_file_path)
            raise HTTPException(status_code=500, detail=f"读取PDF内容失败: {state['errors']}")
        
        # 生成测试用例
        state = agent_generate_test_cases(state)
        
        # 删除临时文件
        os.unlink(temp_file_path)
        
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
        # 确保临时文件被删除
        try:
            if 'temp_file_path' in locals():
                os.unlink(temp_file_path)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"生成测试用例异常: {str(e)}")

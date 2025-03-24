#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：报告Agent模块，负责分析测试结果并生成测试报告
开发规划：实现基于大模型的测试结果分析和报告生成功能
"""

import os
import json
from typing import Dict, Any, List, TypedDict, Optional
from datetime import datetime
from loguru import logger
from langgraph.graph import StateGraph
from sqlalchemy.sql import text

from core.config import get_settings, get_llm_config
from core.database import (
    get_db, 
    TestCase,
    update_test_case_status
)
from core.utils import generate_unique_id
from core.logger import get_logger
from core.llm import call_zhipu_api

# 获取带上下文的logger
log = get_logger("report_agent")

class ReportState(TypedDict):
    """报告Agent状态定义"""
    task_id: str  # 任务ID
    test_cases: Optional[List[Dict[str, Any]]]  # 测试用例列表
    analysis_results: Optional[List[Dict[str, Any]]]  # 分析结果列表
    errors: List[str]  # 错误信息
    status: str  # 任务状态


def analyze_test_results(state: ReportState) -> ReportState:
    """
    分析测试结果节点 - 从数据库读取测试用例结果并使用大模型分析
    
    Args:
        state: 当前状态
        
    Returns:
        更新后的状态
    """
    task_id = state['task_id']
    log.info(f"开始分析测试结果: {task_id}")
    
    try:
        # 从数据库获取该任务的所有测试用例
        with get_db() as db:
            cases = db.query(TestCase).filter(TestCase.task_id == task_id).all()
            if not cases:
                raise ValueError(f"未找到任务的测试用例: {task_id}")
            
            log.info(f"找到 {len(cases)} 个测试用例")
            
            # 获取LLM配置
            llm_config = get_llm_config()
            
            # 存储分析结果
            analysis_results = []
            
            # 逐个分析测试用例
            for case in cases:
                log.info(f"分析测试用例: {case.case_id}")
                
                # 提取测试用例数据
                input_data = case.input_data or {}
                expected_output = case.expected_output or {}
                actual_output = case.actual_output
                
                # 构建提示词
                prompt = f"""
                请分析以下测试用例的执行结果，判断测试是否通过，并提供详细的分析依据。

                测试用例信息：
                - 名称: {input_data.get('name', '未命名')}
                - 目的: {input_data.get('purpose', '无')}
                - 测试步骤: {input_data.get('steps', '无')}
                
                预期结果：
                {expected_output.get('expected_result', '无')}
                
                验证方法：
                {expected_output.get('validation_method', '无')}
                
                实际输出：
                {actual_output or '无输出'}
                
                请提供以下内容：
                1. 测试是否通过的判断（true/false）
                2. 详细的分析依据，包括：
                   - 对比预期结果和实际输出的差异
                   - 根据验证方法进行的具体验证过程
                   - 如果测试失败，指出具体的失败原因
                3. 总结性结论
                
                请按以下JSON格式输出：
                {{
                    "is_passed": true/false,
                    "analysis": "详细的分析过程...",
                    "conclusion": "总结性结论..."
                }}
                """
                
                # 调用大模型API
                try:
                    result = call_zhipu_api(prompt, llm_config)
                    
                    # 解析返回的JSON
                    try:
                        # 尝试直接解析
                        analysis_data = json.loads(result)
                    except json.JSONDecodeError:
                        # 如果直接解析失败，尝试从文本中提取JSON
                        import re
                        json_match = re.search(r'\{[\s\S]*\}', result)
                        if json_match:
                            analysis_data = json.loads(json_match.group())
                        else:
                            raise ValueError("无法解析大模型返回的结果")
                    
                    # 更新测试用例的分析结果
                    case.result_analysis = analysis_data.get("analysis", "") + "\n\n" + analysis_data.get("conclusion", "")
                    case.is_passed = analysis_data.get("is_passed", False)
                    
                    # 更新测试用例状态
                    case.status = "completed"
                    
                    # 添加到分析结果列表
                    analysis_results.append({
                        "case_id": case.case_id,
                        "is_passed": case.is_passed,
                        "result_analysis": case.result_analysis
                    })
                    
                    # 提交更改
                    db.commit()
                    log.info(f"测试用例 {case.case_id} 分析完成: {'通过' if case.is_passed else '未通过'}")
                    
                except Exception as e:
                    log.error(f"分析测试用例 {case.case_id} 时出错: {str(e)}")
                    analysis_results.append({
                        "case_id": case.case_id,
                        "error": str(e)
                    })
            
            log.success(f"完成所有测试用例分析: {task_id}")
            
            # 更新状态
            return {
                **state,
                "test_cases": [
                    {
                        "case_id": case.case_id,
                        "input_data": case.input_data,
                        "expected_output": case.expected_output,
                        "actual_output": case.actual_output,
                        "is_passed": case.is_passed,
                        "result_analysis": case.result_analysis
                    }
                    for case in cases
                ],
                "analysis_results": analysis_results,
                "status": "analyzed"
            }
            
    except Exception as e:
        log.error(f"分析测试结果失败: {str(e)}")
        return {
            **state,
            "errors": state.get("errors", []) + [str(e)],
            "status": "error"
        }

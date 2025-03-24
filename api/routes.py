#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：API路由定义，包括文档上传、测试用例生成和管理接口
开发规划：实现低耦合的API接口，便于后期工程化维护
"""

import os
import json
import shutil
import tempfile
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Path, Query, Body, Depends
from pydantic import BaseModel, Field

from core.logger import get_logger
from core.utils import generate_unique_id
from core.database import (
    get_db,
    create_test_task,
    create_test_case,
    TestCase as DBTestCase,
    TestTask as DBTestTask,
    Session,
    update_test_task,
    get_all_test_tasks,
    get_test_task_by_document_id,
    get_test_task,
    update_task_algorithm_image as db_update_algorithm_image,
    update_task_dataset_url as db_update_dataset_url,
    update_task_container_name,
    close_task_session,
    update_test_case_status,
    update_test_task_status
)
from agents.analysis_agent import read_pdf_content, generate_test_cases as agent_generate_test_cases
from agents.execution_agent import (
    setup_algorithm_container, 
    load_test_cases, 
    parse_command, 
    execute_command, 
    save_result
)
from api.models import (
    TestCase, 
    TestCasesResponse, 
    DocumentUploadResponse, 
    DocumentAnalysisRequest,
    TestCaseCreateRequest,
    TestCaseUpdateRequest,
    MessageResponse,
    AlgorithmImageRequest,
    DatasetUrlRequest,
    TestTaskItem,
    TestTasksResponse,
    DockerSetupResponse,
    TestExecutionResponse
)

# 创建路由器
router = APIRouter(prefix="/api", tags=["tests"])

# 获取日志记录器
log = get_logger("api")

# 临时存储上传的文档
# 注意：在实际生产环境中，应该使用数据库存储
DOCUMENTS = {}

def format_test_case(case: DBTestCase) -> TestCase:
    """将数据库测试用例对象转换为API响应模型"""
    input_data = case.input_data or {}
    expected_output = case.expected_output or {}
    return TestCase(
        id=case.case_id,
        name=input_data.get("name", ""),
        purpose=input_data.get("purpose", ""),
        steps=input_data.get("steps", ""),
        expected_result=expected_output.get("expected_result", ""),
        validation_method=expected_output.get("validation_method", ""),
        document_id=case.document_id,
        actual_output=case.actual_output,
        result_analysis=case.result_analysis,
        is_passed=case.is_passed,
        status=case.status or "pending"
    )

# 1. 文档上传接口
@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(..., description="算法需求文档文件（PDF格式）"),
    db: Session = Depends(get_db)
):
    """
    上传算法需求文档
    
    - **file**: 上传的PDF格式需求文档
    
    返回文档ID和存储路径
    """
    # 检查文件类型
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只支持PDF格式的需求文档")
    
    log.info(f"开始上传文档: {file.filename}")
    
    try:
        # 确保目标目录存在
        os.makedirs("data/pdfs", exist_ok=True)
        
        # 生成唯一文档ID
        document_id = generate_unique_id("DOC")
        
        # 构建文件保存路径
        file_path = f"data/pdfs/{document_id}_{file.filename}"
        
        # 读取上传的文件内容并保存
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 为该文档创建一个任务
        task_id = generate_unique_id("TASK")
        task_data = {
            "task_id": task_id,
            "document_id": document_id,  # 添加文档ID
            "requirement_doc": "",  # 暂时不保存文档内容，后续分析时会更新
            "algorithm_image": None,
            "dataset_url": None,
            "status": "created"
        }
        
        # 保存到数据库
        task = DBTestTask(**task_data)
        db.add(task)
        db.commit()
        
        # 存储文档信息
        DOCUMENTS[document_id] = {
            "id": document_id,
            "filename": file.filename,
            "file_path": file_path,
            "task_id": task_id  # 保存任务ID
        }
        
        log.success(f"文档上传成功: {file.filename}, ID: {document_id}, 关联任务ID: {task_id}")
        
        return {
            "message": "文档上传成功",
            "document_id": document_id,
            "filename": file.filename,
            "file_path": file_path
        }
    except Exception as e:
        if 'db' in locals() and db:
            db.rollback()
        log.error(f"文档上传异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"文档上传异常: {str(e)}")


# 2. 文档分析接口
@router.post("/documents/{document_id}/analyze", response_model=TestCasesResponse)
async def analyze_document(
    document_id: str = Path(..., description="文档ID"),
    db: Session = Depends(get_db)
):
    """
    分析文档并生成测试用例
    
    - **document_id**: 文档ID，通过上传接口获取
    
    返回生成的测试用例列表
    """
    # 直接检查文件是否存在
    pdf_dir = "data/pdfs"
    # 在pdf_dir目录下查找以document_id开头的文件
    matching_files = [f for f in os.listdir(pdf_dir) if f.startswith(document_id)]
    
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"文档不存在: {document_id}")
    
    # 使用找到的第一个匹配文件
    file_path = os.path.join(pdf_dir, matching_files[0])
    log.info(f"开始分析文档: {matching_files[0]}, ID: {document_id}")
    
    try:
        # 查找与文档关联的任务
        task = None
        doc_info = DOCUMENTS.get(document_id)
        
        if doc_info and 'task_id' in doc_info:
            # 如果文档信息中有任务ID，获取该任务
            task_id = doc_info['task_id']
            task = db.query(DBTestTask).filter(DBTestTask.task_id == task_id).first()
            log.info(f"找到文档关联的任务: {task_id}")
        
        if not task:
            # 如果没有找到任务，创建一个新任务
            task_id = generate_unique_id("TASK")
            task_data = {
                "task_id": task_id,
                "document_id": document_id,  # 添加文档ID
                "requirement_doc": "",  # 暂时不保存文档内容
                "algorithm_image": "auto_generated",
                "status": "created"
            }
            
            # 创建测试任务
            task = DBTestTask(**task_data)
            db.add(task)
            db.commit()
            db.refresh(task)
            
            # 如果文档信息存在，更新任务ID
            if doc_info:
                doc_info['task_id'] = task_id
            
            log.info(f"为文档创建新任务: {task_id}")
        
        # 创建初始状态
        state = {
            "task_id": task.task_id,
            "requirement_doc_path": file_path,
            "algorithm_image": task.algorithm_image or "temp_image",  # 使用任务中的镜像地址，如果没有则使用临时值
            "dataset_url": task.dataset_url,  # 使用任务中的数据集地址
            "pdf_content": None,
            "test_cases": None,
            "errors": [],
            "status": "created"
        }
        
        # 读取PDF内容
        state = read_pdf_content(state)
        if state["status"] == "error":
            raise HTTPException(status_code=500, detail=f"读取PDF内容失败: {state['errors']}")
        
        # 更新任务的需求文档
        task.requirement_doc = state["pdf_content"]
        db.commit()
        
        # 生成测试用例
        state = agent_generate_test_cases(state)
        
        if state["status"] == "error":
            raise HTTPException(status_code=500, detail=f"生成测试用例失败: {state['errors']}")
        
        # 获取测试用例
        test_cases = state.get("test_cases", [])
        if not test_cases:
            return {"message": "未生成测试用例", "test_cases": []}
        
        # 保存测试用例到数据库并格式化返回数据
        formatted_test_cases = []
        for case in test_cases:
            case_data = {
                "task_id": task.task_id,
                "case_id": case["id"],
                "document_id": document_id,
                "input_data": {
                    "name": case["name"],
                    "purpose": case["purpose"],
                    "steps": case["steps"]
                },
                "expected_output": {
                    "expected_result": case["expected_result"],
                    "validation_method": case["validation_method"]
                }
            }
            # 创建测试用例
            db_case = DBTestCase(**case_data)
            db.add(db_case)
            db.commit()
            db.refresh(db_case)
            formatted_test_cases.append(format_test_case(db_case))
        
        log.success(f"测试用例生成成功，共{len(formatted_test_cases)}个测试用例")
        
        return {
            "message": f"成功从文档生成{len(formatted_test_cases)}个测试用例",
            "test_cases": formatted_test_cases
        }
    except Exception as e:
        db.rollback()  # 发生异常时回滚事务
        log.error(f"分析文档异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"分析文档异常: {str(e)}")


# 3. 获取测试用例列表
@router.get("/testcases", response_model=TestCasesResponse)
async def get_test_cases(
    document_id: Optional[str] = Query(None, description="文档ID，可选"),
    db: Session = Depends(get_db)
):
    """
    获取测试用例列表
    
    - **document_id**: 可选的文档ID，如果提供则只返回该文档的测试用例
    
    返回测试用例列表
    """
    query = db.query(DBTestCase)
    if document_id:
        query = query.filter(DBTestCase.document_id == document_id)
    
    cases = query.all()
    formatted_cases = [format_test_case(case) for case in cases]
    return {
        "message": f"成功获取{len(formatted_cases)}个测试用例",
        "test_cases": formatted_cases
    }


# 4. 获取单个测试用例
@router.get("/testcases/{case_id}", response_model=TestCase)
async def get_test_case(
    case_id: str = Path(..., description="测试用例ID"),
    db: Session = Depends(get_db)
):
    """
    获取单个测试用例详情
    
    - **case_id**: 测试用例ID
    
    返回测试用例详情
    """
    case = db.query(DBTestCase).filter(DBTestCase.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"测试用例不存在: {case_id}")
    
    return format_test_case(case)


# 5. 创建测试用例
@router.post("/testcases", response_model=TestCase)
async def create_test_case_endpoint(
    test_case: TestCaseCreateRequest = Body(..., description="测试用例信息"),
    db: Session = Depends(get_db)
):
    """
    创建新的测试用例
    
    - **test_case**: 测试用例信息
    
    返回创建的测试用例
    """
    case_id = generate_unique_id("TC")
    
    # 创建测试任务（如果不存在）
    task_id = generate_unique_id("TASK")
    task_data = {
        "task_id": task_id,
        "requirement_doc": "",
        "algorithm_image": "manual_created",
        "status": "completed"
    }
    
    # 直接创建测试任务
    task = DBTestTask(**task_data)
    db.add(task)
    db.commit()
    db.refresh(task)
    
    # 创建测试用例
    case_data = {
        "task_id": task_id,
        "case_id": case_id,
        "document_id": test_case.document_id,
        "input_data": {
            "name": test_case.name,
            "purpose": test_case.purpose,
            "steps": test_case.steps
        },
        "expected_output": {
            "expected_result": test_case.expected_result,
            "validation_method": test_case.validation_method
        }
    }
    
    # 直接创建测试用例
    case = DBTestCase(**case_data)
    db.add(case)
    db.commit()
    db.refresh(case)
    
    log.success(f"测试用例创建成功: {case_id}")
    
    return format_test_case(case)


# 6. 更新测试用例
@router.put("/testcases/{case_id}", response_model=TestCase)
async def update_test_case(
    case_id: str = Path(..., description="测试用例ID"),
    test_case: TestCaseUpdateRequest = Body(..., description="测试用例更新信息"),
    db: Session = Depends(get_db)
):
    """
    更新测试用例
    
    - **case_id**: 测试用例ID
    - **test_case**: 测试用例更新信息
    
    返回更新后的测试用例
    """
    case = db.query(DBTestCase).filter(DBTestCase.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"测试用例不存在: {case_id}")
    
    # 更新非空字段
    update_data = test_case.dict(exclude_unset=True)
    if update_data:
        # 更新document_id
        if "document_id" in update_data:
            case.document_id = update_data["document_id"]
            
        input_data = dict(case.input_data)
        expected_output = dict(case.expected_output)
        
        # 更新input_data
        for key in ["name", "purpose", "steps"]:
            if key in update_data:
                input_data[key] = update_data[key]
        
        # 更新expected_output
        for key in ["expected_result", "validation_method"]:
            if key in update_data:
                expected_output[key] = update_data[key]
        
        case.input_data = input_data
        case.expected_output = expected_output
        db.commit()
        db.refresh(case)
    
    log.success(f"测试用例更新成功: {case_id}")
    return format_test_case(case)


# 7. 删除测试用例
@router.delete("/testcases/{case_id}", response_model=MessageResponse)
async def delete_test_case(
    case_id: str = Path(..., description="测试用例ID"),
    db: Session = Depends(get_db)
):
    """
    删除测试用例
    
    - **case_id**: 测试用例ID
    
    返回删除结果
    """
    case = db.query(DBTestCase).filter(DBTestCase.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"测试用例不存在: {case_id}")
    
    db.delete(case)
    db.commit()
    
    log.success(f"测试用例删除成功: {case_id}")
    return {"message": f"测试用例删除成功: {case_id}"}


# 8. 兼容旧接口 - 直接从上传文档生成测试用例
@router.post("/generate-testcases", response_model=TestCasesResponse)
async def generate_testcases_from_doc(
    file: UploadFile = File(..., description="算法需求文档文件（PDF格式）"),
    db: Session = Depends(get_db)
):
    """
    直接从上传的需求文档生成测试用例，不创建测试任务
    
    - **file**: 上传的PDF格式需求文档
    
    返回生成的测试用例列表
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
        
        # 生成唯一文档ID
        document_id = generate_unique_id("DOC")
        
        # 创建测试任务
        task_id = generate_unique_id("TASK")
        task_data = {
            "task_id": task_id,
            "document_id": document_id,  # 添加文档ID
            "requirement_doc": "",  # 暂时不保存文档内容
            "algorithm_image": "auto_generated",
            "status": "created"
        }
        
        # 创建测试任务
        task = DBTestTask(**task_data)
        db.add(task)
        db.commit()
        db.refresh(task)
        
        # 创建初始状态
        state = {
            "task_id": task_id,
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
        
        # 更新任务的需求文档
        task.requirement_doc = state["pdf_content"]
        db.commit()
        
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
        
        # 保存测试用例到数据库并格式化返回数据
        formatted_test_cases = []
        for case in test_cases:
            case_data = {
                "task_id": task_id,
                "case_id": case["id"],
                "document_id": document_id,
                "input_data": {
                    "name": case["name"],
                    "purpose": case["purpose"],
                    "steps": case["steps"]
                },
                "expected_output": {
                    "expected_result": case["expected_result"],
                    "validation_method": case["validation_method"]
                }
            }
            db_case = DBTestCase(**case_data)
            db.add(db_case)
            db.commit()
            db.refresh(db_case)
            formatted_test_cases.append(format_test_case(db_case))
        
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


# 添加算法镜像地址
@router.post("/tasks/{task_id}/algorithm-image", response_model=MessageResponse)
async def update_task_algorithm_image(
    task_id: str = Path(..., description="任务ID"),
    request: AlgorithmImageRequest = Body(..., description="算法镜像信息"),
    db: Session = Depends(get_db)
):
    """
    通过任务ID更新算法镜像地址
    
    - **task_id**: 任务ID
    - **request**: 包含算法镜像地址的请求
    
    返回成功消息
    """
    log.info(f"开始更新任务的算法镜像地址: {request.algorithm_image}, 任务ID: {task_id}")
    
    try:
        # 使用专用函数更新算法镜像地址
        task = db_update_algorithm_image(task_id, request.algorithm_image)
        
        if task:
            log.info(f"更新任务 {task_id} 的算法镜像地址")
            return {"message": f"算法镜像地址已成功更新: {request.algorithm_image}"}
        else:
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    except Exception as e:
        log.error(f"更新算法镜像地址异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新算法镜像地址异常: {str(e)}")


# 添加数据集地址
@router.post("/tasks/{task_id}/dataset-url", response_model=MessageResponse)
async def update_task_dataset_url(
    task_id: str = Path(..., description="任务ID"),
    request: DatasetUrlRequest = Body(..., description="数据集信息"),
    db: Session = Depends(get_db)
):
    """
    通过任务ID更新数据集地址
    
    - **task_id**: 任务ID
    - **request**: 包含数据集地址的请求
    
    返回成功消息
    """
    log.info(f"开始更新任务的数据集地址: {request.dataset_url}, 任务ID: {task_id}")
    
    try:
        # 使用专用函数更新数据集URL
        task = db_update_dataset_url(task_id, request.dataset_url)
        
        if task:
            log.info(f"更新任务 {task_id} 的数据集地址")
            return {"message": f"数据集地址已成功更新: {request.dataset_url}"}
        else:
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    except Exception as e:
        log.error(f"更新数据集地址异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新数据集地址异常: {str(e)}")


# 添加文档任务信息查询接口
@router.get("/documents/{document_id}/task-info", response_model=Dict[str, Any])
async def get_document_task_info(
    document_id: str = Path(..., description="文档ID"),
    db: Session = Depends(get_db)
):
    """
    获取文档关联的任务信息
    
    - **document_id**: 文档ID
    
    返回文档关联的任务信息，包括算法镜像地址和数据集URL
    """
    # 检查文档是否存在
    pdf_dir = "data/pdfs"
    matching_files = [f for f in os.listdir(pdf_dir) if f.startswith(document_id)]
    
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"文档不存在: {document_id}")
    
    log.info(f"查询文档关联的任务信息: 文档ID={document_id}")
    
    try:
        # 查找与文档关联的任务
        task = None
        task_id = None
        doc_info = DOCUMENTS.get(document_id)
        
        if doc_info and 'task_id' in doc_info:
            # 如果文档信息中有任务ID，获取该任务ID
            task_id = doc_info['task_id']
            # 查询任务
            task = db.query(DBTestTask).filter(DBTestTask.task_id == task_id).first()
        
        if not task:
            # 如果没有找到直接关联的任务，尝试通过测试用例找到关联的任务
            test_cases = db.query(DBTestCase).filter(DBTestCase.document_id == document_id).all()
            if test_cases:
                # 获取第一个测试用例的任务ID
                task_id = test_cases[0].task_id
                # 查询任务
                task = db.query(DBTestTask).filter(DBTestTask.task_id == task_id).first()
        
        if task:
            # 如果找到任务，返回任务信息
            result = {
                "document_id": document_id,
                "task_id": task.task_id,
                "algorithm_image": task.algorithm_image,
                "dataset_url": task.dataset_url,
                "status": task.status,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None
            }
            
            # 如果有文档信息，添加到结果中
            if doc_info:
                result["filename"] = doc_info.get("filename")
                result["file_path"] = doc_info.get("file_path")
            
            return result
        else:
            # 如果仍未找到任务，返回一个基本的文档信息
            result = {
                "document_id": document_id,
                "task_id": None,
                "algorithm_image": None,
                "dataset_url": None,
                "status": "unknown"
            }
            
            # 如果有文档信息，添加到结果中
            if doc_info:
                result["filename"] = doc_info.get("filename")
                result["file_path"] = doc_info.get("file_path")
            
            return result
            
    except Exception as e:
        log.error(f"查询文档任务信息异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询文档任务信息异常: {str(e)}")


@router.get("/tasks", response_model=TestTasksResponse)
async def get_all_tasks():
    """
    获取所有测试任务
    
    返回数据库中所有测试任务的列表。
    
    Returns:
        TestTasksResponse: 包含测试任务列表的响应
    """
    log.info("获取所有测试任务")
    
    try:
        # 调用数据库函数获取所有测试任务
        tasks = get_all_test_tasks()
        
        return TestTasksResponse(
            message="成功获取所有测试任务",
            tasks=tasks
        )
    except Exception as e:
        log.error(f"获取所有测试任务失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取测试任务失败: {str(e)}"
        )


# 开始任务执行前准备Docker容器
@router.post("/tasks/{task_id}/prepare", response_model=DockerSetupResponse)
async def prepare_task_execution(
    task_id: str = Path(..., description="任务ID")
):
    """
    为测试任务执行准备Docker容器环境
    
    该接口会基于任务信息设置Docker容器，为后续的测试执行做准备。
    它会从数据库获取algorithm_image和dataset_url，然后通过MCP在远程服务器上设置Docker容器。
    
    - **task_id**: 任务ID
    
    返回Docker容器设置结果
    """
    log.info(f"开始为任务 {task_id} 准备Docker环境")
    
    try:
        # 获取任务信息验证
        task = get_test_task(task_id)
        if not task:
            log.error(f"任务不存在: {task_id}")
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
            
        if not task.algorithm_image:
            log.error(f"任务 {task_id} 未配置算法镜像")
            raise HTTPException(status_code=400, detail=f"未配置算法镜像，请先设置算法镜像")
        
        # 调用执行函数设置Docker容器
        log.info(f"开始为任务 {task_id} 设置Docker容器，算法镜像: {task.algorithm_image}")
        result = await setup_algorithm_container(task_id)
        
        log.info(f"Docker容器设置结果: success={result.get('success')}")
        
        # 返回响应
        if result.get("success"):
            container_name = result.get("container_name")
            log.success(f"Docker容器设置成功: {container_name}")
            
            # 更新任务的容器名称
            log.info(f"更新任务 {task_id} 的容器名称: {container_name}")
            update_task_container_name(task_id, container_name)
            
            return {
                "message": "Docker容器设置成功",
                "success": True,
                "task_id": task_id,
                "container_name": container_name,
                "error": None
            }
        else:
            error_message = result.get("error", "未知错误")
            log.error(f"Docker容器设置失败: {error_message}")
            raise HTTPException(
                status_code=500, 
                detail=f"Docker容器设置失败: {error_message}"
            )
    except HTTPException:
        # 直接重新抛出HTTP异常
        raise
    except Exception as e:
        log.error(f"准备Docker环境失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"准备Docker环境失败: {str(e)}")


# 执行测试任务
@router.post("/tasks/{task_id}/execute", response_model=TestExecutionResponse)
async def execute_task_tests(
    task_id: str = Path(..., description="任务ID")
):
    """
    执行测试任务的所有测试用例
    
    该接口会执行指定任务的所有测试用例，并自动完成测试用例的加载、命令解析、命令执行和结果保存等步骤。
    
    - **task_id**: 任务ID
    
    返回测试执行结果，包括测试用例的执行情况统计
    """
    log.info(f"开始执行任务测试: {task_id}")
    
    start_time = time.time()
    
    try:
        # 获取任务信息验证
        task = get_test_task(task_id)
        if not task:
            log.error(f"任务不存在: {task_id}")
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
            
        # 初始化状态
        state = {
            "task_id": task_id,
            "current_case_index": 0,
            "test_cases": [],
            "command_strategies": None, 
            "current_strategy_index": 0,
            "status": "created",
            "errors": [],
            "container_ready": True  # 假设容器已准备好
        }
        
        # 统计数据
        cases_total = 0
        cases_executed = 0
        cases_passed = 0
        cases_failed = 0
        error_messages = []
        
        # 第一步：加载测试用例
        log.info(f"步骤1: 加载测试用例 - 任务ID: {task_id}")
        load_result = load_test_cases(state)
        if not load_result or load_result.get("status") == "error":
            error_msg = f"加载测试用例失败: {load_result.get('errors', ['未知错误'])}"
            log.error(error_msg)
            return {
                "message": error_msg,
                "success": False,
                "task_id": task_id,
                "cases_total": 0,
                "cases_executed": 0,
                "cases_passed": 0,
                "cases_failed": 0,
                "execution_time": time.time() - start_time,
                "error": error_msg
            }
            
        test_cases = load_result.get('test_cases', [])
        if not test_cases:
            log.error("未找到测试用例")
            return {
                "message": "未找到测试用例",
                "success": False,
                "task_id": task_id,
                "cases_total": 0,
                "cases_executed": 0,
                "cases_passed": 0,
                "cases_failed": 0,
                "execution_time": time.time() - start_time,
                "error": "未找到测试用例"
            }
            
        log.info(f"成功加载测试用例，共 {len(test_cases)} 个")
        cases_total = len(test_cases)
        state = load_result
        
        # 逐个执行测试用例
        for i, case in enumerate(test_cases):
            case_id = case.get('case_id')
            if not case_id:
                log.error("测试用例缺少case_id字段")
                error_messages.append("测试用例缺少case_id字段")
                continue
                
            log.info(f"正在处理测试用例 {i+1}/{len(test_cases)}: {case_id}")
            
            # 更新当前用例索引
            state['current_case_index'] = i
            state['case_id'] = case_id
            
            try:
                # 解析命令
                log.info(f"解析测试用例命令: {case_id}")
                parse_result = await parse_command(state)
                if not parse_result or parse_result.get("status") != "parsed":
                    log.error(f"命令解析失败: {case_id}")
                    cases_failed += 1
                    continue
                    
                state = parse_result
                
                # 执行命令
                log.info(f"执行测试用例命令: {case_id}")
                execute_result = await execute_command(state)
                if not execute_result or execute_result.get("status") != "executed":
                    log.error(f"命令执行失败: {case_id}")
                    cases_failed += 1
                    continue
                
                state = execute_result
                
                # 获取执行结果
                execution_result = state.get('execution_result', {})
                success = execution_result.get('success', False)
                
                if success:
                    cases_passed += 1
                else:
                    cases_failed += 1
                
                # 保存结果
                log.info(f"保存测试用例结果: {case_id}")
                save_result_state = await save_result(state)
                if not save_result_state:
                    log.error(f"保存结果失败: {case_id}")
                    error_messages.append(f"保存结果失败: {case_id}")
                else:
                    cases_executed += 1
                    state = save_result_state
                
            except Exception as e:
                log.error(f"处理测试用例 {case_id} 时出错: {str(e)}")
                error_messages.append(f"处理测试用例 {case_id} 时出错: {str(e)}")
                cases_failed += 1
        
        # 计算总执行时间
        execution_time = time.time() - start_time
        
        # 更新任务状态为已完成
        with get_db() as db:
            # 更新测试任务状态
            update_test_task_status(
                task_id=task_id,
                status="completed"
            )
        
        # 组装最终响应
        message = f"测试执行完成，共 {cases_total} 个测试用例，成功 {cases_passed} 个，失败 {cases_failed} 个"
        log.success(message)
        
        return {
            "message": message,
            "success": cases_failed == 0 and cases_executed > 0,
            "task_id": task_id,
            "cases_total": cases_total,
            "cases_executed": cases_executed,
            "cases_passed": cases_passed,
            "cases_failed": cases_failed,
            "execution_time": execution_time,
            "error": "; ".join(error_messages) if error_messages else None
        }
    except Exception as e:
        log.error(f"执行测试任务时出错: {str(e)}")
        import traceback
        log.error(traceback.format_exc())
        
        return {
            "message": f"执行测试任务时出错: {str(e)}",
            "success": False,
            "task_id": task_id,
            "cases_total": 0,
            "cases_executed": 0,
            "cases_passed": 0,
            "cases_failed": 0,
            "execution_time": time.time() - start_time,
            "error": str(e)
        }

# 执行单个测试用例
@router.post("/testcases/{case_id}/execute", response_model=TestExecutionResponse)
async def execute_single_test_case(
    case_id: str = Path(..., description="测试用例ID"),
    db: Session = Depends(get_db)
):
    """
    执行单个测试用例
    
    该接口会执行指定的单个测试用例，并自动完成命令解析、命令执行和结果保存等步骤。
    
    - **case_id**: 测试用例ID
    
    返回测试执行结果
    """
    log.info(f"开始执行单个测试用例: {case_id}")
    
    start_time = time.time()
    
    try:
        # 获取测试用例信息
        case = db.query(DBTestCase).filter(DBTestCase.case_id == case_id).first()
        if not case:
            raise HTTPException(status_code=404, detail=f"测试用例不存在: {case_id}")
            
        # 获取任务ID
        task_id = case.task_id
        
        # 初始化状态
        state = {
            "task_id": task_id,
            "case_id": case_id,  # 指定测试用例ID
            "current_case_index": 0,
            "test_cases": [],
            "command_strategies": None, 
            "current_strategy_index": 0,
            "status": "created",
            "errors": [],
            "container_ready": True  # 假设容器已准备好
        }
        
        cases_passed = 0
        cases_failed = 0
        error_message = None
        
        # 加载指定的测试用例
        log.info(f"加载测试用例: {case_id}")
        load_result = load_test_cases(state)
        if not load_result or load_result.get("status") == "error":
            error_msg = f"加载测试用例失败: {load_result.get('errors', ['未知错误'])}"
            log.error(error_msg)
            return {
                "message": error_msg,
                "success": False,
                "task_id": task_id,
                "cases_total": 1,
                "cases_executed": 0,
                "cases_passed": 0,
                "cases_failed": 1,
                "execution_time": time.time() - start_time,
                "error": error_msg
            }
            
        test_cases = load_result.get('test_cases', [])
        if not test_cases:
            log.error(f"未找到测试用例: {case_id}")
            return {
                "message": f"未找到测试用例: {case_id}",
                "success": False,
                "task_id": task_id,
                "cases_total": 1,
                "cases_executed": 0,
                "cases_passed": 0,
                "cases_failed": 1,
                "execution_time": time.time() - start_time,
                "error": f"未找到测试用例: {case_id}"
            }
            
        log.info(f"成功加载测试用例: {case_id}")
        state = load_result
        
        try:
            # 解析命令
            log.info(f"解析测试用例命令: {case_id}")
            parse_result = await parse_command(state)
            if not parse_result or parse_result.get("status") != "parsed":
                error_msg = f"命令解析失败: {case_id}"
                log.error(error_msg)
                cases_failed = 1
                error_message = error_msg
            else:
                state = parse_result
                
                # 执行命令
                log.info(f"执行测试用例命令: {case_id}")
                execute_result = await execute_command(state)
                if not execute_result or execute_result.get("status") != "executed":
                    error_msg = f"命令执行失败: {case_id}"
                    log.error(error_msg)
                    cases_failed = 1
                    error_message = error_msg
                else:
                    state = execute_result
                    
                    # 获取执行结果
                    execution_result = state.get('execution_result', {})
                    success = execution_result.get('success', False)
                    
                    if success:
                        cases_passed = 1
                    else:
                        cases_failed = 1
                        error_message = execution_result.get('error', '未知错误')
                    
                    # 保存结果
                    log.info(f"保存测试用例结果: {case_id}")
                    save_result_state = await save_result(state)
                    if not save_result_state:
                        error_msg = f"保存结果失败: {case_id}"
                        log.error(error_msg)
                        if not error_message:
                            error_message = error_msg
        except Exception as e:
            log.error(f"处理测试用例 {case_id} 时出错: {str(e)}")
            cases_failed = 1
            error_message = str(e)
        
        # 计算总执行时间
        execution_time = time.time() - start_time
        
        # 组装最终响应
        cases_executed = cases_passed + cases_failed
        message = f"测试用例 {case_id} 执行{'成功' if cases_passed == 1 else '失败'}"
        log.info(message)
        
        return {
            "message": message,
            "success": cases_passed == 1,
            "task_id": task_id,
            "cases_total": 1,
            "cases_executed": cases_executed,
            "cases_passed": cases_passed,
            "cases_failed": cases_failed,
            "execution_time": execution_time,
            "error": error_message
        }
    except Exception as e:
        log.error(f"执行测试用例时出错: {str(e)}")
        import traceback
        log.error(traceback.format_exc())
        
        return {
            "message": f"执行测试用例时出错: {str(e)}",
            "success": False,
            "task_id": "unknown",
            "cases_total": 1,
            "cases_executed": 0,
            "cases_passed": 0,
            "cases_failed": 1,
            "execution_time": time.time() - start_time,
            "error": str(e)
        }

# 查询任务测试状态
@router.get("/tasks/{task_id}/status", response_model=Dict[str, Any])
async def get_task_test_status(
    task_id: str = Path(..., description="任务ID"),
    db: Session = Depends(get_db)
):
    """
    查询任务的测试状态
    
    该接口返回指定任务的测试状态，包括总体进度和各测试用例的详细状态。
    
    - **task_id**: 任务ID
    
    返回任务测试状态信息
    """
    log.info(f"查询任务测试状态: {task_id}")
    
    try:
        # 获取任务信息
        task = get_test_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
            
        # 获取任务的所有测试用例
        cases = db.query(DBTestCase).filter(DBTestCase.task_id == task_id).all()
        
        # 统计测试用例状态
        total_cases = len(cases)
        completed_cases = 0
        passed_cases = 0
        failed_cases = 0
        pending_cases = 0
        
        case_details = []
        
        for case in cases:
            case_info = {
                "case_id": case.case_id,
                "status": case.status or "pending",
                "is_passed": case.is_passed,
                "result_analysis": case.result_analysis,
                "has_output": bool(case.actual_output)
            }
            
            case_details.append(case_info)
            
            # 统计不同状态的用例数量
            if case.status == "completed":
                completed_cases += 1
                if case.is_passed:
                    passed_cases += 1
                else:
                    failed_cases += 1
            elif case.status == "failed":
                completed_cases += 1
                failed_cases += 1
            else:
                pending_cases += 1
        
        # 计算整体进度百分比
        progress = (completed_cases / total_cases * 100) if total_cases > 0 else 0
        
        # 组装响应
        response = {
            "task_id": task_id,
            "status": task.status,
            "total_cases": total_cases,
            "completed_cases": completed_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "pending_cases": pending_cases,
            "progress_percent": round(progress, 2),
            "case_details": case_details,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None
        }
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"查询任务测试状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询任务测试状态失败: {str(e)}")

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
    update_test_task
)
from agents.analysis_agent import read_pdf_content, generate_test_cases as agent_generate_test_cases
from api.models import (
    TestCase, 
    TestCasesResponse, 
    DocumentUploadResponse, 
    DocumentAnalysisRequest,
    TestCaseCreateRequest,
    TestCaseUpdateRequest,
    MessageResponse,
    AlgorithmImageRequest,
    DatasetUrlRequest
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
        document_id=case.document_id
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
        
        # 创建测试任务
        task_id = generate_unique_id("TASK")
        task_data = {
            "task_id": task_id,
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
                "document_id": task_id,
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
@router.post("/documents/{document_id}/algorithm-image", response_model=MessageResponse)
async def upload_algorithm_image(
    document_id: str = Path(..., description="文档ID"),
    request: AlgorithmImageRequest = Body(..., description="算法镜像信息"),
    db: Session = Depends(get_db)
):
    """
    上传算法镜像地址
    
    - **document_id**: 文档ID
    - **algorithm_image**: 算法镜像地址
    
    返回更新成功消息
    """
    # 检查文档是否存在
    pdf_dir = "data/pdfs"
    matching_files = [f for f in os.listdir(pdf_dir) if f.startswith(document_id)]
    
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"文档不存在: {document_id}")
    
    log.info(f"开始上传算法镜像地址: 文档ID={document_id}, 镜像={request.algorithm_image}")
    
    try:
        # 查找与文档关联的测试任务
        query = db.query(DBTestTask)
        
        # 先查找该文档对应的测试用例
        test_cases = db.query(DBTestCase).filter(DBTestCase.document_id == document_id).all()
        if test_cases:
            # 如果有测试用例，获取这些用例关联的任务
            task_ids = set(case.task_id for case in test_cases)
            if task_ids:
                # 更新这些任务的算法镜像地址
                for task_id in task_ids:
                    task = db.query(DBTestTask).filter(DBTestTask.task_id == task_id).first()
                    if task:
                        task.algorithm_image = request.algorithm_image
                        log.info(f"更新任务 {task_id} 的算法镜像地址为 {request.algorithm_image}")
                db.commit()
                return {"message": f"已更新{len(task_ids)}个测试任务的算法镜像地址: {request.algorithm_image}"}
        
        # 如果没有找到关联的任务，则尝试查找只有document_id但没有关联测试用例的任务
        # 这种情况可能是先上传了文档，但还没有生成测试用例
        
        # 获取该文档ID对应的任务信息（从DOCUMENTS中）
        doc_info = DOCUMENTS.get(document_id)
        if doc_info:
            # 查找或创建与该文档相关联的任务
            task = None
            # 检查是否有已创建的任务保存在DOCUMENTS中
            if 'task_id' in doc_info:
                task = db.query(DBTestTask).filter(DBTestTask.task_id == doc_info['task_id']).first()
            
            if task:
                # 如果找到了任务，更新它
                task.algorithm_image = request.algorithm_image
                log.info(f"更新文档 {document_id} 关联的任务 {task.task_id} 的算法镜像地址")
            else:
                # 如果没有找到任务，创建一个新的
                task_id = generate_unique_id("TASK")
                task_data = {
                    "task_id": task_id,
                    "requirement_doc": "",  # 暂时不保存文档内容
                    "algorithm_image": request.algorithm_image,
                    "status": "created"
                }
                task = DBTestTask(**task_data)
                db.add(task)
                # 保存任务ID到文档信息中
                doc_info['task_id'] = task_id
                log.info(f"为文档 {document_id} 创建新任务 {task_id} 并设置算法镜像地址")
            
            db.commit()
            return {"message": f"算法镜像地址已成功保存: {request.algorithm_image}"}
        else:
            # 如果没有找到文档信息，创建一个新的任务
            task_id = generate_unique_id("TASK")
            task_data = {
                "task_id": task_id,
                "requirement_doc": "",
                "algorithm_image": request.algorithm_image,
                "status": "created"
            }
            task = DBTestTask(**task_data)
            db.add(task)
            db.commit()
            
            # 创建文档信息并保存任务ID
            DOCUMENTS[document_id] = {
                'id': document_id,
                'task_id': task_id,
                'filename': f"unknown_{document_id}.pdf",
                'file_path': f"data/pdfs/{document_id}_unknown.pdf"
            }
            
            log.info(f"为文档 {document_id} 创建新任务 {task_id} 并设置算法镜像地址")
            return {"message": f"算法镜像地址已成功保存: {request.algorithm_image}"}
        
    except Exception as e:
        db.rollback()
        log.error(f"上传算法镜像地址异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传算法镜像地址异常: {str(e)}")


# 添加数据集地址
@router.post("/documents/{document_id}/dataset-url", response_model=MessageResponse)
async def upload_dataset_url(
    document_id: str = Path(..., description="文档ID"),
    request: DatasetUrlRequest = Body(..., description="数据集信息"),
    db: Session = Depends(get_db)
):
    """
    上传数据集地址
    
    - **document_id**: 文档ID
    - **dataset_url**: 数据集地址
    
    返回更新成功消息
    """
    # 检查文档是否存在
    pdf_dir = "data/pdfs"
    matching_files = [f for f in os.listdir(pdf_dir) if f.startswith(document_id)]
    
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"文档不存在: {document_id}")
    
    log.info(f"开始上传数据集地址: 文档ID={document_id}, 数据集={request.dataset_url}")
    
    try:
        # 查找与文档关联的测试任务
        query = db.query(DBTestTask)
        
        # 先查找该文档对应的测试用例
        test_cases = db.query(DBTestCase).filter(DBTestCase.document_id == document_id).all()
        if test_cases:
            # 如果有测试用例，获取这些用例关联的任务
            task_ids = set(case.task_id for case in test_cases)
            if task_ids:
                # 更新这些任务的数据集地址
                for task_id in task_ids:
                    task = db.query(DBTestTask).filter(DBTestTask.task_id == task_id).first()
                    if task:
                        task.dataset_url = request.dataset_url
                        log.info(f"更新任务 {task_id} 的数据集地址为 {request.dataset_url}")
                db.commit()
                return {"message": f"已更新{len(task_ids)}个测试任务的数据集地址: {request.dataset_url}"}
        
        # 如果没有找到关联的任务，则尝试查找只有document_id但没有关联测试用例的任务
        # 这种情况可能是先上传了文档，但还没有生成测试用例
        
        # 获取该文档ID对应的任务信息（从DOCUMENTS中）
        doc_info = DOCUMENTS.get(document_id)
        if doc_info:
            # 查找或创建与该文档相关联的任务
            task = None
            # 检查是否有已创建的任务保存在DOCUMENTS中
            if 'task_id' in doc_info:
                task = db.query(DBTestTask).filter(DBTestTask.task_id == doc_info['task_id']).first()
            
            if task:
                # 如果找到了任务，更新它
                task.dataset_url = request.dataset_url
                log.info(f"更新文档 {document_id} 关联的任务 {task.task_id} 的数据集地址")
            else:
                # 如果没有找到任务，创建一个新的
                task_id = generate_unique_id("TASK")
                task_data = {
                    "task_id": task_id,
                    "requirement_doc": "",  # 暂时不保存文档内容
                    "dataset_url": request.dataset_url,
                    "status": "created"
                }
                task = DBTestTask(**task_data)
                db.add(task)
                # 保存任务ID到文档信息中
                doc_info['task_id'] = task_id
                log.info(f"为文档 {document_id} 创建新任务 {task_id} 并设置数据集地址")
            
            db.commit()
            return {"message": f"数据集地址已成功保存: {request.dataset_url}"}
        else:
            # 如果没有找到文档信息，创建一个新的任务
            task_id = generate_unique_id("TASK")
            task_data = {
                "task_id": task_id,
                "requirement_doc": "",
                "dataset_url": request.dataset_url,
                "status": "created"
            }
            task = DBTestTask(**task_data)
            db.add(task)
            db.commit()
            
            # 创建文档信息并保存任务ID
            DOCUMENTS[document_id] = {
                'id': document_id,
                'task_id': task_id,
                'filename': f"unknown_{document_id}.pdf",
                'file_path': f"data/pdfs/{document_id}_unknown.pdf"
            }
            
            log.info(f"为文档 {document_id} 创建新任务 {task_id} 并设置数据集地址")
            return {"message": f"数据集地址已成功保存: {request.dataset_url}"}
        
    except Exception as e:
        db.rollback()
        log.error(f"上传数据集地址异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传数据集地址异常: {str(e)}")


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

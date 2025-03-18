#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：数据库模型和操作模块，定义数据库表结构和提供数据库操作接口
开发规划：使用SQLAlchemy ORM实现数据库操作，支持测试任务、测试用例、测试结果和测试报告的存储和查询
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session

from core.config import get_settings
from core.logger import get_logger

# 获取日志记录器
logger = get_logger("database")

# 创建基类
Base = declarative_base()

# 创建数据库引擎
settings = get_settings()
engine = create_engine(settings.db_url)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class TestTask(Base):
    """测试任务模型"""
    __tablename__ = "test_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(50), unique=True, index=True)
    requirement_doc = Column(Text)
    algorithm_image = Column(String(255))
    dataset_url = Column(String(255), nullable=True)  # 数据集URL
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    test_cases = relationship("TestCase", back_populates="task", cascade="all, delete-orphan")
    test_results = relationship("TestResult", back_populates="task", cascade="all, delete-orphan")
    test_report = relationship("TestReport", back_populates="task", uselist=False, cascade="all, delete-orphan")

class TestCase(Base):
    """测试用例模型"""
    __tablename__ = "test_cases"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(50), ForeignKey("test_tasks.task_id", ondelete="CASCADE"))
    case_id = Column(String(50), unique=True, index=True)
    document_id = Column(String(50), index=True)
    input_data = Column(JSON)
    expected_output = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # 关系
    task = relationship("TestTask", back_populates="test_cases")
    test_result = relationship("TestResult", back_populates="test_case", uselist=False, cascade="all, delete-orphan")

class TestResult(Base):
    """测试结果模型"""
    __tablename__ = "test_results"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(50), ForeignKey("test_tasks.task_id", ondelete="CASCADE"))
    case_id = Column(String(50), ForeignKey("test_cases.case_id", ondelete="CASCADE"))
    actual_output = Column(JSON, nullable=True)
    is_passed = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    execution_time = Column(Integer)  # 毫秒
    created_at = Column(DateTime, default=datetime.now)
    
    # 关系
    task = relationship("TestTask", back_populates="test_results")
    test_case = relationship("TestCase", back_populates="test_result")

class TestReport(Base):
    """测试报告模型"""
    __tablename__ = "test_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(50), ForeignKey("test_tasks.task_id", ondelete="CASCADE"), unique=True)
    report_content = Column(Text)
    summary = Column(Text)
    total_cases = Column(Integer)
    passed_cases = Column(Integer)
    failed_cases = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)
    
    # 关系
    task = relationship("TestTask", back_populates="test_report")

def init_db():
    """初始化数据库，创建所有表（警告：会删除所有现有数据）"""
    logger.info("初始化数据库...")
    # 删除所有现有的表
    Base.metadata.drop_all(bind=engine)
    # 创建所有表
    Base.metadata.create_all(bind=engine)
    logger.info("数据库初始化完成")

def ensure_db():
    """确保数据库表存在，但不删除现有数据"""
    logger.info("检查数据库表结构...")
    # 只创建不存在的表，不会删除或修改现有的表
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表结构检查完成")

def get_db() -> Session:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        return db
    except Exception as e:
        logger.error(f"获取数据库会话失败: {str(e)}")
        db.close()
        raise

# 数据库操作函数
def create_test_task(task_data: Dict[str, Any], db: Session = None) -> TestTask:
    """
    创建测试任务
    
    Args:
        task_data: 测试任务数据
        db: 数据库会话，如果不提供则创建新会话
        
    Returns:
        TestTask: 创建的测试任务对象
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        task = TestTask(**task_data)
        db.add(task)
        db.commit()
        db.refresh(task)
        logger.info(f"创建测试任务: {task.task_id}")
        return task
    except Exception as e:
        db.rollback()
        logger.error(f"创建测试任务失败: {str(e)}")
        raise
    finally:
        if close_db:
            db.close()

def get_test_task(task_id: str) -> Optional[TestTask]:
    """
    获取测试任务
    
    Args:
        task_id: 测试任务ID
        
    Returns:
        TestTask: 测试任务对象，不存在返回None
    """
    with get_db() as db:
        task = db.query(TestTask).filter(TestTask.task_id == task_id).first()
        return task

def update_test_task(task_id: str, update_data: Dict[str, Any]) -> Optional[TestTask]:
    """
    更新测试任务
    
    Args:
        task_id: 测试任务ID
        update_data: 更新数据
        
    Returns:
        TestTask: 更新后的测试任务对象，不存在返回None
    """
    with get_db() as db:
        task = db.query(TestTask).filter(TestTask.task_id == task_id).first()
        if task:
            for key, value in update_data.items():
                setattr(task, key, value)
            db.commit()
            db.refresh(task)
            logger.info(f"更新测试任务: {task_id}")
        return task

def create_test_case(case_data: Dict[str, Any], db: Session = None) -> TestCase:
    """
    创建测试用例
    
    Args:
        case_data: 测试用例数据
        db: 数据库会话，如果不提供则创建新会话
        
    Returns:
        TestCase: 创建的测试用例对象
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        case = TestCase(**case_data)
        db.add(case)
        db.commit()
        db.refresh(case)
        logger.info(f"创建测试用例: {case.case_id}")
        return case
    except Exception as e:
        db.rollback()
        logger.error(f"创建测试用例失败: {str(e)}")
        raise
    finally:
        if close_db:
            db.close()

def create_test_result(result_data: Dict[str, Any]) -> TestResult:
    """
    创建测试结果
    
    Args:
        result_data: 测试结果数据
        
    Returns:
        TestResult: 创建的测试结果对象
    """
    with get_db() as db:
        result = TestResult(**result_data)
        db.add(result)
        db.commit()
        db.refresh(result)
        logger.info(f"创建测试结果: {result.case_id}")
        return result

def create_test_report(report_data: Dict[str, Any]) -> TestReport:
    """
    创建测试报告
    
    Args:
        report_data: 测试报告数据
        
    Returns:
        TestReport: 创建的测试报告对象
    """
    with get_db() as db:
        report = TestReport(**report_data)
        db.add(report)
        db.commit()
        db.refresh(report)
        logger.info(f"创建测试报告: {report.task_id}")
        return report

#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：数据库模块的测试代码
开发规划：测试数据库模型和操作功能
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import (
    Base, 
    TestTask, 
    TestCase, 
    TestResult, 
    TestReport,
    init_db,
    get_db,
    create_test_task,
    get_test_task,
    update_test_task,
    create_test_case,
    create_test_result,
    create_test_report
)
from core.config import Settings

class TestDatabase(unittest.TestCase):
    """数据库模块测试类"""
    
    def setUp(self):
        """测试前准备"""
        # 创建临时数据库
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_url = f"sqlite:///{self.db_path}"
        
        # 创建测试引擎和会话
        self.engine = create_engine(self.db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # 创建表
        Base.metadata.create_all(self.engine)
        
        # 保存原始引擎和会话工厂
        self.original_engine = None
        self.original_session_local = None
    
    def tearDown(self):
        """测试后清理"""
        # 删除表
        Base.metadata.drop_all(self.engine)
        
        # 清理临时目录
        self.temp_dir.cleanup()
    
    @patch("core.database.engine")
    @patch("core.database.get_settings")
    def test_init_db(self, mock_get_settings, mock_engine):
        """测试数据库初始化"""
        # 模拟配置
        mock_settings = MagicMock(spec=Settings)
        mock_settings.db_url = self.db_url
        mock_get_settings.return_value = mock_settings
        
        # 模拟Base.metadata.create_all
        mock_metadata = MagicMock()
        mock_engine.mock_add_spec(["connect"])
        
        # 调用初始化函数
        with patch("core.database.Base.metadata", mock_metadata):
            init_db()
            
            # 验证是否调用了create_all
            mock_metadata.create_all.assert_called_once_with(bind=mock_engine)
    
    @patch("core.database.SessionLocal")
    def test_get_db(self, mock_session_local):
        """测试数据库会话获取"""
        # 模拟会话
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session
        
        # 使用上下文管理器
        with get_db() as db:
            # 验证返回的是模拟会话
            self.assertEqual(db, mock_session)
        
        # 验证会话关闭
        mock_session.close.assert_called_once()
    
    @patch("core.database.get_db")
    def test_create_test_task(self, mock_get_db):
        """测试创建测试任务"""
        # 创建实际会话
        session = self.SessionLocal()
        
        # 模拟get_db返回实际会话
        mock_get_db.return_value.__enter__.return_value = session
        mock_get_db.return_value.__exit__.return_value = None
        
        # 创建测试任务
        task_data = {
            "task_id": "test_task_001",
            "requirement_doc": "测试需求文档",
            "algorithm_image": "test/image:latest",
            "status": "pending"
        }
        
        task = create_test_task(task_data)
        
        # 验证任务创建成功
        self.assertEqual(task.task_id, "test_task_001")
        self.assertEqual(task.requirement_doc, "测试需求文档")
        self.assertEqual(task.algorithm_image, "test/image:latest")
        self.assertEqual(task.status, "pending")
        
        # 验证数据库中存在该任务
        db_task = session.query(TestTask).filter(TestTask.task_id == "test_task_001").first()
        self.assertIsNotNone(db_task)
        self.assertEqual(db_task.task_id, task.task_id)
        
        # 清理
        session.close()
    
    @patch("core.database.get_db")
    def test_get_test_task(self, mock_get_db):
        """测试获取测试任务"""
        # 创建实际会话
        session = self.SessionLocal()
        
        # 模拟get_db返回实际会话
        mock_get_db.return_value.__enter__.return_value = session
        mock_get_db.return_value.__exit__.return_value = None
        
        # 创建测试任务
        task = TestTask(
            task_id="test_task_002",
            requirement_doc="测试需求文档2",
            algorithm_image="test/image2:latest",
            status="running"
        )
        session.add(task)
        session.commit()
        
        # 获取测试任务
        retrieved_task = get_test_task("test_task_002")
        
        # 验证任务获取成功
        self.assertIsNotNone(retrieved_task)
        self.assertEqual(retrieved_task.task_id, "test_task_002")
        self.assertEqual(retrieved_task.requirement_doc, "测试需求文档2")
        self.assertEqual(retrieved_task.status, "running")
        
        # 获取不存在的任务
        non_existent_task = get_test_task("non_existent")
        self.assertIsNone(non_existent_task)
        
        # 清理
        session.close()
    
    @patch("core.database.get_db")
    def test_update_test_task(self, mock_get_db):
        """测试更新测试任务"""
        # 创建实际会话
        session = self.SessionLocal()
        
        # 模拟get_db返回实际会话
        mock_get_db.return_value.__enter__.return_value = session
        mock_get_db.return_value.__exit__.return_value = None
        
        # 创建测试任务
        task = TestTask(
            task_id="test_task_003",
            requirement_doc="测试需求文档3",
            algorithm_image="test/image3:latest",
            status="pending"
        )
        session.add(task)
        session.commit()
        
        # 更新测试任务
        update_data = {
            "status": "completed",
            "requirement_doc": "更新后的需求文档"
        }
        updated_task = update_test_task("test_task_003", update_data)
        
        # 验证任务更新成功
        self.assertIsNotNone(updated_task)
        self.assertEqual(updated_task.status, "completed")
        self.assertEqual(updated_task.requirement_doc, "更新后的需求文档")
        
        # 验证数据库中的任务已更新
        db_task = session.query(TestTask).filter(TestTask.task_id == "test_task_003").first()
        self.assertEqual(db_task.status, "completed")
        self.assertEqual(db_task.requirement_doc, "更新后的需求文档")
        
        # 更新不存在的任务
        non_existent_task = update_test_task("non_existent", update_data)
        self.assertIsNone(non_existent_task)
        
        # 清理
        session.close()
    
    @patch("core.database.get_db")
    def test_create_test_case(self, mock_get_db):
        """测试创建测试用例"""
        # 创建实际会话
        session = self.SessionLocal()
        
        # 模拟get_db返回实际会话
        mock_get_db.return_value.__enter__.return_value = session
        mock_get_db.return_value.__exit__.return_value = None
        
        # 创建测试任务
        task = TestTask(
            task_id="test_task_004",
            requirement_doc="测试需求文档4",
            algorithm_image="test/image4:latest",
            status="pending"
        )
        session.add(task)
        session.commit()
        
        # 创建测试用例
        case_data = {
            "task_id": "test_task_004",
            "case_id": "test_case_001",
            "input_data": {"param1": "value1", "param2": 123},
            "expected_output": {"result": "expected_value"}
        }
        
        case = create_test_case(case_data)
        
        # 验证用例创建成功
        self.assertEqual(case.case_id, "test_case_001")
        self.assertEqual(case.task_id, "test_task_004")
        self.assertEqual(case.input_data, {"param1": "value1", "param2": 123})
        self.assertEqual(case.expected_output, {"result": "expected_value"})
        
        # 验证数据库中存在该用例
        db_case = session.query(TestCase).filter(TestCase.case_id == "test_case_001").first()
        self.assertIsNotNone(db_case)
        self.assertEqual(db_case.case_id, case.case_id)
        
        # 清理
        session.close()

if __name__ == "__main__":
    unittest.main() 
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
数据库迁移脚本：添加test_data列到test_cases表
"""

from sqlalchemy import create_engine, text
from core.config import get_settings
from core.logger import get_logger

# 获取日志记录器
log = get_logger("db_migration")

def migrate():
    """执行数据库迁移"""
    # 获取数据库URL
    settings = get_settings()
    engine = create_engine(settings.db_url)
    
    log.info("开始数据库迁移...")
    
    try:
        # 检查test_data列是否存在
        with engine.connect() as conn:
            # SQLite特定的查询
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM pragma_table_info('test_cases') 
                WHERE name='test_data'
            """))
            exists = result.scalar() > 0
            
            if not exists:
                # 添加test_data列
                conn.execute(text("""
                    ALTER TABLE test_cases 
                    ADD COLUMN test_data VARCHAR(500)
                """))
                log.info("成功添加test_data列到test_cases表")
            else:
                log.info("test_data列已存在，无需迁移")
                
        log.info("数据库迁移完成")
        
    except Exception as e:
        log.error(f"数据库迁移失败: {str(e)}")
        raise

if __name__ == "__main__":
    migrate() 
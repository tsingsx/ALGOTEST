#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：项目入口文件，负责启动FastAPI应用程序
开发规划：初始化各个组件，配置日志系统，启动Web服务
"""

import uvicorn
from fastapi import FastAPI
from core import setup_logging, ensure_db, get_settings
from api import app

def main():
    """
    主函数，启动FastAPI应用
    """
    # 设置日志
    setup_logging()
    
    # 确保数据库表存在（不会删除现有数据）
    ensure_db()
    
    # 获取配置
    settings = get_settings()
    
    # 启动Web服务
    uvicorn.run(
        "api:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        reload=settings.api_reload,
        timeout_keep_alive=settings.api_timeout
    )

if __name__ == "__main__":
    main()

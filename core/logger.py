#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：日志配置模块，负责初始化和配置应用日志系统
开发规划：使用loguru库实现日志记录，支持控制台和文件输出，提供统一的日志接口
"""

import os
import sys
from pathlib import Path
from loguru import logger

from core.config import get_settings

def setup_logging():
    """
    配置日志系统
    
    创建日志目录，配置日志格式和输出位置
    
    Returns:
        logger: 配置好的logger对象
    """
    settings = get_settings()
    
    # 确保日志目录存在
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # 移除默认的logger
    logger.remove()
    
    # 添加控制台处理器
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # 添加文件处理器
    logger.add(
        settings.log_file,
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        encoding="utf-8"
    )
    
    logger.info("日志系统初始化完成")
    
    return logger

def get_logger(name=None):
    """
    获取带有上下文信息的logger
    
    Args:
        name: 日志名称，通常为模块名
        
    Returns:
        logger: 带有上下文信息的logger对象
    """
    return logger.bind(name=name or "algotest")

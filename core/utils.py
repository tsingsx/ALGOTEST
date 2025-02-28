#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：实用工具函数模块，提供项目中常用的辅助功能
开发规划：实现文件操作、数据处理、Docker交互等通用功能，为其他模块提供支持
"""

import os
import uuid
import json
import time
# import docker  # 暂时注释掉docker导入
import hashlib
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

from core.logger import get_logger
from core.config import get_settings

# 获取日志记录器
logger = get_logger("utils")

def generate_unique_id(prefix: str = "") -> str:
    """
    生成唯一ID
    
    Args:
        prefix: ID前缀
        
    Returns:
        str: 唯一ID
    """
    unique_id = str(uuid.uuid4()).replace("-", "")[:12]
    timestamp = int(time.time())
    return f"{prefix}{timestamp}_{unique_id}"

def save_json_file(data: Any, file_path: str) -> bool:
    """
    保存JSON数据到文件
    
    Args:
        data: 要保存的数据
        file_path: 文件路径
        
    Returns:
        bool: 是否保存成功
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"保存JSON文件: {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存JSON文件失败: {e}")
        return False

def load_json_file(file_path: str) -> Optional[Any]:
    """
    从文件加载JSON数据
    
    Args:
        file_path: 文件路径
        
    Returns:
        Any: 加载的数据，失败返回None
    """
    try:
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return None
            
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.debug(f"加载JSON文件: {file_path}")
        return data
    except Exception as e:
        logger.error(f"加载JSON文件失败: {e}")
        return None

def calculate_md5(file_path: str) -> Optional[str]:
    """
    计算文件MD5哈希值
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: MD5哈希值，失败返回None
    """
    try:
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return None
            
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        logger.error(f"计算MD5失败: {e}")
        return None

def run_docker_container(image: str, command: str, volumes: Dict[str, Dict[str, str]] = None, 
                        environment: Dict[str, str] = None, timeout: int = 300) -> Dict[str, Any]:
    """
    运行Docker容器
    
    Args:
        image: Docker镜像名称
        command: 要执行的命令
        volumes: 挂载卷
        environment: 环境变量
        timeout: 超时时间(秒)
        
    Returns:
        Dict: 包含执行结果的字典
    """
    # 暂时返回模拟结果
    logger.warning("Docker功能暂未实现，返回模拟结果")
    return {
        "status": "simulated",
        "exit_code": 0,
        "logs": "Docker功能暂未实现，这是模拟输出",
        "execution_time": 0
    }
    
    # 原始代码注释掉
    """
    try:
        settings = get_settings()
        client = docker.from_env()
        
        # 如果需要登录Docker仓库
        if settings.docker_registry and settings.docker_username and settings.docker_password:
            client.login(
                username=settings.docker_username,
                password=settings.docker_password,
                registry=settings.docker_registry
            )
        
        logger.info(f"运行Docker容器: {image}, 命令: {command}")
        start_time = time.time()
        container = client.containers.run(
            image=image,
            command=command,
            volumes=volumes or {},
            environment=environment or {},
            detach=True,
            remove=False
        )
        
        # 等待容器执行完成或超时
        status = "timeout"
        exit_code = -1
        logs = ""
        
        while time.time() - start_time < timeout:
            container.reload()
            if container.status != "running":
                status = "completed"
                exit_code = container.attrs['State']['ExitCode']
                logs = container.logs().decode('utf-8', errors='replace')
                break
            time.sleep(1)
        
        # 如果超时，强制停止容器
        if status == "timeout":
            logger.warning(f"Docker容器执行超时: {image}")
            container.stop()
            logs = container.logs().decode('utf-8', errors='replace')
        
        # 清理容器
        container.remove()
        
        execution_time = int((time.time() - start_time) * 1000)  # 毫秒
        
        result = {
            "status": status,
            "exit_code": exit_code,
            "logs": logs,
            "execution_time": execution_time
        }
        
        logger.info(f"Docker容器执行完成: {image}, 状态: {status}, 退出码: {exit_code}, 执行时间: {execution_time}ms")
        return result
    except Exception as e:
        logger.error(f"运行Docker容器失败: {e}")
        return {
            "status": "error",
            "exit_code": -1,
            "logs": str(e),
            "execution_time": 0
        }
    """

def format_timestamp(timestamp: Optional[float] = None, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化时间戳
    
    Args:
        timestamp: 时间戳，默认为当前时间
        format_str: 格式化字符串
        
    Returns:
        str: 格式化后的时间字符串
    """
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(timestamp).strftime(format_str)

def make_request(url: str, method: str = "GET", data: Any = None, 
                headers: Dict[str, str] = None, timeout: int = 30) -> Dict[str, Any]:
    """
    发送HTTP请求
    
    Args:
        url: 请求URL
        method: 请求方法
        data: 请求数据
        headers: 请求头
        timeout: 超时时间(秒)
        
    Returns:
        Dict: 包含响应结果的字典
    """
    try:
        headers = headers or {}
        if not headers.get("Content-Type") and data:
            headers["Content-Type"] = "application/json"
        
        if isinstance(data, dict) or isinstance(data, list):
            data = json.dumps(data)
        
        logger.debug(f"发送HTTP请求: {method} {url}")
        response = requests.request(
            method=method,
            url=url,
            data=data,
            headers=headers,
            timeout=timeout
        )
        
        result = {
            "status_code": response.status_code,
            "content": response.text,
            "headers": dict(response.headers),
            "success": response.status_code < 400
        }
        
        logger.debug(f"HTTP请求完成: {method} {url}, 状态码: {response.status_code}")
        return result
    except Exception as e:
        logger.error(f"HTTP请求失败: {e}")
        return {
            "status_code": 0,
            "content": str(e),
            "headers": {},
            "success": False
        }

def ensure_dir(directory: str) -> bool:
    """
    确保目录存在，如果不存在则创建
    
    Args:
        directory: 目录路径
        
    Returns:
        bool: 是否成功
    """
    try:
        os.makedirs(directory, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"创建目录失败: {e}")
        return False

def read_file(file_path: str, encoding: str = "utf-8") -> Optional[str]:
    """
    读取文件内容
    
    Args:
        file_path: 文件路径
        encoding: 文件编码
        
    Returns:
        str: 文件内容，失败返回None
    """
    try:
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return None
            
        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
        return content
    except Exception as e:
        logger.error(f"读取文件失败: {e}")
        return None

def write_file(content: str, file_path: str, encoding: str = "utf-8") -> bool:
    """
    写入文件内容
    
    Args:
        content: 文件内容
        file_path: 文件路径
        encoding: 文件编码
        
    Returns:
        bool: 是否成功
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error(f"写入文件失败: {e}")
        return False

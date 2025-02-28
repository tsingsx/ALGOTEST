#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：大模型API调用模块，负责与智谱AI等大模型服务进行交互
开发规划：实现智谱AI的API调用，支持文本生成、对话等功能
"""

import json
import time
import requests
import base64
from typing import Dict, Any, List, Optional, Union
import hashlib
import hmac
from datetime import datetime, timezone

from core.config import get_llm_config
from core.logger import get_logger

# 获取日志记录器
log = get_logger("llm")

def call_zhipu_api(prompt: str, config: Optional[Dict[str, Any]] = None) -> str:
    """
    调用智谱AI的API生成文本
    
    Args:
        prompt: 提示词
        config: 配置参数，如果为None则使用默认配置
        
    Returns:
        str: 生成的文本
    """
    if config is None:
        config = get_llm_config()
    
    api_key = config.get("api_key", "")
    if not api_key:
        raise ValueError("未配置智谱AI API密钥")
    
    # 解析API密钥
    key_parts = api_key.split(".")
    if len(key_parts) != 2:
        raise ValueError("智谱AI API密钥格式错误")
    
    api_id, api_secret = key_parts
    
    # 准备请求
    url = f"https://open.bigmodel.cn/api/paas/v4/chat/completions"
    
    # 生成JWT
    token = generate_zhipu_jwt(api_id, api_secret)
    
    # 准备请求头
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 准备请求体
    data = {
        "model": config.get("model_chat", "glm-4-flash"),
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 6000)
    }
    
    # 发送请求
    retry_count = config.get("retry_count", 3)
    retry_delay = config.get("retry_delay", 5)
    retry_backoff = config.get("retry_backoff", 2.0)
    timeout = config.get("timeout", 60)  # 默认超时时间为60秒
    
    for attempt in range(retry_count):
        try:
            log.info(f"调用智谱AI API，尝试次数: {attempt + 1}/{retry_count}")
            response = requests.post(url, headers=headers, json=data, timeout=timeout)
            
            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    log.success(f"智谱AI API调用成功")
                    return content
                else:
                    log.error(f"智谱AI API返回格式错误: {result}")
            else:
                log.error(f"智谱AI API调用失败，状态码: {response.status_code}, 响应: {response.text}")
            
            # 如果不是最后一次尝试，则等待后重试
            if attempt < retry_count - 1:
                wait_time = retry_delay * (retry_backoff ** attempt)
                log.info(f"等待 {wait_time} 秒后重试")
                time.sleep(wait_time)
        except requests.exceptions.Timeout:
            log.error(f"智谱AI API调用超时 (超时设置: {timeout}秒)")
            # 如果不是最后一次尝试，则增加超时时间后重试
            if attempt < retry_count - 1:
                # 每次重试增加超时时间
                timeout = int(timeout * 1.5)
                wait_time = retry_delay * (retry_backoff ** attempt)
                log.info(f"增加超时时间至 {timeout} 秒，等待 {wait_time} 秒后重试")
                time.sleep(wait_time)
        except requests.exceptions.RequestException as e:
            log.error(f"智谱AI API请求异常: {str(e)}")
            # 如果不是最后一次尝试，则等待后重试
            if attempt < retry_count - 1:
                wait_time = retry_delay * (retry_backoff ** attempt)
                log.info(f"等待 {wait_time} 秒后重试")
                time.sleep(wait_time)
        except Exception as e:
            log.error(f"智谱AI API调用异常: {str(e)}")
            # 如果不是最后一次尝试，则等待后重试
            if attempt < retry_count - 1:
                wait_time = retry_delay * (retry_backoff ** attempt)
                log.info(f"等待 {wait_time} 秒后重试")
                time.sleep(wait_time)
    
    # 所有重试都失败，返回错误信息
    error_msg = "智谱AI API调用失败，已达到最大重试次数"
    log.error(error_msg)
    return f"API调用失败: {error_msg}"

def generate_zhipu_jwt(api_id: str, api_secret: str, exp_seconds: int = 3600) -> str:
    """
    生成智谱AI API的JWT认证令牌
    
    Args:
        api_id: API ID
        api_secret: API 密钥
        exp_seconds: 过期时间(秒)
        
    Returns:
        str: JWT令牌
    """
    try:
        # 准备JWT头部
        header = {
            "alg": "HS256",
            "sign_type": "SIGN"
        }
        header_encoded = base64.b64encode(json.dumps(header).encode('utf-8')).decode('utf-8').replace('=', '')
        
        # 准备JWT载荷
        now = int(datetime.now(tz=timezone.utc).timestamp())
        payload = {
            "api_key": api_id,
            "exp": now + exp_seconds,
            "timestamp": now
        }
        payload_encoded = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8').replace('=', '')
        
        # 准备签名
        signature_message = f"{header_encoded}.{payload_encoded}"
        signature = hmac.new(
            api_secret.encode('utf-8'),
            signature_message.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature_encoded = base64.b64encode(signature).decode('utf-8').replace('=', '')
        
        # 组装JWT
        jwt = f"{header_encoded}.{payload_encoded}.{signature_encoded}"
        return jwt
    except Exception as e:
        log.error(f"生成JWT令牌失败: {str(e)}")
        raise 
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：API应用定义，创建FastAPI应用实例
开发规划：配置中间件、异常处理、CORS等
"""

import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from core.logger import get_logger
from api.routes import router

# 获取日志记录器
log = get_logger("api")

# 创建FastAPI应用
app = FastAPI(
    title="ALGOTEST API",
    description="大模型驱动的算法测试系统API，支持上传算法需求文档并自动生成测试用例",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加路由
app.include_router(router)


# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录请求日志的中间件"""
    start_time = time.time()
    
    # 记录请求信息
    log.info(f"开始处理请求: {request.method} {request.url.path}")
    
    # 处理请求
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        
        # 记录响应信息
        log.info(f"请求处理完成: {request.method} {request.url.path} - 状态码: {response.status_code}, 耗时: {process_time:.4f}秒")
        
        return response
    except Exception as e:
        # 记录异常信息
        log.error(f"请求处理异常: {request.method} {request.url.path} - 异常: {str(e)}")
        raise


# 异常处理
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求验证异常"""
    log.warning(f"请求验证失败: {request.method} {request.url.path} - 错误: {str(exc)}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "message": "请求参数验证失败"}
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """处理HTTP异常"""
    log.warning(f"HTTP异常: {request.method} {request.url.path} - 状态码: {exc.status_code}, 错误: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """处理通用异常"""
    log.error(f"未处理的异常: {request.method} {request.url.path} - 异常: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误", "message": str(exc)}
    )


# 根路由
@app.get("/")
async def root():
    """API根路由，重定向到API文档"""
    return {"message": "欢迎使用ALGOTEST API", "docs": "/api/docs"}

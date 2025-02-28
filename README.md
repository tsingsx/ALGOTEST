# ALGOTEST

## 项目概述

ALGOTEST是一个大模型驱动的算法测试系统，能够分析用户输入的算法需求文档，生成测试用例，执行测试，并生成测试报告。系统通过FastAPI封装为API服务，提供RESTful接口供外部调用。

系统主要特点：
- 使用langgraph构建工作流
- 采用loguru进行日志管理
- 使用SQLite进行数据存储
- 通过pydantic-settings进行配置管理

## 系统架构

系统由三个核心Agent组成：
1. **分析Agent**：负责分析用户输入的算法需求文档，生成测试用例
2. **执行Agent**：负责执行测试用例，包括拉取算法镜像、获取数据集、执行测试
3. **报告Agent**：负责收集测试结果，生成测试报告

## 安装说明

### 环境要求
- Python 3.8+
- Docker

### 安装步骤

1. 克隆仓库
```bash
git clone https://github.com/tsingsx/ALGOTEST.git
cd ALGOTEST
```

2. 创建虚拟环境
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

3. 安装依赖
```bash
pip install -r requirements.txt
```

4. 配置环境变量
```bash
cp .env.example .env
# 编辑.env文件，填写必要的配置信息
```

## 使用方法

### 文件存储

- **算法需求文档**：请将算法需求文档（PDF格式）放置在 `data/pdfs/` 目录下
- **测试报告**：测试报告将保存在 `data/reports/` 目录下
- **测试用例**：测试用例将保存在 `data/testcases/` 目录下

### 启动服务
```bash
python main.py
```

### API接口
- **POST /api/tests**：提交新的算法测试请求
- **GET /api/tests/{task_id}**：获取测试任务状态
- **GET /api/tests/{task_id}/report**：获取测试报告
- **GET /api/tests**：获取所有测试任务列表

## 开发指南

请参考项目文档了解更多开发信息。

## 许可证

[MIT License](LICENSE)
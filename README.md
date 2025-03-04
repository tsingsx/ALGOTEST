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
- **GET /api/tests/{task_id}/cases**：获取测试任务的测试用例列表
- **POST /api/tests/{task_id}/generate-cases**：为指定测试任务重新生成测试用例
- **POST /api/generate-testcases**：直接从需求文档生成测试用例，不创建测试任务

### 测试用例生成功能

系统能够自动分析算法需求文档，生成测试用例。测试用例生成过程如下：

1. 用户通过 `POST /api/tests` 接口提交测试请求，包含算法需求文档路径和算法镜像名称
2. 系统在后台启动分析Agent，读取需求文档内容
3. 分析Agent使用大模型分析需求文档，生成测试用例
4. 生成的测试用例保存到数据库中
5. 用户可以通过 `GET /api/tests/{task_id}/cases` 接口获取生成的测试用例列表
6. 如果需要重新生成测试用例，可以使用 `POST /api/tests/{task_id}/generate-cases` 接口

测试用例包含以下信息：
- 测试名称：简短描述测试内容
- 测试目的：详细说明测试什么功能或参数
- 测试步骤：如何执行测试，包括具体的参数设置
- 预期结果：测试应该产生什么结果
- 验证方法：如何验证测试结果

### 直接生成测试用例

如果只需要生成测试用例，而不需要创建测试任务，可以使用 `POST /api/generate-testcases` 接口：

1. 将算法需求文档（PDF格式）放置在 `data/pdfs/` 目录下
2. 发送POST请求到 `/api/generate-testcases`，请求体包含 `doc_path` 参数，指定需求文档的相对路径
3. 系统会直接返回生成的测试用例列表，不会创建测试任务或保存到数据库

示例请求：
```json
{
  "doc_path": "algorithm_requirement.pdf"
}
```

示例响应：
```json
{
  "message": "成功从文档生成10个测试用例",
  "test_cases": [
    {
      "id": "TC_20250304_123456",
      "name": "测试参数A的默认值",
      "purpose": "验证参数A在未设置时使用默认值",
      "steps": "不设置参数A，直接运行算法",
      "expected_result": "算法使用参数A的默认值10进行计算",
      "validation_method": "检查输出结果中的计算值是否基于默认值10"
    },
    // 更多测试用例...
  ]
}
```

## 开发指南

请参考项目文档了解更多开发信息。

## 许可证

[MIT License](LICENSE)
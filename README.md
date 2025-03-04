# ALGOTEST

## 项目概述

ALGOTEST是一个大模型驱动的算法测试系统，能够分析用户输入的算法需求文档，自动生成全面的测试用例。系统通过FastAPI封装为API服务，提供RESTful接口供外部调用。

系统主要特点：
- 使用langgraph构建工作流
- 采用loguru进行日志管理
- 使用SQLite进行数据存储
- 通过pydantic-settings进行配置管理

## 系统架构

系统由核心分析Agent组成：
- **分析Agent**：负责分析用户输入的算法需求文档，生成测试用例

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
# 编辑.env文件，填写必要的配置信息，特别是ZHIPU_API_KEY
```

## 使用方法

### 启动服务
```bash
python main.py
```

或者使用热重载模式（开发时推荐）：
```bash
export API_RELOAD=true && python main.py
```

### API接口
- **POST /api/generate-testcases**：上传需求文档并生成测试用例

### 测试用例生成功能

系统能够自动分析算法需求文档，生成测试用例。

测试用例包含以下信息：
- 测试名称：简短描述测试内容
- 测试目的：详细说明测试什么功能或参数
- 测试步骤：如何执行测试，包括具体的参数设置
- 预期结果：测试应该产生什么结果
- 验证方法：如何验证测试结果

### 生成测试用例

使用 `POST /api/generate-testcases` 接口：

1. 准备算法需求文档（PDF格式）
2. 发送POST请求到 `/api/generate-testcases`，使用multipart/form-data格式上传PDF文件
3. 系统会直接返回生成的测试用例列表

示例请求：
```
POST /api/generate-testcases HTTP/1.1
Host: localhost:8000
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW

------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="file"; filename="需求文档.pdf"
Content-Type: application/pdf

(二进制PDF文件内容)
------WebKitFormBoundary7MA4YWxkTrZu0gW--
```

示例响应：
```json
{
  "message": "成功从文档生成8个测试用例",
  "test_cases": [
    {
      "id": "TC1741059293_f1f741f10322",
      "name": "验证未佩戴面罩报警逻辑",
      "purpose": "验证算法在识别到人员未佩戴面罩时是否能够正确触发报警。",
      "steps": "设置参数 `visual_object=true`，`used_time_switch=true`，`alert_time_thresh=3`...",
      "expected_result": "输出结果中的 `algorithm_data.is_alert` 应为 `true`...",
      "validation_method": "检查输出结果中的 `algorithm_data.is_alert` 字段，确认其值为 `true`。"
    },
    // 更多测试用例...
  ]
}
```

## API文档

系统提供了Swagger UI文档，可以通过访问 `http://localhost:8000/api/docs` 查看和测试API接口。

## 开发指南

请参考项目文档了解更多开发信息。

## 许可证

[MIT License](LICENSE)
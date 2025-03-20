#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件作用：执行Agent模块，负责执行测试用例
开发规划：实现基于MCP的测试用例执行功能，包括命令解析和执行
"""

import os
import json
import asyncio
from typing import Dict, Any, List, Optional, Tuple, TypedDict
from datetime import datetime
from loguru import logger
from langgraph.graph import StateGraph, END
import zhipuai
from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from pydantic import BaseModel

from core.config import get_settings, get_llm_config
from core.database import get_db, update_test_case_status, update_test_task_status, get_test_task
from core.utils import generate_unique_id, format_timestamp, ensure_dir
from core.logger import get_logger

# 加载环境变量
load_dotenv()

# 获取带上下文的logger
log = get_logger("execution_agent")

# 智谱AI配置
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")
ZHIPU_MODEL = os.getenv("ZHIPU_MODEL_CHAT", "glm-4-flash")
ZHIPU_API_BASE = os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4")

# MCP服务器配置
MCP_HOST = os.getenv("MCP_HOST", "172.16.100.108")
MCP_PORT = int(os.getenv("MCP_PORT", "2800"))
SSE_URL = f"http://{MCP_HOST}:{MCP_PORT}/sse"


class CommandStrategy(BaseModel):
    """命令策略模型"""
    tool: str
    parameters: Dict[str, Any]
    description: Optional[str] = None


class ExecutionState(TypedDict):
    """执行Agent状态定义"""
    task_id: str  # 任务ID
    case_id: Optional[str]  # 测试用例ID，可选
    algorithm_image: str  # 算法镜像
    dataset_url: Optional[str]  # 数据集URL
    test_cases: List[Dict[str, Any]]  # 测试用例列表
    current_case_index: int  # 当前执行的测试用例索引
    command_strategy: Optional[CommandStrategy]  # 命令策略
    execution_result: Optional[Dict[str, Any]]  # 执行结果
    errors: List[str]  # 错误信息
    status: str  # 任务状态
    container_ready: bool  # Docker容器是否准备好


class ZhipuAIClient:
    """智谱AI客户端"""
    
    def __init__(self, api_key: str, model: str):
        """初始化智谱AI客户端"""
        self.api_key = api_key
        self.model = model
        zhipuai.api_key = api_key
        
    async def parse_command(self, command: str, available_tools: List[Dict[str, Any]]) -> CommandStrategy:
        """
        使用智谱AI解析自然语言命令
        
        Args:
            command: 自然语言命令
            available_tools: 可用工具列表
            
        Returns:
            解析后的命令策略
        """
        # 检查API密钥是否设置
        if not self.api_key:
            raise ValueError("智谱AI API密钥未设置")
        
        # 构建工具描述
        tools_description = """
可用的工具有:

1. execute_command - 执行单个CLI命令
   参数:
   - command (字符串, 必需): 要执行的命令
   - working_dir (字符串, 可选): 命令执行的工作目录，默认为当前目录

2. execute_script - 执行多行脚本
   参数:
   - script (字符串, 必需): 要执行的脚本内容
   - working_dir (字符串, 可选): 脚本执行的工作目录，默认为当前目录

3. list_directory - 列出目录内容
   参数:
   - path (字符串, 可选): 要列出内容的目录路径，默认为当前目录

使用说明:
- 对于单个命令，使用 execute_command
- 对于需要执行多个命令或创建文件的操作，使用 execute_script
- 对于查看目录内容的操作，使用 list_directory
- working_dir 参数可以指定命令或脚本执行的工作目录

重要提示：
- 命令在Docker容器中执行，不支持sudo命令
- 如果需要apt-get等命令，请直接使用apt-get，不要加sudo
- 如果命令不存在，可能需要先安装相应的软件包
"""
        
        prompt = f"""
请将以下测试用例步骤转换为JSON格式的执行策略。策略应包含要调用的工具名称和参数。

{tools_description}

测试用例步骤: {command}

请以以下JSON格式返回:
{{
  "tool": "工具名称",
  "parameters": {{
    "参数名1": "参数值1",
    "参数名2": "参数值2"
  }},
  "description": "对这个操作的简短描述"
}}

注意事项:
1. 如果步骤涉及创建文件或执行多个命令，应该使用 execute_script
2. 如果只是查看目录内容，使用 list_directory
3. 如果是单个命令，使用 execute_command
4. 如果命令需要在特定目录下执行，添加 working_dir 参数
5. 确保参数名称和类型与工具定义完全匹配
6. 不要使用sudo命令，Docker容器中没有sudo

只返回JSON，不要有其他文字。
"""
        
        try:
            # 创建客户端
            client = zhipuai.ZhipuAI(api_key=self.api_key)
            
            # 调用模型
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                top_p=0.7,
                max_tokens=1000,
            )
            
            # 提取JSON响应
            content = response.choices[0].message.content
            
            # 尝试解析JSON
            try:
                strategy_dict = json.loads(content)
                return CommandStrategy(**strategy_dict)
            except json.JSONDecodeError as e:
                # 如果直接解析失败，尝试从文本中提取JSON部分
                import re
                json_match = re.search(r'({[\s\S]*})', content)
                if json_match:
                    strategy_dict = json.loads(json_match.group(1))
                    return CommandStrategy(**strategy_dict)
                else:
                    raise Exception("无法从智谱AI响应中提取JSON")
                    
        except Exception as e:
            log.error(f"调用智谱AI API时出错: {e}")
            raise


class MCPClient:
    """MCP客户端"""
    
    def __init__(self, host: str, port: int):
        """初始化MCP客户端"""
        self.host = host
        self.port = port
        self.sse_url = f"http://{host}:{port}/sse"
        self.ai_client = ZhipuAIClient(ZHIPU_API_KEY, ZHIPU_MODEL)
        self.session = None
        
    async def connect(self):
        """连接到MCP服务器"""
        log.info(f"正在连接到MCP服务器 {self.sse_url}...")
        
        try:
            # 建立SSE连接
            async with sse_client(self.sse_url) as (read, write):
                # 创建客户端会话
                async with ClientSession(read, write) as session:
                    # 初始化连接
                    await session.initialize()
                    log.success("MCP服务器连接成功！")
                    
                    # 保存会话
                    self.session = session
                    
                    # 等待会话结束
                    while True:
                        await asyncio.sleep(0.1)
            
            return True
        except Exception as e:
            log.error(f"连接到MCP服务器时出错: {e}")
            return False
    
    async def disconnect(self):
        """断开与MCP服务器的连接"""
        self.session = None
        log.info("已断开与MCP服务器的连接")
    
    async def execute_command(self, command: str) -> Dict[str, Any]:
        """
        执行命令
        
        Args:
            command: 要执行的命令
            
        Returns:
            执行结果
        """
        if not self.session:
            raise Exception("未连接到MCP服务器")
        
        try:
            # 获取可用工具列表
            tools = await self.session.list_tools()
            available_tools = []
            if hasattr(tools, 'tools'):
                for tool in tools.tools:
                    available_tools.append({
                        "name": tool.name,
                        "description": tool.description
                    })
            
            # 使用智谱AI解析命令
            strategy = await self.ai_client.parse_command(command, available_tools)
            
            log.info(f"解析结果: {strategy}")
            log.info(f"将调用工具: {strategy.tool}")
            
            # 预处理参数
            if "working_dir" in strategy.parameters:
                # 处理特殊的工作目录值
                if strategy.parameters["working_dir"] in ["current_directory", ".", "current", "current dir"]:
                    log.info(f"将工作目录从 '{strategy.parameters['working_dir']}' 修改为 '/'")
                    strategy.parameters["working_dir"] = "/"
            
            # 对于execute_script，确保脚本不使用sudo
            if strategy.tool == "execute_script" and "script" in strategy.parameters:
                script = strategy.parameters["script"]
                if "sudo " in script:
                    clean_script = script.replace("sudo ", "")
                    log.info(f"移除脚本中的sudo命令: '{script}' -> '{clean_script}'")
                    strategy.parameters["script"] = clean_script
            
            # 对于execute_command，确保命令不使用sudo
            if strategy.tool == "execute_command" and "command" in strategy.parameters:
                cmd = strategy.parameters["command"]
                if cmd.startswith("sudo "):
                    clean_cmd = cmd.replace("sudo ", "", 1)
                    log.info(f"移除命令中的sudo: '{cmd}' -> '{clean_cmd}'")
                    strategy.parameters["command"] = clean_cmd
            
            log.info(f"处理后的参数: {strategy.parameters}")
            
            # 调用相应的工具
            result = await self.session.call_tool(strategy.tool, strategy.parameters)
            log.success("命令执行成功")
            
            return {
                "success": True,
                "strategy": strategy,
                "result": result
            }
            
        except Exception as e:
            log.error(f"执行命令时出错: {e}")
            return {
                "success": False,
                "error": str(e)
            }


def load_test_cases(state: ExecutionState) -> ExecutionState:
    """
    按照task_id批量加载测试用例信息，如果提供了case_id则只加载指定用例
    
    Args:
        state: 当前状态
        
    Returns:
        更新后的状态
    """
    task_id = state['task_id']
    case_id = state.get('case_id')
    
    if case_id:
        log.info(f"开始加载指定的测试用例: 任务ID={task_id}, 用例ID={case_id}")
    else:
        log.info(f"开始加载任务 {task_id} 的所有测试用例")
    
    try:
        # 从数据库加载测试用例
        with get_db() as db:
            if case_id:
                # 只加载指定的测试用例
                test_case = db.query("SELECT * FROM test_cases WHERE case_id = ? AND task_id = ?", 
                                    [case_id, task_id]).fetchone()
                
                if not test_case:
                    raise ValueError(f"找不到指定的测试用例: 任务ID={task_id}, 用例ID={case_id}")
                
                test_cases = [test_case]
                log.info(f"找到指定的测试用例: {case_id}")
            else:
                # 按task_id获取所有测试用例
                test_cases = db.query("SELECT * FROM test_cases WHERE task_id = ?", [task_id]).fetchall()
                
                if not test_cases or len(test_cases) == 0:
                    raise ValueError(f"任务 {task_id} 没有测试用例")
                
                log.info(f"找到 {len(test_cases)} 个测试用例")
            
            # 更新状态
            return {
                **state,
                "test_cases": test_cases,
                "current_case_index": 0,  # 从第一个测试用例开始
                "status": "loaded"
            }
    except Exception as e:
        log.error(f"加载测试用例失败: {str(e)}")
        return {
            **state,
            "errors": state.get("errors", []) + [str(e)],
            "status": "error"
        }


async def parse_command(state: ExecutionState) -> ExecutionState:
    """
    解析测试用例命令 - 只使用智谱AI API进行解析，不连接MCP服务器
    
    Args:
        state: 当前状态
        
    Returns:
        更新后的状态
    """
    # 获取当前测试用例
    current_index = state.get("current_case_index", 0)
    test_cases = state.get("test_cases", [])
    
    if not test_cases or current_index >= len(test_cases):
        return {
            **state,
            "errors": state.get("errors", []) + ["没有可执行的测试用例"],
            "status": "error"
        }
    
    # 获取当前测试用例
    test_case = test_cases[current_index]
    case_id = test_case.get("case_id")
    
    log.info(f"开始解析命令: 用例ID={case_id}, 索引={current_index+1}/{len(test_cases)}")
    
    try:
        # 获取测试步骤
        steps = test_case.get("input_data", {}).get("steps", "")
        if not steps:
            raise ValueError("测试步骤为空")
        
        # 直接创建智谱AI客户端
        ai_client = ZhipuAIClient(ZHIPU_API_KEY, ZHIPU_MODEL)
        
        # 解析命令 - 不需要连接MCP服务器
        log.info(f"使用智谱AI解析命令")
        command_strategy = await ai_client.parse_command(steps, [])
        
        log.success(f"命令解析成功: {command_strategy.tool}")
        
        # 更新状态
        return {
            **state,
            "case_id": case_id,  # 设置当前执行的case_id
            "command_strategy": command_strategy,
            "status": "parsed"
        }
            
    except Exception as e:
        log.error(f"解析命令失败: {str(e)}")
        return {
            **state,
            "errors": state.get("errors", []) + [str(e)],
            "status": "error"
        }


async def execute_command(state: ExecutionState) -> ExecutionState:
    """
    执行命令
    
    Args:
        state: 当前状态
        
    Returns:
        更新后的状态
    """
    case_id = state.get("case_id")
    log.info(f"开始执行命令: 用例ID={case_id}")
    
    try:
        # 获取命令策略
        command_strategy = state.get("command_strategy")
        if not command_strategy:
            raise ValueError("命令策略未解析")
        
        # 检查Docker容器是否已准备好
        if not state.get("container_ready", False):
            log.warning("Docker容器未准备好，将尝试在本地执行命令")
            
            # 创建MCP客户端
            client = MCPClient(MCP_HOST, MCP_PORT)
            
            # 连接到MCP服务器
            if not await client.connect():
                raise Exception("无法连接到MCP服务器")
            
            try:
                # 执行命令
                result = await client.execute_command(command_strategy.parameters.get("command", ""))
                
                # 更新状态
                return {
                    **state,
                    "execution_result": result,
                    "status": "executed"
                }
            finally:
                # 断开连接
                await client.disconnect()
        else:
            # 使用Docker容器执行命令
            log.info("使用Docker容器执行命令")
            
            # 获取命令
            command = command_strategy.parameters.get("command", "")
            
            # 在Docker容器中执行命令
            result = await execute_container_command(state["task_id"], command)
            
            if not result.get("success"):
                error_msg = result.get("error", "未知错误")
                raise Exception(f"在Docker容器中执行命令失败: {error_msg}")
            
            # 更新状态
            return {
                **state,
                "execution_result": result,
                "status": "executed"
            }
            
    except Exception as e:
        log.error(f"执行命令失败: {str(e)}")
        return {
            **state,
            "errors": state.get("errors", []) + [str(e)],
            "status": "error"
        }


async def save_result(state: ExecutionState) -> ExecutionState:
    """
    保存执行结果，并决定是否继续执行下一个测试用例
    
    Args:
        state: 当前状态
        
    Returns:
        更新后的状态
    """
    case_id = state.get("case_id")
    log.info(f"开始保存执行结果: 用例ID={case_id}")
    
    try:
        # 获取执行结果
        execution_result = state.get("execution_result")
        if not execution_result:
            raise ValueError("执行结果为空")
        
        # 更新测试用例状态
        with get_db() as db:
            # 更新测试用例状态
            update_test_case_status(
                case_id=case_id,
                status="completed" if execution_result.get("success") else "failed",
                result=execution_result
            )
        
        log.success(f"执行结果保存成功: 用例ID={case_id}")
        
        # 获取当前测试用例索引
        current_index = state.get("current_case_index", 0)
        test_cases = state.get("test_cases", [])
        
        # 检查是否还有下一个测试用例需要执行
        if current_index + 1 < len(test_cases):
            # 还有测试用例需要执行，更新索引并准备执行下一个
            log.info(f"准备执行下一个测试用例，当前进度: {current_index + 1}/{len(test_cases)}")
            next_state = {
                **state,
                "current_case_index": current_index + 1,
                "case_id": None,  # 清除当前case_id
                "command_strategy": None,  # 清除当前命令策略
                "execution_result": None,  # 清除当前执行结果
                "status": "next_case"  # 设置状态为下一个测试用例
            }
            
            # 调用parse_command函数解析下一个测试用例的命令
            next_state = await parse_command(next_state)
            
            # 如果解析成功，继续执行命令
            if next_state.get("status") == "parsed":
                next_state = await execute_command(next_state)
                
                # 如果执行成功，递归调用save_result保存结果
                if next_state.get("status") == "executed":
                    return await save_result(next_state)
            
            # 如果过程中出现错误，返回错误状态
            return next_state
        else:
            # 所有测试用例已执行完成，更新任务状态
            with get_db() as db:
                # 更新测试任务状态
                update_test_task_status(
                    task_id=state["task_id"],
                    status="completed"
                )
            
            log.success(f"所有测试用例执行完成: 任务ID={state['task_id']}, 共{len(test_cases)}个测试用例")
            
            # 更新状态
            return {
                **state,
                "status": "completed"
            }
    except Exception as e:
        log.error(f"保存执行结果失败: {str(e)}")
        return {
            **state,
            "errors": state.get("errors", []) + [str(e)],
            "status": "error"
        }


async def setup_algorithm_container(task_id: str) -> Dict[str, Any]:
    """
    通过MCP在远程服务器上设置算法Docker容器
    
    Args:
        task_id: 测试任务ID
        
    Returns:
        设置结果
    """
    log.info(f"开始通过MCP设置算法Docker容器: {task_id}")
    
    try:
        # 从数据库获取任务信息
        task = get_test_task(task_id)
        if not task:
            raise ValueError(f"测试任务不存在: {task_id}")
        
        # 获取算法镜像和数据集URL
        algorithm_image = task.algorithm_image
        dataset_url = task.dataset_url
        
        if not algorithm_image:
            raise ValueError(f"算法镜像未设置: {task_id}")
        
        # 构建容器名称
        container_name = f"algotest_{task_id}"
        
        # 准备数据集挂载参数
        dataset_mount = ""
        if dataset_url:
            # 在Docker容器中的数据集路径
            container_dataset_path = "/data"
            dataset_mount = f"-v {dataset_url}:{container_dataset_path}"
        
        # 构建Docker操作脚本
        script = f"""
# 检查是否已存在同名容器
container_id=$(docker ps -a --filter name={container_name} -q)
if [ ! -z "$container_id" ]; then
    echo "发现同名容器，正在删除: {container_name}"
    docker rm -f {container_name}
fi

# 运行新容器
echo "正在启动新容器: {container_name}"
docker run --gpus=all -itd --privileged -v /etc/localtime:/etc/localtime:ro -e LANG=C.UTF-8 --name {container_name} {dataset_mount} {algorithm_image}

# 检查容器是否成功启动
sleep 2
container_status=$(docker inspect -f '{{{{.State.Running}}}}' {container_name} 2>/dev/null || echo "false")

if [ "$container_status" != "true" ]; then
    echo "容器启动失败，输出日志:"
    docker logs {container_name}
    exit 1
fi

echo "容器启动成功: {container_name}"
echo "算法镜像: {algorithm_image}"
"""
        
        if dataset_url:
            script += f'echo "数据集URL: {dataset_url} 已挂载到容器 {container_dataset_path}"\n'
        
        log.info(f"准备通过MCP执行Docker脚本...")
        
        # 连接到MCP服务器并执行脚本
        async with sse_client(SSE_URL) as (read, write):
            async with ClientSession(read, write) as session:
                # 初始化连接
                await session.initialize()
                log.success("MCP服务器连接成功")
                
                # 使用execute_script工具执行Docker脚本
                log.info("正在执行Docker配置脚本...")
                result = await session.call_tool("execute_script", {"script": script})
                
                # 检查脚本执行结果
                if hasattr(result, 'stderr') and result.stderr:
                    log.error(f"Docker脚本执行出错: {result.stderr}")
                    return {
                        "success": False,
                        "task_id": task_id,
                        "error": f"Docker容器启动失败: {result.stderr}"
                    }
                
                # 再次检查容器是否真的在运行
                verify_script = f"""
container_status=$(docker inspect -f '{{{{.State.Running}}}}' {container_name} 2>/dev/null || echo "false")
if [ "$container_status" != "true" ]; then
    echo "容器状态检查失败: 未运行"
    exit 1
fi
echo "容器状态检查成功: 正在运行"
"""
                
                try:
                    # 等待容器完全启动
                    await asyncio.sleep(3)
                    # 验证容器状态
                    verify_result = await session.call_tool("execute_script", {"script": verify_script})
                    
                    if hasattr(verify_result, 'stderr') and verify_result.stderr:
                        log.error(f"容器状态验证失败: {verify_result.stderr}")
                        return {
                            "success": False,
                            "task_id": task_id,
                            "error": f"容器启动后未正常运行: {verify_result.stderr}"
                        }
                    
                    # 检查验证脚本输出
                    if hasattr(verify_result, 'stdout') and "容器状态检查成功" not in verify_result.stdout:
                        log.error(f"容器状态验证未通过: {verify_result.stdout}")
                        return {
                            "success": False,
                            "task_id": task_id,
                            "error": f"容器状态验证未通过: {verify_result.stdout}"
                        }
                    
                    log.success(f"Docker容器验证成功: {container_name}")
                    
                except Exception as e:
                    log.error(f"验证容器状态时出错: {str(e)}")
                    return {
                        "success": False,
                        "task_id": task_id,
                        "error": f"验证容器状态时出错: {str(e)}"
                    }
                
                log.success(f"Docker容器设置完成: {container_name}")
        
        return {
            "success": True,
            "task_id": task_id,
            "container_name": container_name,
            "algorithm_image": algorithm_image,
            "dataset_url": dataset_url,
            "result": {
                "stdout": result.stdout if hasattr(result, "stdout") else str(result),
                "stderr": result.stderr if hasattr(result, "stderr") else ""
            }
        }
    except Exception as e:
        log.error(f"设置Docker容器失败: {str(e)}")
        return {
            "success": False,
            "task_id": task_id,
            "error": str(e)
        }


async def execute_container_command(task_id: str, command: str) -> Dict[str, Any]:
    """
    通过MCP在远程服务器上的Docker容器中执行命令
    
    Args:
        task_id: 测试任务ID
        command: 要执行的命令
        
    Returns:
        执行结果
    """
    log.info(f"开始通过MCP在容器中执行命令: 任务={task_id}, 命令={command}")
    
    try:
        # 构建容器名称
        container_name = f"algotest_{task_id}"
        
        # 构建执行脚本
        script = f"""
# 检查容器是否存在并运行
container_status=$(docker inspect -f '{{{{.State.Running}}}}' {container_name} 2>/dev/null || echo "false")

if [ "$container_status" != "true" ]; then
    echo "容器不存在或未运行: {container_name}"
    exit 1
fi

# 在容器中执行命令
echo "在容器 {container_name} 中执行命令: {command}"
docker exec {container_name} {command}
"""
        
        log.info(f"准备通过MCP执行容器命令脚本...")
        
        # 连接到MCP服务器并执行脚本
        async with sse_client(SSE_URL) as (read, write):
            async with ClientSession(read, write) as session:
                # 初始化连接
                await session.initialize()
                log.success("MCP服务器连接成功")
                
                # 使用execute_script工具执行Docker命令脚本
                log.info("正在执行容器命令脚本...")
                result = await session.call_tool("execute_script", {"script": script})
                
                log.success(f"容器命令执行完成")
        
        return {
            "success": True,
            "task_id": task_id,
            "container_name": container_name,
            "command": command,
            "result": {
                "stdout": result.stdout if hasattr(result, "stdout") else str(result),
                "stderr": result.stderr if hasattr(result, "stderr") else ""
            }
        }
    except Exception as e:
        log.error(f"在容器中执行命令失败: {str(e)}")
        return {
            "success": False,
            "task_id": task_id,
            "command": command,
            "error": str(e)
        }


async def setup_docker_for_workflow(state: ExecutionState) -> ExecutionState:
    """
    为工作流设置Docker容器
    
    Args:
        state: 当前状态
        
    Returns:
        更新后的状态
    """
    log.info(f"为任务 {state['task_id']} 设置Docker容器")
    
    try:
        # 调用函数设置Docker容器
        result = await setup_algorithm_container(state['task_id'])
        
        if not result.get('success'):
            error_msg = result.get('error', '未知错误')
            log.error(f"设置Docker容器失败: {error_msg}")
            return {
                **state,
                "errors": state.get("errors", []) + [f"设置Docker容器失败: {error_msg}"],
                "status": "error",
                "container_ready": False
            }
        
        log.success(f"Docker容器设置成功: {result.get('container_name')}")
        
        # 更新状态
        return {
            **state,
            "algorithm_image": result.get("algorithm_image", state["algorithm_image"]),
            "dataset_url": result.get("dataset_url", state["dataset_url"]),
            "container_ready": True,
            "status": "container_ready"
        }
    except Exception as e:
        log.error(f"设置Docker容器异常: {str(e)}")
        return {
            **state,
            "errors": state.get("errors", []) + [str(e)],
            "status": "error",
            "container_ready": False
        }


def create_execution_graph() -> StateGraph:
    """
    创建执行Agent工作流图
    
    Returns:
        工作流图
    """
    # 创建工作流图
    execution_graph = StateGraph(ExecutionState)
    
    # 添加节点
    execution_graph.add_node("setup_docker", setup_docker_for_workflow)
    execution_graph.add_node("load_test_cases", load_test_cases)
    execution_graph.add_node("parse_command", parse_command)
    execution_graph.add_node("execute_command", execute_command)
    execution_graph.add_node("save_result", save_result)
    
    # 添加边
    execution_graph.add_edge("setup_docker", "load_test_cases")
    execution_graph.add_edge("load_test_cases", "parse_command")
    execution_graph.add_edge("parse_command", "execute_command")
    execution_graph.add_edge("execute_command", "save_result")
    
    # 添加条件边 - 如果需要执行下一个测试用例，回到parse_command
    execution_graph.add_conditional_edges(
        "save_result",
        lambda state: "parse_command" if state.get("status") == "next_case" else "end",
        {
            "parse_command": "parse_command",
            "end": END
        }
    )
    
    # 设置入口点和结束点
    execution_graph.set_entry_point("setup_docker")
    
    return execution_graph


async def run_execution(task_id: str, case_id: Optional[str] = None, algorithm_image: str = None, dataset_url: Optional[str] = None) -> Dict[str, Any]:
    """
    运行执行Agent
    
    Args:
        task_id: 任务ID
        case_id: 测试用例ID（可选），如果提供则只执行指定的测试用例
        algorithm_image: 算法镜像（可选，如果不提供则从数据库获取）
        dataset_url: 数据集URL（可选）
        
    Returns:
        执行结果
    """
    # 如果没有提供算法镜像，则从数据库获取
    if not algorithm_image:
        task = get_test_task(task_id)
        if not task:
            raise ValueError(f"测试任务不存在: {task_id}")
        algorithm_image = task.algorithm_image
        if not algorithm_image:
            raise ValueError(f"算法镜像未设置: {task_id}")
    
    # 创建工作流图
    execution_graph = create_execution_graph()
    
    # 编译工作流
    execution_app = execution_graph.compile()
    
    # 创建初始状态
    initial_state = {
        "task_id": task_id,
        "case_id": case_id,
        "algorithm_image": algorithm_image,
        "dataset_url": dataset_url,
        "test_cases": [],
        "current_case_index": 0,
        "command_strategy": None,
        "execution_result": None,
        "errors": [],
        "status": "created",
        "container_ready": False
    }
    
    # 运行工作流
    log.info(f"开始运行执行Agent: 任务ID={task_id}")
    result = execution_app.invoke(initial_state)
    log.info(f"执行Agent运行完成: 任务ID={task_id}, 状态: {result['status']}")
    
    return result

#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
MCP 客户端

这个客户端通过TCP连接到Docker中运行的CLI Executor MCP服务器，
使用智谱AI的API将自然语言命令转化为JSON策略，
然后通过MCP协议调用相应工具。
"""

import asyncio
import json
import os
import sys
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
import zhipuai
from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from pydantic import BaseModel


# 加载环境变量
load_dotenv()

# 智谱AI配置
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")
ZHIPU_MODEL = os.getenv("ZHIPU_MODEL_CHAT", "glm-4-flash")
ZHIPU_API_BASE = os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4")

# 检查API密钥是否设置
if not ZHIPU_API_KEY:
    print("警告: ZHIPU_API_KEY 环境变量未设置，智谱AI功能将不可用")
else:
    print(f"智谱AI API密钥: {ZHIPU_API_KEY[:5]}...{ZHIPU_API_KEY[-5:] if len(ZHIPU_API_KEY) > 10 else ''}")
    print(f"智谱AI模型: {ZHIPU_MODEL}")

# MCP服务器配置
MCP_HOST = os.getenv("MCP_HOST", "localhost")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
SSE_URL = f"http://{MCP_HOST}:{MCP_PORT}/sse"
print(f"将连接到SSE URL: {SSE_URL}")


class CommandStrategy(BaseModel):
    """命令策略模型"""
    tool: str
    parameters: Dict[str, Any]
    description: Optional[str] = None


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
            print("错误: 智谱AI API密钥未设置")
            return CommandStrategy(
                tool="list_directory",
                parameters={"path": "."},
                description="列出当前目录内容（API密钥未设置）"
            )
        
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

可用的资源:
1. system://info - 获取系统信息
   这个资源提供系统名称、主机名、发行版、Python版本等信息

可用的提示:
1. deploy_app_prompt - 创建一个部署应用的提示
   参数:
   - app_name: 应用名称
   - target_dir: 目标目录

使用说明:
- 对于单个命令，使用 execute_command
- 对于需要执行多个命令或创建文件的操作，使用 execute_script
- 对于查看目录内容的操作，使用 list_directory
- working_dir 参数可以指定命令或脚本执行的工作目录
- 如果用户想获取系统信息，直接使用 system://info 资源
- 如果用户想获取部署应用的指南，使用 deploy_app_prompt 提示

重要提示：
- 命令在Docker容器中执行，不支持sudo命令
- 如果需要apt-get等命令，请直接使用apt-get，不要加sudo
- 如果命令不存在，可能需要先安装相应的软件包
"""
        
        prompt = f"""
请将以下自然语言命令转换为JSON格式的执行策略。策略应包含要调用的工具名称和参数。

{tools_description}

自然语言命令: {command}

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
1. 如果命令涉及创建文件或执行多个命令，应该使用 execute_script
2. 如果只是查看目录内容，使用 list_directory
3. 如果是单个命令，使用 execute_command
4. 如果命令需要在特定目录下执行，添加 working_dir 参数
5. 确保参数名称和类型与工具定义完全匹配
6. 不要使用sudo命令，Docker容器中没有sudo

只返回JSON，不要有其他文字。
"""
        
        try:
            print(f"正在调用智谱AI API (模型: {self.model})...")
            
            # 使用新版本的智谱AI API
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
                print(f"API响应内容: {content[:100]}...")
                
                # 尝试解析JSON
                try:
                    strategy_dict = json.loads(content)
                    return CommandStrategy(**strategy_dict)
                except json.JSONDecodeError as e:
                    print(f"JSON解析错误: {e}")
                    # 如果直接解析失败，尝试从文本中提取JSON部分
                    import re
                    json_match = re.search(r'({[\s\S]*})', content)
                    if json_match:
                        try:
                            strategy_dict = json.loads(json_match.group(1))
                            return CommandStrategy(**strategy_dict)
                        except json.JSONDecodeError as e2:
                            print(f"提取的JSON解析错误: {e2}")
                            raise Exception(f"无法解析提取的JSON: {e2}")
                    else:
                        raise Exception("无法从智谱AI响应中提取JSON")
                
            except Exception as api_error:
                print(f"智谱AI API调用错误: {api_error}")
                raise
                
        except Exception as e:
            print(f"调用智谱AI API时出错: {e}")
            import traceback
            print(traceback.format_exc())
            
            # 返回一个默认策略
            # 根据命令内容智能选择工具
            print("使用默认策略...")
            if "目录" in command or "文件" in command and "列出" in command:
                return CommandStrategy(
                    tool="list_directory",
                    parameters={"path": "."},
                    description="列出当前目录内容（解析失败后的默认行为）"
                )
            elif "脚本" in command or "多行" in command or "创建" in command and "文件" in command:
                return CommandStrategy(
                    tool="execute_script",
                    parameters={"script": command},
                    description="执行脚本命令（解析失败后的默认行为）"
                )
            else:
                return CommandStrategy(
                    tool="execute_command",
                    parameters={"command": "ls"},
                    description="直接执行命令（解析失败后的默认行为）"
                )


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
        print(f"正在连接到MCP服务器 {self.sse_url}...")
        
        try:
            # 使用mcp库中的sse_client和ClientSession
            from mcp import ClientSession
            from mcp.client.sse import sse_client
            
            # 建立SSE连接
            print("尝试建立SSE连接...")
            async with sse_client(self.sse_url) as (read, write):
                print("SSE连接已建立，正在创建客户端会话...")
                
                # 创建客户端会话
                async with ClientSession(read, write) as session:
                    # 初始化连接
                    print("正在初始化会话...")
                    await session.initialize()
                    print("连接成功！")
                    
                    # 列出可用工具
                    print("正在获取工具列表...")
                    tools = await session.list_tools()
                    print("\n可用工具:")
                    if hasattr(tools, 'tools'):
                        for tool in tools.tools:
                            print(f"- {tool.name}: {tool.description}")
                    else:
                        print("无法获取工具列表")
                    
                    # 保存会话
                    self.session = session
                    
                    # 等待会话结束
                    while True:
                        await asyncio.sleep(0.1)
            
            return True
        except Exception as e:
            print(f"连接到MCP服务器时出错: {e}")
            import traceback
            print(traceback.format_exc())
            return False
    
    async def disconnect(self):
        """断开与MCP服务器的连接"""
        self.session = None
        print("已断开与MCP服务器的连接")
    
    async def get_system_info(self) -> str:
        """
        获取系统信息资源
        
        Returns:
            系统信息内容
        """
        if not self.session:
            raise Exception("未连接到MCP服务器")
        
        print("正在获取系统信息...")
        try:
            content, mime_type = await self.session.read_resource("system://info")
            print(f"获取到系统信息 (MIME类型: {mime_type})")
            
            # 提取用户可读的内容
            system_info = None
            
            # 先检查是否是TextResourceContents对象数组
            if hasattr(mime_type, '__iter__') and 'contents' in mime_type[0]:
                contents = mime_type[1]  # 获取内容数组
                if contents and hasattr(contents[0], 'text'):
                    system_info = contents[0].text
            
            # 如果上面的方法失败，尝试其他方法
            if not system_info:
                if isinstance(content, str):
                    system_info = content
                elif hasattr(content, 'text'):
                    system_info = content.text
                elif hasattr(content, '__iter__'):
                    # 尝试迭代内容
                    for item in content:
                        if hasattr(item, 'text'):
                            system_info = item.text
                            break
            
            # 如果仍然无法解析，则返回原始内容的字符串表示
            if not system_info:
                return f"无法解析系统信息。原始内容: {str(content)}"
            
            return system_info
            
        except Exception as e:
            print(f"获取系统信息时出错: {e}")
            import traceback
            print(traceback.format_exc())
            return f"获取系统信息失败: {e}"
    
    async def get_deploy_app_prompt(self, app_name: str, target_dir: str) -> str:
        """
        获取部署应用的提示
        
        Args:
            app_name: 应用名称
            target_dir: 目标目录
            
        Returns:
            部署应用的提示内容
        """
        if not self.session:
            raise Exception("未连接到MCP服务器")
        
        print(f"正在获取部署提示 (应用: {app_name}, 目标目录: {target_dir})...")
        try:
            prompt_response = await self.session.get_prompt("deploy_app_prompt", {
                "app_name": app_name, 
                "target_dir": target_dir
            })
            print("获取到部署提示")
            
            # 提取用户可读的提示内容
            if hasattr(prompt_response, 'messages') and prompt_response.messages:
                for message in prompt_response.messages:
                    if hasattr(message, 'content') and hasattr(message.content, 'text'):
                        return message.content.text
            
            # 如果无法提取结构化内容，返回原始响应
            return str(prompt_response)
            
        except Exception as e:
            print(f"获取部署提示时出错: {e}")
            import traceback
            print(traceback.format_exc())
            return f"获取部署提示失败: {e}"
    
    async def execute_natural_language_command(self, command: str):
        """
        执行自然语言命令
        
        Args:
            command: 自然语言命令
        """
        if not self.session:
            raise Exception("未连接到MCP服务器")
        
        print(f"\n收到自然语言命令: {command}")
        
        # 特殊命令处理
        command_lower = command.lower()
        
        # 处理列出资源和提示的请求
        if "列出" in command_lower and ("资源" in command_lower or "提示" in command_lower):
            print("检测到列出资源或提示的请求...")
            result = ""
            
            try:
                # 列出资源
                resources = await self.session.list_resources()
                if hasattr(resources, 'resources'):
                    result += "\n可用资源列表:\n"
                    for resource in resources.resources:
                        result += f"- {resource}\n"
                else:
                    result += "\n无法获取资源列表\n"
                
                # 列出提示
                prompts = await self.session.list_prompts()
                if hasattr(prompts, 'prompts'):
                    result += "\n可用提示列表:\n"
                    for prompt in prompts.prompts:
                        result += f"- {prompt.name}: {prompt.description if hasattr(prompt, 'description') else '无描述'}\n"
                else:
                    result += "\n无法获取提示列表\n"
                
                print(result)
                return result
                
            except Exception as e:
                print(f"列出资源和提示时出错: {e}")
                import traceback
                print(traceback.format_exc())
                return f"列出资源和提示时出错: {e}"
        
        # 处理获取系统信息请求
        if "系统信息" in command_lower or "system info" in command_lower:
            print("检测到系统信息请求，直接调用system://info资源...")
            result = await self.get_system_info()
            print("\n系统信息:")
            print(result)
            return result
            
        # 处理部署应用提示请求
        deploy_app_match = any(x in command_lower for x in ["部署应用", "deploy app", "应用部署"])
        if deploy_app_match:
            import re
            
            # 尝试从命令中提取应用名称
            app_name = "测试应用"  # 默认值
            app_name_match = re.search(r'应用名称[：:]\s*([^,，;；]+)|名称[：:]\s*([^,，;；]+)', command)
            if app_name_match:
                # 如果第一个捕获组匹配成功，使用第一个，否则使用第二个
                app_name = app_name_match.group(1) if app_name_match.group(1) else app_name_match.group(2)
                # 去除前后空格
                app_name = app_name.strip()
            
            # 尝试从命令中提取目标目录
            target_dir = "/tmp/app"  # 默认值
            target_dir_match = re.search(r'目标目录[：:]\s*([^,，;；]+)|目录[：:]\s*([^,，;；]+)', command)
            if target_dir_match:
                # 如果第一个捕获组匹配成功，使用第一个，否则使用第二个
                target_dir = target_dir_match.group(1) if target_dir_match.group(1) else target_dir_match.group(2)
                # 去除前后空格
                target_dir = target_dir.strip()
            
            print(f"检测到部署应用提示请求，使用参数 app_name='{app_name}', target_dir='{target_dir}'")
            result = await self.get_deploy_app_prompt(app_name, target_dir)
            print("\n部署应用提示:")
            print(result)
            return result
        
        print("正在使用智谱AI解析命令...")
        
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
            
            print(f"解析结果: {strategy}")
            print(f"将调用工具: {strategy.tool}")
            
            # 预处理参数
            if "working_dir" in strategy.parameters:
                # 处理特殊的工作目录值
                if strategy.parameters["working_dir"] in ["current_directory", ".", "current", "current dir"]:
                    print(f"将工作目录从 '{strategy.parameters['working_dir']}' 修改为 '/'")
                    strategy.parameters["working_dir"] = "/"
            
            # 对于execute_script，确保脚本不使用sudo
            if strategy.tool == "execute_script" and "script" in strategy.parameters:
                script = strategy.parameters["script"]
                if "sudo " in script:
                    clean_script = script.replace("sudo ", "")
                    print(f"移除脚本中的sudo命令: '{script}' -> '{clean_script}'")
                    strategy.parameters["script"] = clean_script
            
            # 对于execute_command，确保命令不使用sudo
            if strategy.tool == "execute_command" and "command" in strategy.parameters:
                cmd = strategy.parameters["command"]
                if cmd.startswith("sudo "):
                    clean_cmd = cmd.replace("sudo ", "", 1)
                    print(f"移除命令中的sudo: '{cmd}' -> '{clean_cmd}'")
                    strategy.parameters["command"] = clean_cmd
            
            print(f"处理后的参数: {strategy.parameters}")
            
            if strategy.description:
                print(f"描述: {strategy.description}")
            
            # 调用相应的工具
            try:
                print(f"正在调用工具 {strategy.tool}...")
                result = await self.session.call_tool(strategy.tool, strategy.parameters)
                print("\n执行结果:")
                print(result)
                return result
            except Exception as e:
                print(f"执行命令时出错: {e}")
                import traceback
                print(f"错误详情:\n{traceback.format_exc()}")
                return f"错误: {e}"
        except Exception as e:
            print(f"解析命令时出错: {e}")
            import traceback
            print(f"错误详情:\n{traceback.format_exc()}")
            
            # 尝试使用默认工具
            print("尝试使用默认工具...")
            try:
                if "目录" in command or "列出" in command:
                    print("使用list_directory工具...")
                    result = await self.session.call_tool("list_directory", {"path": "."})
                    print("\n执行结果:")
                    print(result)
                    return result
                else:
                    print("使用execute_command工具...")
                    result = await self.session.call_tool("execute_command", {"command": "ls"})
                    print("\n执行结果:")
                    print(result)
                    return result
            except Exception as e2:
                print(f"使用默认工具时出错: {e2}")
                import traceback
                print(f"错误详情:\n{traceback.format_exc()}")
                return f"错误: {e2}"


async def interactive_session():
    """交互式会话"""
    client = MCPClient(MCP_HOST, MCP_PORT)
    
    # 创建连接任务
    connect_task = asyncio.create_task(client.connect())
    
    try:
        print("\n=== MCP 交互式客户端 ===")
        print("输入自然语言命令，系统将使用智谱AI解析并执行")
        print("输入 'exit' 或 'quit' 退出")
        
        # 等待连接建立
        await asyncio.sleep(2)
        
        while True:
            command = input("\n请输入命令: ")
            
            if command.lower() in ["exit", "quit", "退出"]:
                break
                
            if not command.strip():
                continue
            
            try:    
                await client.execute_natural_language_command(command)
            except Exception as e:
                print(f"执行命令时出错: {e}")
                import traceback
                print(f"错误详情:\n{traceback.format_exc()}")
            
    except KeyboardInterrupt:
        print("\n用户中断，正在退出...")
    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        print(f"错误详情:\n{traceback.format_exc()}")
    finally:
        # 取消连接任务
        if not connect_task.done():
            connect_task.cancel()
            try:
                await connect_task
            except asyncio.CancelledError:
                pass
        await client.disconnect()


async def main():
    """主函数"""
    if len(sys.argv) > 1:
        # 命令行模式
        command = " ".join(sys.argv[1:])
        client = MCPClient(MCP_HOST, MCP_PORT)
        
        # 创建连接任务
        connect_task = asyncio.create_task(client.connect())
        
        try:
            # 等待连接建立
            await asyncio.sleep(2)
            
            try:
                await client.execute_natural_language_command(command)
            except Exception as e:
                print(f"执行命令时出错: {e}")
                import traceback
                print(f"错误详情:\n{traceback.format_exc()}")
        except Exception as e:
            print(f"连接到服务器时出错: {e}")
            import traceback
            print(f"错误详情:\n{traceback.format_exc()}")
        finally:
            # 取消连接任务
            if not connect_task.done():
                connect_task.cancel()
                try:
                    await connect_task
                except asyncio.CancelledError:
                    pass
            await client.disconnect()
    else:
        # 交互式模式
        await interactive_session()


if __name__ == "__main__":
    asyncio.run(main()) 
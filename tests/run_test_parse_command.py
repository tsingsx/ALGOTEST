#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
运行测试智谱AI命令解析功能的脚本
"""

import os
import sys
import unittest
import argparse

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# 导入测试模块
from tests.test_parse_command import TestParseCommand

def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='运行智谱AI命令解析测试')
    parser.add_argument('--verbose', '-v', action='store_true', 
                      help='输出详细的测试信息')
    args = parser.parse_args()
    
    # 创建测试套件
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestParseCommand))
    
    # 运行测试
    verbosity = 2 if args.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    # 输出结果
    print(f"\n===== 测试报告 =====")
    print(f"运行测试数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    
    # 如果有失败或错误，返回非零值
    if result.failures or result.errors:
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main()) 
# ============================================
# MCP 风格工具注册中心
# 功能：统一管理和调用所有工具
# 每个工具必须提供：
#   - name: 工具名称
#   - description: 工具描述（给 LLM 看的）
#   - parameters: 参数定义（JSON Schema 格式）
#   - execute: 执行函数
#   - validate: 验证输入参数是否合法
# ============================================

import json
from typing import Dict, List, Callable, Any, Optional

class ToolDefinition:
    """
    单个工具的定义
    
    按照 MCP 风格，每个工具包含：
    - 元数据（名称、描述、参数 Schema）
    - 执行逻辑（execute 函数）
    - 验证逻辑（validate 函数）
    """
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        execute_func: Callable,
        validate_func: Optional[Callable] = None
    ):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema 格式
        self.execute_func = execute_func
        self.validate_func = validate_func or self._default_validate
    
    def _default_validate(self, params: Dict[str, Any]) -> bool:
        """默认验证：检查必填参数是否存在"""
        required = self.parameters.get("required", [])
        for key in required:
            if key not in params or params[key] is None:
                return False
        return True
    
    def validate(self, params: Dict[str, Any]) -> bool:
        """验证输入参数"""
        return self.validate_func(params)
    
    def execute(self, params: Dict[str, Any]) -> str:
        """执行工具"""
        return self.execute_func(**params)
    
    def to_dict(self) -> Dict[str, Any]:
        """转为字典，方便序列化和给 LLM 展示"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters
        }


class ToolRegistry:
    """
    工具注册中心
    
    管理所有可用工具，提供统一的注册、查询、执行接口
    
    使用方式：
        registry = ToolRegistry()
        registry.register(tool_definition)
        result = registry.execute("工具名称", {"参数": "值"})
    """
    
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
    
    def register(self, tool: ToolDefinition) -> None:
        """注册一个工具"""
        self._tools[tool.name] = tool
        print(f"✅ 工具已注册：{tool.name}")
    
    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self._tools.get(name)
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有工具的元数据（给 LLM 看）"""
        return [tool.to_dict() for tool in self._tools.values()]
    
    def list_names(self) -> List[str]:
        """列出所有工具名称"""
        return list(self._tools.keys())
    
    def execute(self, name: str, params: Dict[str, Any]) -> str:
        """
        执行指定工具
        
        参数：
            name: 工具名称
            params: 参数字典
        
        返回：
            工具执行结果字符串
        """
        tool = self._tools.get(name)
        if not tool:
            return f"❌ 工具不存在：{name}，可用工具：{', '.join(self.list_names())}"
        
        # 先验证参数
        if not tool.validate(params):
            return f"❌ 参数验证失败，工具 {name} 需要参数：{json.dumps(tool.parameters, ensure_ascii=False)}"
        
        # 执行
        try:
            return tool.execute(params)
        except Exception as e:
            return f"❌ 工具执行异常：{str(e)[:100]}"
    
    def to_langchain_tools(self):
        """
        将注册的所有工具转为 LangChain Tool 列表
        方便直接喂给 LangChain Agent
        """
        from langchain.tools import Tool
        
        langchain_tools = []
        for tool_def in self._tools.values():
            # 创建一个包装函数，接收字符串参数，内部解析后调用 execute
            def make_func(td):
                def func(input_str: str) -> str:
                    # 尝试解析为 JSON 参数
                    try:
                        params = json.loads(input_str)
                    except json.JSONDecodeError:
                        # 如果不是 JSON，作为单个参数传入
                        params = {"query": input_str}
                    return td.execute(params)
                return func
            
            lc_tool = Tool(
                name=tool_def.name,
                func=make_func(tool_def),
                description=tool_def.description
            )
            langchain_tools.append(lc_tool)
        
        return langchain_tools


# ============================================
# 测试代码
# ============================================
if __name__ == "__main__":
    print("=" * 50)
    print("MCP 工具注册中心测试")
    print("=" * 50)
    
    # 创建一个测试工具
    def greet(name: str = "世界") -> str:
        return f"你好，{name}！"
    
    greet_tool = ToolDefinition(
        name="打招呼",
        description="向用户打招呼",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要打招呼的人名"
                }
            },
            "required": ["name"]
        },
        execute_func=greet
    )
    
    # 注册
    registry = ToolRegistry()
    registry.register(greet_tool)
    
    # 列出工具
    print("\n已注册工具：")
    for tool_info in registry.list_tools():
        print(f"  - {tool_info['name']}: {tool_info['description']}")
    
    # 执行
    print("\n执行测试：")
    result = registry.execute("打招呼", {"name": "张三"})
    print(f"  结果：{result}")
    
    # 测试参数验证
    result = registry.execute("打招呼", {})
    print(f"  缺少参数：{result}")
    
    # 测试不存在的工具
    result = registry.execute("不存在的工具", {})
    print(f"  错误工具：{result}")
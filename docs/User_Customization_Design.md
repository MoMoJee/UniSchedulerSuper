# 用户自定义配置技术方案

## 背景

当前系统的配置（API Key、专家定义、MCP 服务器等）都硬编码在代码中，不支持用户级别的自定义。本方案旨在实现：

1. **多用户隔离**：每个用户可以配置自己的 LLM Provider 和 API Key
2. **专家自定义**：用户可以启用/禁用专家，自定义 System Prompt
3. **MCP 扩展**：用户可以添加自己的 MCP 服务器（如私有工具、内部系统）
4. **安全性**：敏感信息加密存储

---

## 一、数据模型设计

### 1.1 UserAgentConfig（用户 Agent 配置）

```python
# agent_service/models.py

from django.db import models
from django.contrib.auth.models import User
from cryptography.fernet import Fernet
from django.conf import settings

class UserAgentConfig(models.Model):
    """用户的 Agent 配置"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='agent_config')
    
    # LLM 配置
    llm_provider = models.CharField(
        max_length=50, 
        choices=[
            ('openai', 'OpenAI'),
            ('deepseek', 'DeepSeek'),
            ('claude', 'Claude'),
            ('azure_openai', 'Azure OpenAI'),
            ('local', '本地模型'),
        ],
        default='deepseek'
    )
    llm_model = models.CharField(max_length=100, default='deepseek-chat')
    llm_api_key_encrypted = models.BinaryField(null=True, blank=True, help_text="加密的 API Key")
    llm_api_base = models.URLField(default='https://api.deepseek.com')
    llm_temperature = models.FloatField(default=0.0)
    llm_max_tokens = models.IntegerField(default=4000, null=True, blank=True)
    
    # 专家配置
    enabled_experts = models.JSONField(default=list, help_text="启用的专家列表 ['planner', 'map', 'chat']")
    
    # 会话配置
    max_history_messages = models.IntegerField(default=20, help_text="最大历史消息数")
    enable_memory = models.BooleanField(default=True, help_text="是否启用长期记忆")
    
    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def set_api_key(self, api_key: str):
        """加密并存储 API Key"""
        cipher = Fernet(settings.SECRET_KEY[:32].encode().ljust(32, b'='))
        self.llm_api_key_encrypted = cipher.encrypt(api_key.encode())
    
    def get_api_key(self) -> str:
        """解密并返回 API Key"""
        if not self.llm_api_key_encrypted:
            return None
        cipher = Fernet(settings.SECRET_KEY[:32].encode().ljust(32, b'='))
        return cipher.decrypt(self.llm_api_key_encrypted).decode()
    
    class Meta:
        verbose_name = "用户 Agent 配置"
        verbose_name_plural = "用户 Agent 配置"

class ExpertConfig(models.Model):
    """专家配置（用户可自定义）"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expert_configs')
    expert_name = models.CharField(max_length=50, help_text="专家名称 (planner, map, chat)")
    display_name = models.CharField(max_length=100, help_text="显示名称")
    system_prompt = models.TextField(help_text="系统提示词")
    enabled_tools = models.JSONField(default=list, help_text="启用的工具列表")
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = [['user', 'expert_name']]
        verbose_name = "专家配置"
        verbose_name_plural = "专家配置"

class MCPServerConfig(models.Model):
    """MCP 服务器配置"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mcp_servers')
    name = models.CharField(max_length=100, help_text="服务器名称")
    transport = models.CharField(
        max_length=20,
        choices=[('sse', 'SSE'), ('stdio', 'STDIO')],
        default='sse'
    )
    url = models.URLField(null=True, blank=True, help_text="SSE URL")
    command = models.CharField(max_length=200, null=True, blank=True, help_text="STDIO 命令")
    args = models.JSONField(default=list, help_text="STDIO 参数")
    api_key_encrypted = models.BinaryField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    def set_api_key(self, api_key: str):
        cipher = Fernet(settings.SECRET_KEY[:32].encode().ljust(32, b'='))
        self.api_key_encrypted = cipher.encrypt(api_key.encode())
    
    def get_api_key(self) -> str:
        if not self.api_key_encrypted:
            return None
        cipher = Fernet(settings.SECRET_KEY[:32].encode().ljust(32, b'='))
        return cipher.decrypt(self.api_key_encrypted).decode()
    
    class Meta:
        verbose_name = "MCP 服务器配置"
        verbose_name_plural = "MCP 服务器配置"
```

---

## 二、动态 Graph 构建

### 2.1 工厂模式重构

```python
# agent_service/graph_factory.py

from typing import Optional
from django.contrib.auth.models import User
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph
from .models import UserAgentConfig, ExpertConfig, MCPServerConfig
from .agent_graph import AgentState, create_supervisor_node, create_planner_agent, ...

class AgentGraphFactory:
    """为用户动态构建 Agent Graph"""
    
    @staticmethod
    def create_for_user(user: User) -> StateGraph:
        """根据用户配置创建个性化的 Agent Graph"""
        
        # 1. 获取用户配置（或使用默认配置）
        config, created = UserAgentConfig.objects.get_or_create(
            user=user,
            defaults={
                'llm_provider': 'deepseek',
                'llm_model': 'deepseek-chat',
                'enabled_experts': ['planner', 'chat'],
            }
        )
        
        # 2. 初始化 LLM
        llm = AgentGraphFactory._create_llm(config)
        
        # 3. 加载用户的专家配置
        expert_configs = AgentGraphFactory._load_expert_configs(user)
        
        # 4. 加载用户的 MCP 工具
        mcp_tools = AgentGraphFactory._load_mcp_tools(user)
        
        # 5. 构建 Graph
        workflow = StateGraph(AgentState)
        
        # 添加 Supervisor
        workflow.add_node("supervisor", create_supervisor_node(llm, config.enabled_experts))
        
        # 动态添加专家节点
        all_tools = []
        for expert_name in config.enabled_experts:
            expert_config = expert_configs.get(expert_name)
            if expert_config:
                tools = AgentGraphFactory._get_tools_for_expert(expert_name, mcp_tools)
                agent_node = AgentGraphFactory._create_agent_node(
                    llm, expert_config.system_prompt, tools
                )
                workflow.add_node(expert_name, agent_node)
                all_tools.extend(tools)
        
        # 添加工具节点
        from langgraph.prebuilt import ToolNode
        workflow.add_node("tools", ToolNode(all_tools))
        
        # 设置路由逻辑
        workflow.set_entry_point("supervisor")
        # ... (添加边和条件路由)
        
        # 编译
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        return workflow.compile(checkpointer=checkpointer)
    
    @staticmethod
    def _create_llm(config: UserAgentConfig):
        """根据配置创建 LLM 实例"""
        api_key = config.get_api_key()
        
        if config.llm_provider == 'openai':
            return ChatOpenAI(
                model=config.llm_model,
                api_key=api_key,
                temperature=config.llm_temperature,
            )
        elif config.llm_provider == 'deepseek':
            return ChatOpenAI(
                model=config.llm_model,
                api_key=api_key,
                base_url=config.llm_api_base,
                temperature=config.llm_temperature,
            )
        elif config.llm_provider == 'claude':
            return ChatAnthropic(
                model=config.llm_model,
                api_key=api_key,
                temperature=config.llm_temperature,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {config.llm_provider}")
    
    @staticmethod
    def _load_expert_configs(user: User) -> dict:
        """加载用户的专家配置"""
        configs = ExpertConfig.objects.filter(user=user, is_active=True)
        return {c.expert_name: c for c in configs}
    
    @staticmethod
    def _load_mcp_tools(user: User):
        """加载用户的 MCP 工具"""
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from asgiref.sync import async_to_sync
        
        servers = MCPServerConfig.objects.filter(user=user, is_active=True)
        if not servers:
            return []
        
        config_dict = {}
        for server in servers:
            if server.transport == 'sse':
                api_key = server.get_api_key()
                url = server.url
                if api_key:
                    url = f"{url}?key={api_key}"
                config_dict[server.name] = {
                    "url": url,
                    "transport": "sse"
                }
            elif server.transport == 'stdio':
                config_dict[server.name] = {
                    "command": server.command,
                    "args": server.args,
                    "transport": "stdio"
                }
        
        client = MultiServerMCPClient(config_dict)
        
        async def get_tools():
            return await client.get_tools()
        
        try:
            tools = async_to_sync(get_tools)()
            return tools
        except Exception as e:
            print(f"加载 MCP 工具失败: {e}")
            return []
    
    @staticmethod
    def _get_tools_for_expert(expert_name: str, mcp_tools: list):
        """根据专家名称返回对应的工具集"""
        from agent_service.tools.planner_tools import planner_tools
        from agent_service.tools.memory_tools import memory_tools
        
        if expert_name == 'planner':
            return planner_tools
        elif expert_name == 'map':
            return mcp_tools
        elif expert_name == 'chat':
            return memory_tools
        else:
            return []
```

---

## 三、使用方式

### 3.1 WebSocket Consumer 改造

```python
# agent_service/consumers.py

from .graph_factory import AgentGraphFactory

class AgentConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        
        # 动态创建用户的 Graph
        self.graph = await sync_to_async(AgentGraphFactory.create_for_user)(self.user)
        
        await self.accept()
    
    async def receive(self, text_data):
        # ... 使用 self.graph 处理消息
        pass
```

### 3.2 REST API 端点

```python
# agent_service/views_config.py

from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import UserAgentConfig

@api_view(['GET', 'PUT'])
def agent_config(request):
    """获取或更新用户的 Agent 配置"""
    config, _ = UserAgentConfig.objects.get_or_create(user=request.user)
    
    if request.method == 'GET':
        return Response({
            'llm_provider': config.llm_provider,
            'llm_model': config.llm_model,
            'llm_api_base': config.llm_api_base,
            'enabled_experts': config.enabled_experts,
            # 注意：不返回 API Key
        })
    
    elif request.method == 'PUT':
        data = request.data
        config.llm_provider = data.get('llm_provider', config.llm_provider)
        config.llm_model = data.get('llm_model', config.llm_model)
        config.llm_api_base = data.get('llm_api_base', config.llm_api_base)
        config.enabled_experts = data.get('enabled_experts', config.enabled_experts)
        
        # 如果提供了新的 API Key，更新它
        if 'llm_api_key' in data:
            config.set_api_key(data['llm_api_key'])
        
        config.save()
        return Response({'status': 'updated'})

@api_view(['POST'])
def test_api_key(request):
    """测试 API Key 的有效性"""
    provider = request.data.get('provider')
    api_key = request.data.get('api_key')
    model = request.data.get('model', 'deepseek-chat')
    
    try:
        if provider == 'deepseek':
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url='https://api.deepseek.com'
            )
            llm.invoke("test")
            return Response({'valid': True})
    except Exception as e:
        return Response({'valid': False, 'error': str(e)})
```

---

## 四、前端界面设计

### 4.1 配置页面

```html
<!-- templates/agent_settings.html -->

<div class="container">
    <h2>Agent 配置</h2>
    
    <!-- LLM 配置 -->
    <div class="card mb-3">
        <div class="card-header">LLM 配置</div>
        <div class="card-body">
            <div class="mb-3">
                <label>Provider</label>
                <select class="form-select" id="llm_provider">
                    <option value="deepseek">DeepSeek</option>
                    <option value="openai">OpenAI</option>
                    <option value="claude">Claude</option>
                </select>
            </div>
            <div class="mb-3">
                <label>API Key</label>
                <input type="password" class="form-control" id="llm_api_key">
                <button class="btn btn-sm btn-secondary mt-2" onclick="testApiKey()">测试连接</button>
            </div>
            <div class="mb-3">
                <label>Model</label>
                <input type="text" class="form-control" id="llm_model" value="deepseek-chat">
            </div>
        </div>
    </div>
    
    <!-- 专家配置 -->
    <div class="card mb-3">
        <div class="card-header">启用的专家</div>
        <div class="card-body">
            <div class="form-check">
                <input class="form-check-input" type="checkbox" id="expert_planner" checked>
                <label class="form-check-label">Planner（日程管理）</label>
            </div>
            <div class="form-check">
                <input class="form-check-input" type="checkbox" id="expert_map">
                <label class="form-check-label">Map（地图查询）</label>
            </div>
            <div class="form-check">
                <input class="form-check-input" type="checkbox" id="expert_chat" checked>
                <label class="form-check-label">Chat（闲聊助手）</label>
            </div>
        </div>
    </div>
    
    <button class="btn btn-primary" onclick="saveConfig()">保存配置</button>
</div>

<script>
function testApiKey() {
    const provider = document.getElementById('llm_provider').value;
    const apiKey = document.getElementById('llm_api_key').value;
    const model = document.getElementById('llm_model').value;
    
    fetch('/api/agent/test-api-key/', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({provider, api_key: apiKey, model})
    })
    .then(r => r.json())
    .then(data => {
        if (data.valid) {
            alert('✅ API Key 有效');
        } else {
            alert('❌ API Key 无效: ' + data.error);
        }
    });
}

function saveConfig() {
    const config = {
        llm_provider: document.getElementById('llm_provider').value,
        llm_api_key: document.getElementById('llm_api_key').value,
        llm_model: document.getElementById('llm_model').value,
        enabled_experts: []
    };
    
    if (document.getElementById('expert_planner').checked) config.enabled_experts.push('planner');
    if (document.getElementById('expert_map').checked) config.enabled_experts.push('map');
    if (document.getElementById('expert_chat').checked) config.enabled_experts.push('chat');
    
    fetch('/api/agent/config/', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(config)
    })
    .then(r => r.json())
    .then(() => alert('✅ 配置已保存'));
}
</script>
```

---

## 五、安全性考虑

### 5.1 API Key 加密

使用 Django 的 `SECRET_KEY` 派生加密密钥：

```python
from cryptography.fernet import Fernet
import base64
import hashlib

def get_encryption_key():
    """从 Django SECRET_KEY 派生加密密钥"""
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key)

cipher = Fernet(get_encryption_key())
```

### 5.2 权限控制

```python
# 确保用户只能访问自己的配置
@api_view(['GET'])
def my_config(request):
    config = UserAgentConfig.objects.get(user=request.user)
    # ...
```

### 5.3 输入验证

```python
from pydantic import BaseModel, validator

class ConfigUpdateSchema(BaseModel):
    llm_provider: str
    llm_model: str
    enabled_experts: list
    
    @validator('llm_provider')
    def validate_provider(cls, v):
        allowed = ['openai', 'deepseek', 'claude']
        if v not in allowed:
            raise ValueError(f"Provider must be one of {allowed}")
        return v
```

---

## 六、实施优先级

### P0 (核心功能)
1. ✅ UserAgentConfig 模型创建
2. ✅ API Key 加密存储
3. ✅ AgentGraphFactory 基础实现
4. ✅ REST API 端点

### P1 (增强功能)
1. ExpertConfig 自定义 System Prompt
2. MCPServerConfig 用户添加 MCP 服务器
3. 前端配置界面

### P2 (高级功能)
1. 配置热重载（无需重启）
2. 配置模板（预设配置）
3. 配置导入/导出

---

## 七、迁移路径

### 7.1 向后兼容

```python
# 默认配置，确保现有用户不受影响
def get_or_create_default_config(user):
    config, created = UserAgentConfig.objects.get_or_create(
        user=user,
        defaults={
            'llm_provider': 'deepseek',
            'llm_model': 'deepseek-chat',
            'llm_api_base': 'https://api.deepseek.com',
            'enabled_experts': ['planner', 'chat'],
        }
    )
    
    # 如果没有设置 API Key，使用系统默认的
    if not config.llm_api_key_encrypted:
        config.set_api_key(os.environ.get('DEFAULT_API_KEY', 'sk-xxx'))
        config.save()
    
    return config
```

### 7.2 渐进式升级

1. **Phase 6.1**: 创建模型和基础 API（不影响现有功能）
2. **Phase 6.2**: 改造 Graph 使用工厂模式（保留旧 Graph 作为 fallback）
3. **Phase 6.3**: 添加前端配置界面
4. **Phase 6.4**: 逐步弃用硬编码配置

---

## 八、总结

通过实施本方案，系统将支持：

✅ **多租户隔离**：每个用户独立的配置  
✅ **灵活性**：支持多种 LLM Provider  
✅ **可扩展性**：用户可添加自己的 MCP 服务  
✅ **安全性**：API Key 加密存储  
✅ **易用性**：可视化配置界面  

这将使 UniScheduler 从一个"单一配置"的系统升级为一个"多用户、可定制"的 SaaS 平台。

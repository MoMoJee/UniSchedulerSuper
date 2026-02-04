"""
记忆系统工具 V2
包含：个人信息、对话风格、工作流规则的 CRUD 工具
"""
from typing import Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from agent_service.models import UserPersonalInfo, DialogStyle, WorkflowRule
from agent_service.utils import agent_transaction
from django.db import IntegrityError

# ==========================================
# 个人信息工具
# ==========================================

@tool
@agent_transaction(action_type="save_personal_info")
def save_personal_info(key: str, value: str, description: str = "", config: RunnableConfig = None) -> str:
    """
    保存用户个人信息（新增或更新）。当用户提到个人事实、偏好或重要信息时使用。
    
    Args:
        key: 信息键，如 "姓名", "生日", "居住城市", "饮食偏好" 等
        value: 信息值
        description: 可选的补充说明
    
    Examples:
        - save_personal_info("姓名", "张三")
        - save_personal_info("居住城市", "上海", "2024年从北京搬过来")
        - save_personal_info("饮食偏好", "不吃辣")
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        info, created = UserPersonalInfo.objects.update_or_create(
            user=user,
            key=key,
            defaults={
                'value': value,
                'description': description
            }
        )
        action = "保存" if created else "更新"
        return f"✅ 已{action}个人信息: {key} = {value}"
    except Exception as e:
        return f"❌ 保存失败: {str(e)}"


@tool
def get_personal_info(key: str = None, config: RunnableConfig = None) -> str:
    """
    获取用户个人信息。可指定 key 获取单条信息，或不指定获取全部。
    
    Args:
        key: 可选，要查询的信息键。不指定则返回全部个人信息。
    
    Examples:
        - get_personal_info() -> 获取全部个人信息
        - get_personal_info("居住城市") -> 获取居住城市
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        if key:
            info = UserPersonalInfo.objects.filter(user=user, key=key).first()
            if info:
                result = f"📌 {info.key}: {info.value}"
                if info.description:
                    result += f" ({info.description})"
                return result
            else:
                return f"未找到关于 '{key}' 的个人信息"
        else:
            infos = UserPersonalInfo.objects.filter(user=user)
            if not infos.exists():
                return "暂无保存的个人信息"
            
            result = "📌 用户个人信息:\n"
            for info in infos:
                line = f"- {info.key}: {info.value}"
                if info.description:
                    line += f" ({info.description})"
                result += line + "\n"
            return result.strip()
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"


@tool
@agent_transaction(action_type="update_personal_info")
def update_personal_info(key: str, new_value: str, new_description: str = None, config: RunnableConfig = None) -> str:
    """
    更新已有的个人信息。用于修正或更新用户之前保存的信息。
    
    Args:
        key: 要更新的信息键
        new_value: 新的信息值
        new_description: 可选，新的补充说明。如果不提供则保留原说明。
    
    Examples:
        - update_personal_info("居住城市", "上海", "2024年12月搬家")
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        info = UserPersonalInfo.objects.filter(user=user, key=key).first()
        if not info:
            return f"❌ 未找到关于 '{key}' 的个人信息，无法更新"
        
        old_value = info.value
        info.value = new_value
        if new_description is not None:
            info.description = new_description
        info.save()
        
        return f"✅ 已更新个人信息:\n【之前】{key}: {old_value}\n【之后】{key}: {new_value}"
    except Exception as e:
        return f"❌ 更新失败: {str(e)}"


@tool
@agent_transaction(action_type="delete_personal_info")
def delete_personal_info(key: str, config: RunnableConfig = None) -> str:
    """
    删除指定的个人信息。
    
    Args:
        key: 要删除的信息键
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        info = UserPersonalInfo.objects.filter(user=user, key=key).first()
        if not info:
            return f"❌ 未找到关于 '{key}' 的个人信息"
        
        old_value = info.value
        info.delete()
        return f"✅ 已删除个人信息: {key} = {old_value}"
    except Exception as e:
        return f"❌ 删除失败: {str(e)}"


# ==========================================
# 对话风格工具
# ==========================================

@tool
def get_dialog_style(config: RunnableConfig = None) -> str:
    """
    获取当前的对话风格模板。查看用户自定义的 Agent 人格设定。
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        style = DialogStyle.get_or_create_default(user)
        return f"💬 当前对话风格模板:\n\n{style.content}"
    except Exception as e:
        return f"❌ 获取失败: {str(e)}"


@tool
@agent_transaction(action_type="update_dialog_style")
def update_dialog_style(content: str, config: RunnableConfig = None) -> str:
    """
    更新对话风格模板。修改 Agent 的人格设定和回答风格。
    
    Args:
        content: 新的对话风格模板（完整内容）
    
    注意: 这会完全替换现有的对话风格模板
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        style = DialogStyle.get_or_create_default(user)
        old_preview = style.content[:100] + "..." if len(style.content) > 100 else style.content
        style.content = content
        style.save()
        
        new_preview = content[:100] + "..." if len(content) > 100 else content
        return f"✅ 对话风格已更新\n【之前】{old_preview}\n【之后】{new_preview}"
    except Exception as e:
        return f"❌ 更新失败: {str(e)}"


# ==========================================
# 工作流规则工具
# ==========================================

@tool
@agent_transaction(action_type="save_workflow_rule")
def save_workflow_rule(name: str, trigger: str, steps: str, config: RunnableConfig = None) -> str:
    """
    保存工作流程规则。为复杂多步骤任务定义执行流程指导。
    
    Args:
        name: 规则名称，如 "创建日程流程"
        trigger: 触发条件描述，如 "当用户要求创建日程时"
        steps: 纯文本步骤描述，如 "1.确认时间 2.确认地点 3.设置提醒"
    
    Examples:
        save_workflow_rule(
            name="创建日程流程",
            trigger="当用户要求创建日程时",
            steps="1. 先确认是否有时间冲突\n2. 确认具体时间\n3. 确认地点\n4. 询问是否需要提醒"
        )
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        rule, created = WorkflowRule.objects.update_or_create(
            user=user,
            name=name,
            defaults={
                'trigger': trigger,
                'steps': steps,
                'is_active': True
            }
        )
        action = "创建" if created else "更新"
        return f"✅ 已{action}工作流规则: {name}\n触发条件: {trigger}\n步骤:\n{steps}"
    except Exception as e:
        return f"❌ 保存失败: {str(e)}"


@tool
def get_workflow_rules(trigger: str = None, config: RunnableConfig = None) -> str:
    """
    获取工作流规则。可按触发条件筛选，或获取全部规则。
    
    Args:
        trigger: 可选，按触发条件关键词筛选
    
    Examples:
        - get_workflow_rules() -> 获取全部规则
        - get_workflow_rules("创建日程") -> 获取与创建日程相关的规则
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        rules = WorkflowRule.objects.filter(user=user, is_active=True)
        
        if trigger:
            rules = rules.filter(trigger__icontains=trigger)
        
        if not rules.exists():
            if trigger:
                return f"未找到与 '{trigger}' 相关的工作流规则"
            else:
                return "暂无保存的工作流规则"
        
        result = "⚙️ 工作流规则:\n"
        for rule in rules:
            result += f"\n【{rule.name}】\n"
            result += f"触发: {rule.trigger}\n"
            result += f"步骤:\n{rule.steps}\n"
        
        return result.strip()
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"


@tool
@agent_transaction(action_type="update_workflow_rule")
def update_workflow_rule(
    name: str, 
    trigger: str = None, 
    steps: str = None, 
    is_active: bool = None, 
    config: RunnableConfig = None
) -> str:
    """
    更新工作流规则。可更新触发条件、步骤或启用状态。
    
    Args:
        name: 要更新的规则名称
        trigger: 可选，新的触发条件
        steps: 可选，新的步骤描述
        is_active: 可选，是否启用
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        rule = WorkflowRule.objects.filter(user=user, name=name).first()
        if not rule:
            return f"❌ 未找到名为 '{name}' 的工作流规则"
        
        changes = []
        if trigger is not None:
            old_trigger = rule.trigger
            rule.trigger = trigger
            changes.append(f"触发条件: {old_trigger} → {trigger}")
        
        if steps is not None:
            old_steps = rule.steps[:50] + "..." if len(rule.steps) > 50 else rule.steps
            rule.steps = steps
            new_steps = steps[:50] + "..." if len(steps) > 50 else steps
            changes.append(f"步骤: {old_steps} → {new_steps}")
        
        if is_active is not None:
            old_status = "启用" if rule.is_active else "禁用"
            rule.is_active = is_active
            new_status = "启用" if is_active else "禁用"
            changes.append(f"状态: {old_status} → {new_status}")
        
        if not changes:
            return "未提供任何更新内容"
        
        rule.save()
        return f"✅ 已更新工作流规则 '{name}':\n" + "\n".join(changes)
    except Exception as e:
        return f"❌ 更新失败: {str(e)}"


@tool
@agent_transaction(action_type="delete_workflow_rule")
def delete_workflow_rule(name: str, config: RunnableConfig = None) -> str:
    """
    删除工作流规则。
    
    Args:
        name: 要删除的规则名称
    """
    user = config.get("configurable", {}).get("user")
    if not user:
        return "Error: 用户未登录"
    
    try:
        rule = WorkflowRule.objects.filter(user=user, name=name).first()
        if not rule:
            return f"❌ 未找到名为 '{name}' 的工作流规则"
        
        rule.delete()
        return f"✅ 已删除工作流规则: {name}"
    except Exception as e:
        return f"❌ 删除失败: {str(e)}"


# ==========================================
# 导出工具列表
# ==========================================

PERSONAL_INFO_TOOLS = [
    save_personal_info,
    get_personal_info,
    update_personal_info,
    delete_personal_info,
]

DIALOG_STYLE_TOOLS = [
    get_dialog_style,
    update_dialog_style,
]

WORKFLOW_RULE_TOOLS = [
    save_workflow_rule,
    get_workflow_rules,
    update_workflow_rule,
    delete_workflow_rule,
]

# 所有记忆工具 V2
ALL_MEMORY_TOOLS_V2 = PERSONAL_INFO_TOOLS + DIALOG_STYLE_TOOLS + WORKFLOW_RULE_TOOLS

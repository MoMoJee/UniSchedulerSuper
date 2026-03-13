"""
Agent Skill 工具
让 Agent 能够创建和列举用户的技能
"""
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from agent_service.models import AgentSkill
from agent_service.views_skills_api import _sanitize_content
from logger import logger


@tool
def save_skill(name: str, description: str, content: str, config: RunnableConfig = None) -> str:
    """
    保存一个用户技能（新增或覆盖同名技能）。当用户要求将某段工作流程、行为规则或专业知识沉淀为可复用的技能时使用。

    Args:
        name: 技能名称，简短明确，如 "会议纪要生成"、"日报撰写流程"
        description: 技能的简短描述（供筛选器阅读），说明该技能适用于什么场景
        content: 技能的完整内容，纯文本格式
    """
    user = config.get("configurable", {}).get("user") if config else None
    if not user:
        return "Error: 用户未登录"

    # 安全过滤
    try:
        content = _sanitize_content(content)
        description = _sanitize_content(description)
    except ValueError as e:
        return f"❌ 内容不安全: {e}"

    if not name or not description or not content:
        return "❌ 名称、描述、内容均不能为空"

    try:
        skill, created = AgentSkill.objects.update_or_create(
            user=user,
            name=name.strip(),
            defaults={
                'description': description.strip(),
                'content': content,
                'source': 'ai',
            }
        )
        action = "创建" if created else "更新"
        return f"✅ 已{action}技能: {skill.name}"
    except Exception as e:
        logger.exception(f"保存技能失败: {e}")
        return f"❌ 保存失败: {e}"


@tool
def list_skills(config: RunnableConfig = None) -> str:
    """
    列出当前用户的所有技能。用于查看已保存的技能列表。
    """
    user = config.get("configurable", {}).get("user") if config else None
    if not user:
        return "Error: 用户未登录"

    skills = AgentSkill.objects.filter(user=user).order_by('-created_at')
    if not skills.exists():
        return "当前没有保存任何技能。"

    lines = []
    for s in skills:
        status_icon = "✓" if s.is_active else "✗"
        lines.append(f"[{status_icon}] {s.name} — {s.description} (来源: {s.get_source_display()})")
    return f"共 {len(lines)} 个技能:\n" + "\n".join(lines)


# 工具映射（供 agent_graph.py 注册使用）
SKILL_TOOLS = {
    "save_skill": save_skill,
    "list_skills": list_skills,
}

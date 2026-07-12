import ast
import io
import json
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from reversion.models import Revision, Version

from agent_service.models import AgentTransaction as AgentServiceTransaction
from core.models import AgentTransaction as CoreAgentTransaction
from core.models import PlannerChangeSet
from core.planner.p4_contract import (
    MCP_TOOL_PARAMETER_CONTRACTS,
    P4_ENTRYPOINT_INVENTORY,
    PLANNER_TOOL_PARAMETER_CONTRACTS,
    ROLLBACK_ROUTE_CONTRACTS,
)


def _function_parameters(path: Path, decorator_name: str) -> dict[str, tuple[str, ...]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorated = False
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Name) and target.id == decorator_name:
                decorated = True
            elif isinstance(target, ast.Attribute) and target.attr == decorator_name:
                decorated = True
        if decorated:
            result[node.name] = tuple(item.arg for item in node.args.args)
    return result


class P4ContractBaselineTests(TestCase):
    def setUp(self):
        self.root = Path(settings.BASE_DIR)

    def test_unified_and_mcp_public_tool_signatures_are_frozen(self):
        unified = _function_parameters(
            self.root / "agent_service/tools/unified_planner_tools.py", "tool"
        )
        self.assertEqual(
            {name: unified[name] for name in PLANNER_TOOL_PARAMETER_CONTRACTS},
            PLANNER_TOOL_PARAMETER_CONTRACTS,
        )
        mcp = _function_parameters(self.root / "mcp_server.py", "tool")
        self.assertEqual(
            {name: mcp[name] for name in MCP_TOOL_PARAMETER_CONTRACTS},
            MCP_TOOL_PARAMETER_CONTRACTS,
        )

    def test_agent_rollback_routes_are_frozen(self):
        source = (self.root / "agent_service/urls.py").read_text(encoding="utf-8")
        for route in ROLLBACK_ROUTE_CONTRACTS:
            self.assertIn(f"path('{route}'", source)

    def test_p4_audit_commands_are_read_only(self):
        before = {
            "revisions": Revision.objects.count(),
            "versions": Version.objects.count(),
            "agent_transactions": AgentServiceTransaction.objects.count(),
            "core_transactions": CoreAgentTransaction.objects.count(),
            "changesets": PlannerChangeSet.objects.count(),
        }
        storage_output = io.StringIO()
        call_command("audit_planner_rollback_storage", stdout=storage_output)
        storage = json.loads(storage_output.getvalue())
        self.assertIn("serialized_bytes", storage["summary"])

        entrypoint_output = io.StringIO()
        call_command("audit_planner_p4_entrypoints", stdout=entrypoint_output)
        entrypoints = json.loads(entrypoint_output.getvalue())
        self.assertEqual(entrypoints["summary"]["missing_file_count"], 0)
        self.assertEqual(entrypoints["summary"]["inventory_count"], len(P4_ENTRYPOINT_INVENTORY))

        after = {
            "revisions": Revision.objects.count(),
            "versions": Version.objects.count(),
            "agent_transactions": AgentServiceTransaction.objects.count(),
            "core_transactions": CoreAgentTransaction.objects.count(),
            "changesets": PlannerChangeSet.objects.count(),
        }
        self.assertEqual(after, before)

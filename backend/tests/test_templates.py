"""内置示例工作流模板库测试（V1.1 遗留项）。

覆盖：模板列表非空、每个模板通过 validate_workflow、可经 RunService 端到端运行成功。
"""

from app.core.dag import validate_workflow
from app.core.runs import RunService, RunStatus
from app.templates import BUILTIN_TEMPLATES, get_template, list_templates


def test_templates_non_empty():
    assert len(list_templates()) >= 2


def test_each_template_validates():
    for t in BUILTIN_TEMPLATES:
        graph = validate_workflow(t["nodes"], t["edges"])  # 不抛异常即通过
        assert graph.nodes


def test_get_template_lookup():
    assert get_template("ma_cross") is not None
    assert get_template("nope") is None


def test_templates_run_end_to_end():
    svc = RunService(backend="local")
    for t in BUILTIN_TEMPLATES:
        resp = svc.submit(t["nodes"], t["edges"], workflow_name=f"tpl_{t['id']}")
        rec = svc.wait(resp["run_id"], timeout=30)
        assert rec["status"] == RunStatus.SUCCEEDED, (
            f"模板 {t['id']} 运行失败: {rec.get('result')}"
        )
        # 回测节点应产出 summary
        assert rec["nodes"]["bt"]["status"] == RunStatus.SUCCEEDED

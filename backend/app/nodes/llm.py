"""LLM 策略助手节点（V1.1 N1）。

llm.assistant：在 DAG 中调用 LLM provider，输出文本。
无 key 环境下自动走 MockProvider，保证工作流可跑通。
"""

from typing import Any, Dict

from ..core.llm import LLMMessage, get_provider
from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node


@work_node(
    "llm.assistant",
    label="LLM 策略助手",
    category="AI",
    description="调用 LLM（mock / OpenAI 兼容）生成策略建议文本",
    outputs=[PortSpec("text", "string")],
    params=[
        ParamSpec("prompt", "string", default="", label="提示词", required=True),
        ParamSpec("system", "string", default="你是一名量化策略助手。", label="系统提示"),
    ],
)
class LLMAssistantNode(BaseWorkNode):
    def execute(self, ctx, inputs) -> Dict[str, Any]:
        prompt = self.params["prompt"] or ""
        messages = [
            LLMMessage(role="system", content=self.params["system"]),
            LLMMessage(role="user", content=prompt),
        ]
        text = get_provider().chat(messages)
        return {"text": text}

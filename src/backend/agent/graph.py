from langgraph.graph import END, START, StateGraph

from src.backend.agent.context import AgentContext
from src.backend.agent.nodes import (
    approval_node,
    document_node,
    finalize_node,
    model_node,
    prepare_node,
    retrieval_node,
    route_after_approval,
    route_after_model,
    summarize_node,
    tool_node,
)
from src.backend.agent.state import AgentState
from src.backend.services.checkpoint import checkpointer


builder = StateGraph(AgentState, context_schema=AgentContext)

builder.add_node("prepare", prepare_node)
builder.add_node("summarize", summarize_node)
builder.add_node("model", model_node)
builder.add_node("approval", approval_node)
builder.add_node("tools", tool_node)
builder.add_node("document", document_node)
builder.add_node("retrieval", retrieval_node)
builder.add_node("finalize", finalize_node)

builder.add_edge(START, "prepare")
builder.add_edge("prepare", "summarize")
builder.add_edge("summarize", "model")
builder.add_conditional_edges(
    "model",
    route_after_model,
    {
        "finalize": "finalize",
        "approval": "approval",
    },
)
builder.add_conditional_edges(
    "approval",
    route_after_approval,
    {
        "tools": "tools",
        "document": "document",
        "retrieval": "retrieval",
    },
)
builder.add_edge("tools", "summarize")
builder.add_edge("document", "summarize")
builder.add_edge("retrieval", "summarize")
builder.add_edge("finalize", END)

graph = builder.compile(checkpointer=checkpointer)

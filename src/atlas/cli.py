from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from atlas.app import AtlasApp, build_app
from atlas.config import AtlasConfig
from atlas.demo import DEMO_TASK, demo_knowledge, seed_memory
from atlas.memory.long_term import InMemoryStore
from atlas.rag.hybrid import KnowledgeBase
from atlas.types import Trajectory

_SUFFIXES = ("*.md", "*.txt")


def load_knowledge_dir(path: Path) -> KnowledgeBase:
    """把目录下的 Markdown/文本文件装入知识库；doc_id 由相对路径生成。"""

    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"knowledge directory not found: {root}")

    knowledge = KnowledgeBase()
    files: list[Path] = []
    for pattern in _SUFFIXES:
        files.extend(root.glob(f"**/{pattern}"))
    for file_path in sorted(set(files)):
        content = file_path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        relative = file_path.relative_to(root).with_suffix("")
        doc_id = relative.as_posix()
        knowledge.add_document(
            doc_id,
            content,
            str(file_path),
            title=file_path.stem,
        )
    return knowledge


def _memory_size(app: AtlasApp) -> int:
    items = getattr(app.memory, "all", None)
    return len(items()) if callable(items) else 0


def _payload(task: str, trajectory: Trajectory, app: AtlasApp) -> dict[str, Any]:
    report = app.last_report
    return {
        "task": task,
        "answer": trajectory.final_answer,
        "stop_reason": trajectory.stop_reason,
        "steps": len(trajectory.steps),
        "tool_calls": sum(len(step.tool_calls) for step in trajectory.steps),
        "total_tokens": trajectory.usage.total_tokens,
        "citations": list(report.cited) if report else [],
        "unknown_citations": list(report.unknown) if report else [],
        "retrieval_count": report.queries if report else 0,
        "memory_items": _memory_size(app),
    }


def _print_text(payload: dict[str, Any], *, offline: bool) -> None:
    header = "Atlas · 离线演示" if offline else "Atlas"
    print(header)
    print(f"任务：{payload['task']}")
    print(f"答案：{payload['answer']}")
    print(
        f"停止原因：{payload['stop_reason']} ｜ 步骤：{payload['steps']} ｜ "
        f"工具调用：{payload['tool_calls']} ｜ 令牌：{payload['total_tokens']}"
    )
    citations = payload["citations"]
    if citations or payload["retrieval_count"]:
        print(
            f"引用：{'、'.join(citations) or '无'} ｜ "
            f"检索：{payload['retrieval_count']} 次"
        )
    if payload["unknown_citations"]:
        print("未找到出处的引用：" + "、".join(payload["unknown_citations"]))
    print(f"长期记忆：{payload['memory_items']} 条")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas",
        description="Atlas 研究助手：装配记忆、检索、上下文预算与引用审计。",
    )
    parser.add_argument("task", nargs="?", help="要执行的任务")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="使用内置知识库与脚本模型，不调用真实 API",
    )
    parser.add_argument("--model", help="覆盖 ATLAS_MODEL")
    parser.add_argument("--max-steps", type=int, help="覆盖最大步数")
    parser.add_argument(
        "--knowledge-dir",
        type=Path,
        help="把目录下的 Markdown/文本文件装入知识库",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读的 JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = AtlasConfig.from_env()
    if args.model:
        config.model = args.model
    if args.max_steps is not None:
        config.budget.max_steps = args.max_steps

    offline = bool(args.offline or config.offline)
    config.offline = offline
    if not offline and not args.task:
        parser.error("需要提供任务，或使用 --offline 运行演示")

    task = args.task or DEMO_TASK
    memory = InMemoryStore()
    knowledge = None
    if offline:
        seed_memory(memory)
        knowledge = demo_knowledge()
    elif args.knowledge_dir is not None:
        try:
            knowledge = load_knowledge_dir(args.knowledge_dir)
        except ValueError as exc:
            parser.error(str(exc))
        if not knowledge.chunks:
            parser.error(f"知识库为空：{args.knowledge_dir}")

    app = build_app(config, knowledge=knowledge, memory=memory)
    trajectory = app.run(task)
    payload = _payload(task, trajectory, app)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload, offline=offline)
    return 0

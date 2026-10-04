"""Commands keep the demo and model-backed execution modes explicit."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv


def main():
    load_dotenv(Path.cwd() / ".env", override=False)
    parser = argparse.ArgumentParser(description="商策助手 — 本地电商运营诊断")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="启动127.0.0.1本地工作台")
    serve.add_argument("--port", type=int, default=8877)
    evaluate = commands.add_parser("evaluate", help="运行20条模拟业务回归")
    evaluate.add_argument("--output", type=Path)
    index = commands.add_parser("index", help="通过配置的真实LightRAG建立规则索引")
    index.add_argument(
        "--curated-graph", action="store_true", help="使用人工图谱；仍需配置真实Embedding服务"
    )
    args = parser.parse_args()
    if args.command == "serve":
        if not 1 <= args.port <= 65535:
            parser.error("port must be between 1 and 65535")
        import uvicorn

        uvicorn.run(
            "commerceops.app:create_app",
            factory=True,
            host="127.0.0.1",
            port=args.port,
            log_level="info",
        )
        return
    from .evaluation import run_evaluation
    from .retrieval import from_environment, load_evidence

    data_dir = Path(os.getenv("COMMERCEOPS_DATA_DIR", "var")).resolve()
    backend = from_environment(data_dir / "lightrag", load_evidence())

    async def operation():
        try:
            if hasattr(backend, "initialize"):
                await backend.initialize()
            if args.command == "index":
                if not hasattr(backend, "ingest"):
                    parser.error(
                        "index requires COMMERCEOPS_RETRIEVAL=lightrag and model configuration"
                    )
                await backend.ingest(curated_graph=args.curated_graph)
                print("规则索引已建立：demo-v3。停止索引进程后可启动工作台。")
            else:
                result = await run_evaluation(backend, args.output or data_dir / "evaluation.json")
                print(
                    json.dumps(
                        {
                            "backend": result["backend"],
                            "scope": result["scope"],
                            "summary": result["summary"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0 if result["summary"]["failed"] == 0 else 1
        finally:
            if hasattr(backend, "close"):
                await backend.close()
        return 0

    try:
        code = asyncio.run(operation())
    except Exception as exc:
        parser.exit(
            1,
            f"执行失败（{type(exc).__name__}）。请检查配置、索引目录和模型服务；未切换为假成功结果。\n",
        )
    raise SystemExit(code)

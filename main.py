from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from welfare_agent.server import create_server


mcp = create_server()


if __name__ == "__main__":
    from welfare_agent.config import load_settings

    settings = load_settings()
    # FastMCP Streamable HTTP 서버를 설정된 host/port/path로 실행한다.
    mcp.run(transport="http", host=settings.host, port=settings.port, path=settings.path)

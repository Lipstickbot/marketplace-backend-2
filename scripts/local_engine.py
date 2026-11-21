"""Launch the friend's unmodified engine in an explicitly local mock mode."""
from pathlib import Path
import sys


def create_app():
    root = Path(__file__).resolve().parents[1]
    from backend.app.config import Settings as PlatformSettings
    platform = PlatformSettings.from_env()
    if not platform.engine_jwt_secret:
        raise RuntimeError("Run scripts/configure_local_engine.py first")
    source = root / "ai-engine-upstream" / "ai-engine"
    if not (source / "app" / "main.py").exists():
        raise RuntimeError("AI Engine checkout is missing; run scripts/setup-engine.ps1")
    sys.path.insert(0, str(source))
    from app.core.config import Settings
    from app.main import create_app as upstream_create_app
    return upstream_create_app(Settings(
        llm_provider="mock", app_env="development", enable_demo_ui=False,
        database_url=f"sqlite:///{(root / '.run' / 'engine.db').as_posix()}",
        storage_dir=root / ".run" / "engine-files",
        jwt_secret=platform.engine_jwt_secret, jwt_audience=platform.engine_jwt_audience,
        jwt_issuer=platform.engine_jwt_issuer, demo_api_key=None,
        daily_run_limit_per_user=10, extraction_memory_mb=0,
    ))

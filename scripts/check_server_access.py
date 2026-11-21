"""Read-only validation of the server key; never prints keys or row data."""
import httpx

from backend.app.config import Settings


def main():
    settings = Settings.from_env()
    if settings.supabase_secret_key is None:
        raise RuntimeError("Server key is not configured")
    with httpx.Client(base_url=settings.supabase_url, timeout=20, trust_env=False,
                      headers={"apikey": settings.supabase_secret_key.get_secret_value()}) as client:
        database = client.get("/rest/v1/agent_runs", params={"select": "id", "limit": "1"})
        if database.status_code != 200:
            raise RuntimeError(f"Database access returned HTTP {database.status_code}")
        bucket = client.get("/storage/v1/bucket/agent-files")
        if bucket.status_code != 200:
            raise RuntimeError(f"Storage access returned HTTP {bucket.status_code}")
        assert bucket.json()["public"] is False
        print({"database_access": "ok", "private_storage_access": "ok", "secret_displayed": False})


if __name__ == "__main__":
    main()

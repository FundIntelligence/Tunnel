import os
from typing import Optional, Union

from supabase import create_client
from supabase.lib.client_options import SyncClientOptions
from dotenv import load_dotenv

load_dotenv()


def get_supabase(timeout: Optional[Union[int, float]] = None):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    if timeout is None:
        return create_client(url, key)
    return create_client(url, key, options=SyncClientOptions(postgrest_client_timeout=timeout))

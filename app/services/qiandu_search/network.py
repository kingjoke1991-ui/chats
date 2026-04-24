import asyncio
import random
from typing import Any, Dict, Optional

try:
    from curl_cffi import requests as async_requests
except ImportError:
    async_requests = None

class QianduStealthRequester:
    """Stealthy requester using curl_cffi for JA3 fingerprinting and H2 support."""

    CHROME_VERSIONS = ["chrome110", "chrome116", "chrome120"]

    @classmethod
    async def get(
        self, 
        url: str, 
        params: Optional[Dict[str, Any]] = None, 
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        impersonate: Optional[str] = None
    ) -> str:
        if not async_requests:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, headers=headers, timeout=timeout)
                return resp.text

        loop = asyncio.get_event_loop()
        
        target_impersonate = impersonate or random.choice(self.CHROME_VERSIONS)
        
        # curl_cffi's async requests are actually synchronous calls wrapped in threads or similar 
        # unless using the AsyncSession. For simplicity in a single call:
        def _fetch():
            return async_requests.get(
                url, 
                params=params, 
                headers=headers, 
                timeout=timeout, 
                impersonate=target_impersonate
            )

        resp = await loop.run_in_executor(None, _fetch)
        return resp.text

    @classmethod
    async def post(
        self, 
        url: str, 
        data: Optional[Any] = None, 
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        impersonate: Optional[str] = None
    ) -> str:
        if not async_requests:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, data=data, json=json, headers=headers, timeout=timeout)
                return resp.text

        loop = asyncio.get_event_loop()
        target_impersonate = impersonate or random.choice(self.CHROME_VERSIONS)

        def _fetch():
            return async_requests.post(
                url, 
                data=data, 
                json=json, 
                headers=headers, 
                timeout=timeout, 
                impersonate=target_impersonate
            )

        resp = await loop.run_in_executor(None, _fetch)
        return resp.text

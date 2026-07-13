"""Small dependency-free contract client shared by the examples."""

from __future__ import annotations

import os
from typing import Any

import requests


BASE_URL = os.getenv("UNISCHEDULER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.getenv("UNISCHEDULER_USERNAME", "")
PASSWORD = os.getenv("UNISCHEDULER_PASSWORD", "")


class ApiError(RuntimeError):
    def __init__(self, response: requests.Response):
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        super().__init__(f"HTTP {response.status_code}: {payload}")
        self.response = response
        self.payload = payload


class UniSchedulerClient:
    def __init__(self, base_url: str = BASE_URL, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Token {token}"

    def login(self, username: str = USERNAME, password: str = PASSWORD) -> str:
        if not username or not password:
            raise RuntimeError(
                "请先设置 UNISCHEDULER_USERNAME 与 UNISCHEDULER_PASSWORD 环境变量"
            )
        response = self.session.post(
            f"{self.base_url}/api/auth/login/",
            json={"username": username, "password": password},
            timeout=15,
        )
        self._raise(response)
        token = response.json()["token"]
        self.session.headers["Authorization"] = f"Token {token}"
        return token

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        response = self.session.request(method, f"{self.base_url}{path}", **kwargs)
        self._raise(response)
        return response

    def json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request(method, path, **kwargs).json()

    @staticmethod
    def _raise(response: requests.Response) -> None:
        if not response.ok:
            raise ApiError(response)


def authenticated_client() -> UniSchedulerClient:
    client = UniSchedulerClient()
    client.login()
    return client

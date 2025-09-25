"""FastAPI application serving the admin portal."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .client import (
    ExecutorClient,
    ExecutorHealth,
    ExecutorTaskDetail,
    ExecutorTaskSummary,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def status_class(status: str) -> str:
    mapping = {
        "pending": "status-pending",
        "running": "status-running",
        "waiting_for_user": "status-waiting",
        "paused": "status-paused",
        "completed": "status-success",
        "failed": "status-failed",
        "available": "status-success",
        "configured": "status-success",
        "missing_credentials": "status-paused",
        "unavailable": "status-failed",
        "error": "status-failed",
        "unknown": "status-unknown",
    }
    return mapping.get(status.lower(), "status-unknown")


def format_datetime(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M:%S")


templates.env.globals.update({
    "status_class": status_class,
    "format_datetime": format_datetime,
})


@dataclass
class ExecutorEndpoint:
    key: str
    label: str
    base_url: str


class ExecutorRegistry:
    def __init__(self, endpoints: Iterable[ExecutorEndpoint] | None = None) -> None:
        self._items: dict[str, ExecutorEndpoint] = {}
        for endpoint in endpoints or []:
            self._items[endpoint.key] = endpoint

    def all(self) -> list[ExecutorEndpoint]:
        return list(self._items.values())

    def get(self, key: str) -> ExecutorEndpoint:
        try:
            return self._items[key]
        except KeyError:
            raise HTTPException(status_code=404, detail="Executor not found") from None

    def add(self, label: str, base_url: str) -> ExecutorEndpoint:
        normalized_label = label.strip() or base_url.strip()
        normalized_url = base_url.strip()
        for item in self._items.values():
            if item.base_url == normalized_url:
                return item
        key = self._generate_unique_key(normalized_label)
        endpoint = ExecutorEndpoint(key=key, label=normalized_label, base_url=normalized_url)
        self._items[key] = endpoint
        return endpoint

    def _generate_unique_key(self, label: str) -> str:
        base_key = _slugify(label)
        if not base_key:
            base_key = "executor"
        key = base_key
        counter = 1
        while key in self._items:
            counter += 1
            key = f"{base_key}-{counter}"
        return key


class AdminApplication:
    def __init__(self, registry: ExecutorRegistry) -> None:
        self._registry = registry

    def create_app(self) -> FastAPI:
        app = FastAPI(title="Remote Browser Tool Admin")
        router = APIRouter()

        @router.get("/", response_class=HTMLResponse, name="admin_home")
        async def home(request: Request) -> HTMLResponse:
            rows: list[dict[str, object]] = []
            for endpoint in self._registry.all():
                client = ExecutorClient(endpoint.base_url)
                health: ExecutorHealth | None = None
                error: str | None = None
                try:
                    health = await client.get_health()
                except httpx.HTTPError as exc:
                    error = str(exc)
                rows.append({"endpoint": endpoint, "health": health, "error": error})
            return templates.TemplateResponse(
                request,
                "index.html",
                {"executors": rows},
            )

        @router.post("/executors", name="register_executor")
        async def register_executor(request: Request) -> RedirectResponse:
            form = await request.form()
            label = (form.get("label") or "").strip()
            base_url = (form.get("base_url") or "").strip()
            if not base_url:
                raise HTTPException(status_code=400, detail="Executor URL is required")
            endpoint = self._registry.add(label=label, base_url=base_url)
            return RedirectResponse(
                request.url_for("executor_dashboard", key=endpoint.key),
                status_code=303,
            )

        @router.get("/executors/{key}", response_class=HTMLResponse, name="executor_dashboard")
        async def executor_dashboard(request: Request, key: str) -> HTMLResponse:
            endpoint = self._registry.get(key)
            client = ExecutorClient(endpoint.base_url)
            tasks: list[ExecutorTaskSummary] = []
            env_overrides: dict[str, str] = {}
            health: ExecutorHealth | None = None
            error: str | None = None
            try:
                tasks = await client.list_tasks()
                env_overrides = await client.get_env()
                health = await client.get_health()
            except httpx.HTTPError as exc:
                error = str(exc)
            return templates.TemplateResponse(
                request,
                "executor.html",
                {
                    "endpoint": endpoint,
                    "tasks": tasks,
                    "env_overrides": env_overrides,
                    "health": health,
                    "error": error,
                },
            )

        @router.post("/executors/{key}/tasks")
        async def create_task(request: Request, key: str) -> RedirectResponse:
            endpoint = self._registry.get(key)
            form = await request.form()
            description = (form.get("description") or "").strip()
            if not description:
                raise HTTPException(status_code=400, detail="Task description is required")
            goal = (form.get("goal") or "").strip() or None
            provider = (form.get("llm_provider") or "mock").strip() or "mock"
            model = (form.get("llm_model") or "").strip() or None
            api_key = (form.get("llm_api_key") or "").strip() or None
            enable_vnc = form.get("enable_vnc") == "on"
            headless = form.get("headless") == "on"
            llm_config: dict[str, object] = {"provider": provider}
            if model:
                llm_config["model"] = model
            if api_key:
                llm_config["api_key"] = api_key
            task_config: dict[str, object] = {"description": description}
            if goal:
                task_config["goal"] = goal
            config: dict[str, object] = {
                "task": task_config,
                "llm": llm_config,
                "browser": {"enable_vnc": enable_vnc, "headless": headless},
            }
            client = ExecutorClient(endpoint.base_url)
            try:
                await client.create_task(config=config)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            return RedirectResponse(
                request.url_for("executor_dashboard", key=key),
                status_code=303,
            )

        @router.get(
            "/executors/{key}/tasks/{task_id}",
            response_class=HTMLResponse,
            name="task_detail",
        )
        async def view_task(request: Request, key: str, task_id: str) -> HTMLResponse:
            endpoint = self._registry.get(key)
            client = ExecutorClient(endpoint.base_url)
            task: ExecutorTaskDetail | None = None
            screenshots: list[str] = []
            error: str | None = None
            try:
                task = await client.get_task(task_id)
                screenshots = await client.list_screenshots(task_id)
            except httpx.HTTPError as exc:
                error = str(exc)
            return templates.TemplateResponse(
                request,
                "task_detail.html",
                {
                    "endpoint": endpoint,
                    "task": task,
                    "screenshots": screenshots,
                    "error": error,
                    "task_id": task_id,
                },
            )

        @router.post("/executors/{key}/tasks/{task_id}/pause")
        async def pause_task(request: Request, key: str, task_id: str) -> RedirectResponse:
            endpoint = self._registry.get(key)
            client = ExecutorClient(endpoint.base_url)
            form = await request.form()
            reason = (form.get("reason") or "Manual pause requested from admin").strip()
            instructions = (
                form.get("instructions")
                or "Take control of the browser, resolve the issue, and resume."
            ).strip()
            try:
                await client.pause_task(task_id, reason=reason, instructions=instructions)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            return RedirectResponse(
                request.url_for("task_detail", key=key, task_id=task_id),
                status_code=303,
            )

        @router.post("/executors/{key}/tasks/{task_id}/resume")
        async def resume_task(request: Request, key: str, task_id: str) -> RedirectResponse:
            endpoint = self._registry.get(key)
            client = ExecutorClient(endpoint.base_url)
            try:
                await client.resume_task(task_id)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            return RedirectResponse(
                request.url_for("task_detail", key=key, task_id=task_id),
                status_code=303,
            )

        @router.post("/executors/{key}/settings/env")
        async def update_env(request: Request, key: str) -> RedirectResponse:
            endpoint = self._registry.get(key)
            client = ExecutorClient(endpoint.base_url)
            form = await request.form()
            overrides = _parse_env_text(form.get("env_text") or "")
            try:
                await client.update_env(overrides)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            return RedirectResponse(
                request.url_for("executor_dashboard", key=key),
                status_code=303,
            )

        @router.get("/executors/{key}/tasks/{task_id}/screenshots/{name}")
        async def proxy_screenshot(key: str, task_id: str, name: str) -> Response:
            endpoint = self._registry.get(key)
            client = ExecutorClient(endpoint.base_url)
            try:
                content = await client.fetch_screenshot(task_id, name)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return Response(content=content, media_type="image/png")

        app.include_router(router)
        return app


def _parse_env_text(value: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        overrides[key.strip()] = val.strip()
    return overrides


def build_executor_endpoints(specs: Iterable[str]) -> list[ExecutorEndpoint]:
    registry = ExecutorRegistry()
    for index, raw in enumerate(specs):
        if "=" in raw:
            label, url = raw.split("=", 1)
        else:
            label = f"Executor {index + 1}"
            url = raw
        registry.add(label=label, base_url=url)
    return registry.all()


def _slugify(label: str) -> str:
    cleaned = [ch.lower() if ch.isalnum() else "-" for ch in label]
    slug = "".join(cleaned).strip("-")
    return slug or "executor"


def create_admin_app(executor_specs: Iterable[str]) -> FastAPI:
    endpoints = build_executor_endpoints(executor_specs)
    registry = ExecutorRegistry(endpoints)
    app = AdminApplication(registry).create_app()
    return app

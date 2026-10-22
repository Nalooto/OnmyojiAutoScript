# This Python file uses the following encoding: utf-8
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from module.server.api_logger import ApiLoggingRoute
from module.server.log_stats import log_stats_service

stats_app = APIRouter(
    prefix="/stats",
    tags=["stats"],
    route_class=ApiLoggingRoute,
)


class BattleStatsResponse(BaseModel):
    count: int
    avg_duration_seconds: float


class TaskRunStatsResponse(BaseModel):
    start_time: str
    end_time: str
    duration_seconds: float
    battle: BattleStatsResponse | None = None


class TaskStatsResponse(BaseModel):
    run_count: int
    total_duration_seconds: float
    battle: BattleStatsResponse | None = None
    runs: list[TaskRunStatsResponse] = Field(default_factory=list)


class StatsResponse(BaseModel):
    script_name: str
    total_runtime_seconds: float
    total_task_run_count: int
    total_battle_count: int
    tasks: dict[str, TaskStatsResponse] = Field(default_factory=dict)


class StatsAvailableDatesResponse(BaseModel):
    script_name: str
    dates: list[str] = Field(default_factory=list)


class StatsUpdateResponse(BaseModel):
    script_name: str
    total_runtime_seconds: float
    total_task_run_count: int
    total_battle_count: int
    changed_tasks: dict[str, TaskStatsResponse] = Field(default_factory=dict)
    removed_tasks: list[str] = Field(default_factory=list)


def _parse_target_date(date_text: str) -> date:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid date format, expected YYYY-MM-DD") from exc


@stats_app.get("/{script_name}/dates", response_model=StatsAvailableDatesResponse)
async def stats_available_dates(script_name: str):
    return log_stats_service.list_available_dates(script_name)


class AssetItemResponse(BaseModel):
    key: str
    label: str
    icon: str = ''
    value: int
    prev: int | None = None


class AssetDayResponse(BaseModel):
    date: str
    updated_at: str | None = None
    items: dict[str, int] = Field(default_factory=dict)


class AssetStatsResponse(BaseModel):
    script_name: str
    available: bool
    updated_at: str | None = None
    source: str | None = None
    account: dict = Field(default_factory=dict)
    items: list[AssetItemResponse] = Field(default_factory=list)
    days: list[AssetDayResponse] = Field(default_factory=list)


def _asset_file(script_name: str) -> Path:
    return Path(__file__).resolve().parents[2] / 'config' / 'asset_stats' / f'{script_name}.json'


def _load_asset_response(script_name: str) -> AssetStatsResponse:
    path = _asset_file(script_name)
    if not path.exists():
        return AssetStatsResponse(script_name=script_name, available=False)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Invalid asset stats file: {exc}') from exc
    items = [AssetItemResponse(**item) for item in data.get('items', []) if item.get('key')]
    days = []
    for day_key, day in sorted((data.get('days') or {}).items()):
        days.append(AssetDayResponse(
            date=day_key,
            updated_at=day.get('updated_at'),
            items={str(k): int(v) for k, v in (day.get('items') or {}).items()},
        ))
    return AssetStatsResponse(
        script_name=script_name,
        available=True,
        updated_at=data.get('updated_at'),
        source=data.get('source'),
        account=data.get('account') or {},
        items=items,
        days=days,
    )


@stats_app.get("/{script_name}/assets", response_model=AssetStatsResponse)
async def stats_assets(script_name: str):
    """读取每日琐事写入的角色资产快照。"""
    return _load_asset_response(script_name)


@stats_app.post("/{script_name}/assets/refresh", response_model=AssetStatsResponse)
def refresh_assets(script_name: str):
    """按需触发一次资产读取（独立进程，不依赖每日琐事任务）。"""
    root = Path(__file__).resolve().parents[2]
    lock = root / 'config' / 'asset_stats' / '.refresh.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    if not _acquire_asset_lock(lock):
        raise HTTPException(status_code=409, detail='正在读取资产，请稍后再试')
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'tasks.DailyTrifles.asset_cli', script_name],
            cwd=str(root), capture_output=True, timeout=120,
        )
        if proc.returncode != 0:
            output = (proc.stderr or proc.stdout or b'').decode('utf-8', 'replace')[-800:]
            raise HTTPException(status_code=500, detail=f'资产读取失败: {output}')
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail='资产读取超时（120s）') from exc
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    return _load_asset_response(script_name)


def _acquire_asset_lock(lock: Path, stale_seconds: int = 180) -> bool:
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(time.time()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - lock.stat().st_mtime > stale_seconds:
                lock.unlink()
                return _acquire_asset_lock(lock, stale_seconds)
        except OSError:
            pass
    except OSError:
        pass
    return False


@stats_app.get("/{script_name}", response_model=StatsResponse)
async def stats_snapshot(
    script_name: str,
    date_text: str = Query(..., alias="date", description="YYYY-MM-DD"),
):
    target_day = _parse_target_date(date_text)
    return log_stats_service.build_stats(script_name, target_day)


@stats_app.get("/{script_name}/stream")
async def stats_stream(
    script_name: str,
    date_text: str = Query(..., alias="date", description="YYYY-MM-DD"),
):
    target_day = _parse_target_date(date_text)
    if target_day != date.today():
        raise HTTPException(status_code=400, detail="Only today's date supports SSE stream")

    response = StreamingResponse(
        log_stats_service.stream_events(script_name, target_day),
        media_type="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    return response

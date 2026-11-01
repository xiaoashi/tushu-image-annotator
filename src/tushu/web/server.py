from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import shutil
import threading
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tushu.domain.entities import Box, STATES, uid
from tushu.repositories.project import Project
from tushu.infrastructure.tasks import Cancelled, TaskContext
from tushu.services import importing, editing, processing, quality, splitting, inferencing, vision
from tushu.datasets.exporter import export


class Workbench:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.project = None
        self.history = None
        self.model = None
        self.vision = vision.VisionConfig.local()
        self.client_token = secrets.token_urlsafe(32)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tushu-work")
        self.job = None
        self.cancel = threading.Event()
        self.guard = threading.RLock()

    def ready(self):
        if self.job and self.job["status"] == "running":
            raise HTTPException(409, "后台任务正在运行，请等待或取消")
        if not self.project:
            raise HTTPException(400, "请先创建或打开项目")
        return self.project

    def idle(self):
        if self.job and self.job["status"] == "running":
            raise HTTPException(409, "后台任务正在运行，请等待或取消")

    def attach(self, project):
        if self.project:
            self.project.close()
        self.project = project
        self.history = editing.History(project)

    def task(self, kind, action):
        self.ready()
        self.cancel = threading.Event()
        job = {
            "id": uid(),
            "kind": kind,
            "status": "running",
            "done": 0,
            "total": 0,
            "current": "",
            "result": None,
            "error": None,
        }
        self.job = job

        def progress(done, total, name):
            job.update(done=done, total=total, current=name)

        def execute():
            context = TaskContext(self.project, kind, progress, self.cancel)
            try:
                job["result"] = context.run(action)
                job["status"] = (
                    "partial_failure"
                    if context.failures and context.completed
                    else "failed"
                    if context.failures
                    else "success"
                )
            except Cancelled as error:
                job.update(status="cancelled", error=str(error))
            except Exception as error:
                job.update(status="failed", error=str(error))

        self.executor.submit(execute)
        return job

    def projects(self):
        result = []
        for folder in self.workspace.glob("tushu-project-*"):
            try:
                data = json.loads((folder / "project.json").read_text("utf-8"))
                result.append({"id": folder.name, "name": data["name"], "created_at": data["created_at"]})
            except (OSError, ValueError, KeyError):
                continue
        return sorted(result, key=lambda p: p["created_at"], reverse=True)

    def status(self):
        project = self.project
        assets = project.assets() if project else []
        counts = {key: sum(a["state"] == key for a in assets) for key in STATES}
        plan = None
        if project:
            try:
                plan = splitting.current_plan(project)
            except ValueError:
                pass
        for asset in assets:
            asset.pop("source_path", None)
            asset.pop("path", None)
            asset["split"] = plan["assignments"].get(asset["group_id"]) if plan else None
            asset["box_count"] = len(project.boxes(asset["active_version_id"]))
        return {
            "project": {"id": project.root.name, "name": project.name} if project else None,
            "assets": assets,
            "categories": project.categories() if project else [],
            "counts": counts,
            "plan": plan,
            "job": self.job,
            "vision": self.vision.public(),
            "projects": self.projects(),
            "service": "tushu-web",
            "version": "1.1.0",
            "client_token": self.client_token,
        }


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SelectProject(BaseModel):
    id: str


class BoxesInput(BaseModel):
    revision: int
    boxes: list[dict]


class AssetSelection(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=2000)


class CategoryInput(BaseModel):
    name: str
    export_name: str
    color: str = "#6366f1"


class VisionInput(AssetSelection):
    consent: bool = False


class VisionSettings(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None


class ProcessInput(AssetSelection):
    operations: list[dict]
    augment: bool = False
    seed: int = 42


class SplitInput(BaseModel):
    train_ratio: float = 0.8
    seed: int = 42


class ExportInput(BaseModel):
    format: str = "yolo"
    ids: list[str] | None = None
    acknowledge_warnings: bool = False


class ScanInput(BaseModel):
    folder: str
    recursive: bool = True


class InferInput(AssetSelection):
    threshold: float = 0.3
    nms: float = 0.45


def model_folder():
    import sys

    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    return root / "models/yolox-s-coco"


def create_app(workspace=None):
    wb = Workbench(workspace or os.getenv("TUSHU_WORKSPACE", str(Path.home() / "Pictures/Tushu Projects")))

    @asynccontextmanager
    async def lifespan(app):
        yield
        wb.cancel.set()
        wb.executor.shutdown(wait=True, cancel_futures=True)
        if wb.project:
            wb.project.close()

    app = FastAPI(title="图枢图像标注工作台", version="1.1.0", lifespan=lifespan)
    app.state.workbench = wb

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "拒绝跨站修改请求"}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-tushu-client", ""), wb.client_token):
                return JSONResponse({"detail": "请刷新页面后重试"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/api/bootstrap")
    def bootstrap():
        return wb.status()

    @app.post("/api/projects")
    def new_project(body: NewProject):
        wb.idle()
        project = Project.create(wb.workspace, body.name)
        wb.attach(project)
        return wb.status()

    @app.post("/api/projects/open")
    def open_project(body: SelectProject):
        wb.idle()
        if not body.id.startswith("tushu-project-") or "/" in body.id or "\\" in body.id or ".." in body.id:
            raise ValueError("无效项目 ID")
        path = (wb.workspace / body.id).resolve()
        if path.parent != wb.workspace:
            raise ValueError("无效项目路径")
        if not wb.project or wb.project.root != path:
            wb.attach(Project(path))
        return wb.status()

    @app.get("/api/assets/{identifier}")
    def asset_detail(identifier: str):
        if not wb.project:
            raise HTTPException(400, "请先打开项目")
        asset = wb.project.asset(identifier)
        records = wb.project.rows(
            "SELECT data_json FROM audit WHERE event='vision_assistance' ORDER BY rowid DESC LIMIT 100"
        )
        reports = [json.loads(r["data_json"]) for r in records]
        latest = next((r for r in reports if r["asset_id"] == identifier), None)
        return {
            "asset": {k: v for k, v in asset.items() if k not in ("source_path", "path")},
            "boxes": [b.to_dict() for b in wb.project.boxes(asset["active_version_id"])],
            "vision_result": latest,
            "versions": wb.project.rows(
                "SELECT id,width,height,state,revision FROM image_versions WHERE asset_id=? ORDER BY rowid DESC",
                (identifier,),
            ),
        }

    @app.get("/api/assets/{identifier}/image")
    def image(identifier: str, thumbnail: bool = False):
        if not wb.project:
            raise HTTPException(400, "请先打开项目")
        asset = wb.project.asset(identifier)
        path = wb.project.root / ("thumbnails" if thumbnail else "previews") / f"{asset['sha256']}.png"
        if not path.is_file():
            path = wb.project.path(asset["path"])
        return FileResponse(path, headers={"Cache-Control": "private,max-age=60"})

    @app.put("/api/assets/{identifier}/boxes")
    def boxes(identifier: str, body: BoxesInput):
        project = wb.ready()
        asset = project.asset(identifier)
        if body.revision != asset["revision"]:
            raise HTTPException(409, "修订号已改变，请刷新图片后重试")
        wb.history.execute(asset, [Box(**b) for b in body.boxes], "web-edit")
        return asset_detail(identifier)

    @app.post("/api/assets/{identifier}/undo")
    def undo(identifier: str, redo: bool = False):
        project = wb.ready()
        wb.history.undo(project.asset(identifier), redo)
        return asset_detail(identifier)

    @app.post("/api/assets/{identifier}/review")
    def review(
        identifier: str,
        negative_confirmed: bool = False,
        hidden: bool = False,
        acknowledge_stale: bool = False,
    ):
        project = wb.ready()
        asset = project.asset(identifier)
        if not project.boxes(asset["active_version_id"]) and not negative_confirmed:
            raise ValueError("请明确确认该图片没有待标注目标")
        editing.review(project, identifier, hidden, acknowledge_stale)
        return asset_detail(identifier)

    @app.post("/api/categories")
    def category(body: CategoryInput):
        project = wb.ready()
        editing.add_category(project, body.name, body.export_name, body.color)
        return wb.status()

    @app.post("/api/categories/template")
    def template():
        project = wb.ready()
        existing = {c["export_name"] for c in project.categories()}
        for name, export_name, color in [
            ("动物", "animal", "#8b5cf6"),
            ("植物", "plant", "#16a085"),
            ("物品", "object", "#d88738"),
        ]:
            if export_name not in existing:
                editing.add_category(project, name, export_name, color)
        return wb.status()

    @app.post("/api/import/scan")
    def scan(body: ScanInput):
        wb.ready()
        return wb.task("扫描文件夹", lambda context: importing.scan(body.folder, body.recursive, context))

    @app.post("/api/import/confirm")
    def import_confirm():
        wb.ready()
        if not wb.job or wb.job["kind"] != "扫描文件夹" or wb.job["status"] != "success":
            raise ValueError("请先完成文件夹扫描")
        rows = wb.job["result"]
        return wb.task("导入图片", lambda context: importing.import_files(wb.project, rows, context))

    @app.post("/api/import/upload")
    async def upload(files: list[UploadFile] = File(...)):
        project = wb.ready()
        if len(files) > 2000:
            raise ValueError("单次最多 2000 张")
        staging = project.root / "trash" / f"upload-{uid()}"
        staging.mkdir()
        rows = []
        try:
            for file in files:
                suffix = Path(file.filename or "").suffix.lower()
                if suffix not in importing.SUPPORTED:
                    raise ValueError("仅支持 JPEG、PNG、静态 WebP")
                destination = staging / (uid() + suffix)
                count = 0
                with destination.open("wb") as stream:
                    while chunk := await file.read(1024 * 1024):
                        count += len(chunk)
                        if count > 100 * 1024**2:
                            raise ValueError("单个文件超过 100 MiB")
                        stream.write(chunk)
                await file.close()
                try:
                    row = importing.inspect(destination)
                    row.update(
                        path=str(destination),
                        name=Path(file.filename or destination.name).name,
                        hash=importing.sha256(destination),
                        accepted=True,
                        reason="",
                    )
                except Exception as error:
                    row = {
                        "path": str(destination),
                        "name": file.filename or "",
                        "accepted": False,
                        "reason": str(error),
                    }
                rows.append(row)

            def action(context):
                try:
                    return importing.import_files(project, rows, context)
                finally:
                    shutil.rmtree(staging, ignore_errors=True)

            return wb.task("上传导入", action)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @app.post("/api/vision/config")
    def config(body: VisionSettings):
        wb.ready()
        settings = vision.VisionConfig(
            body.base_url.rstrip("/"), body.model, body.api_key or wb.vision.api_key
        )
        settings.validate()
        wb.vision = settings
        return settings.public()

    @app.post("/api/vision/run")
    def vision_run(body: VisionInput):
        wb.ready()
        return wb.task(
            "大模型视觉辅助",
            lambda context: vision.run(wb.project, body.ids, wb.vision, context, body.consent),
        )

    @app.post("/api/infer")
    def infer(body: InferInput):
        project = wb.ready()

        def action(context):
            from tushu.inference.yolox import YoloX

            if wb.model is None:
                wb.model = YoloX(model_folder())
            categories = project.categories()
            animal = {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
            mapping = {}
            for index, name in enumerate(wb.model.classes):
                target = next((c["id"] for c in categories if c["export_name"] == name), None)
                broad = (
                    "animal"
                    if name in animal
                    else "plant"
                    if name == "potted plant"
                    else "object"
                    if name != "person"
                    else None
                )
                mapping[index] = target or next(
                    (c["id"] for c in categories if c["export_name"] == broad), None
                )
            inferencing.register(project, wb.model, mapping)
            return inferencing.run(project, body.ids, wb.model, mapping, body.threshold, body.nms, context)

        return wb.task("本地检测预标注", action)

    @app.post("/api/process")
    def process(body: ProcessInput):
        wb.ready()
        return wb.task(
            "训练组增强" if body.augment else "批量处理",
            lambda context: processing.apply(
                wb.project, body.ids, body.operations, context, body.augment, body.seed
            ),
        )

    @app.post("/api/quality")
    def quality_check():
        return wb.task("质量检查", lambda context: quality.check(wb.project, context=context))

    @app.post("/api/split")
    def split(body: SplitInput):
        project = wb.ready()
        return splitting.create(project, body.train_ratio, body.seed)

    @app.post("/api/groups/merge")
    def merge(body: AssetSelection):
        project = wb.ready()
        splitting.merge_groups(project, body.ids)
        return wb.status()

    @app.post("/api/export")
    def exporting(body: ExportInput):
        project = wb.ready()
        return wb.task(
            "导出与独立校验",
            lambda context: export(
                project, project.root / "exports", body.format, body.ids, body.acknowledge_warnings, context
            ),
        )

    @app.get("/api/exports")
    def exports():
        project = wb.project
        if not project:
            return []
        return [
            {k: v for k, v in row.items() if k not in ("snapshot_json", "output_path")}
            for row in project.rows("SELECT * FROM exports ORDER BY rowid DESC")
        ]

    @app.get("/api/exports/{identifier}/download")
    def download(identifier: str):
        if not wb.project:
            raise ValueError("请先打开项目")
        row = wb.project.one("SELECT * FROM exports WHERE id=?", (identifier,))
        if row["status"] != "success":
            raise ValueError("导出未通过校验")
        path = Path(row["output_path"]).resolve()
        if not path.is_relative_to(wb.project.root / "exports"):
            raise ValueError("无效导出路径")
        archive = path.with_suffix(".zip")
        if not archive.exists():
            shutil.make_archive(str(path), "zip", path)
        return FileResponse(archive, filename=archive.name, media_type="application/zip")

    @app.get("/api/tasks")
    def tasks():
        return wb.project.rows("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100") if wb.project else []

    @app.post("/api/tasks/cancel")
    def cancel():
        wb.cancel.set()
        return {"requested": True}

    @app.post("/api/assets/exclude")
    def exclude(body: AssetSelection, reason: str = "用户排除", restore: bool = False):
        project = wb.ready()
        editing.set_excluded(project, body.ids, None if restore else reason)
        return wb.status()

    static = Path(__file__).parent / "static"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="web")
    return app

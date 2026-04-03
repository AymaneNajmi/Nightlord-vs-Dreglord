from pathlib import Path
import logging
import os
import subprocess

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.db import engine, Base, SessionLocal
from app.core.config import settings
from jose import JWTError

from app.core.auth import (
    decode_access_token,
    get_token_from_request,
    get_user_from_token,
    require_admin,
    require_authenticated,
    require_user,
)

# ✅ Routers API
from app.api_auth import router as auth_router
from app.api_admin_users import router as admin_users_router
from app.api_technos import router as technos_router
from app.api_docs import router as docs_router
from app.api_forms import router as forms_router
from app.api_hardware import router as hardware_router
from app.api_admin_ai_template_builder import router as ai_template_builder_router
from app.api_llm import router as llm_router
from app.routers.admin.ai_form_builder import router as ai_form_builder_router
from app.services.ai_template_builder import FORM_MODEL, OUTLINE_MODEL

# ✅ OPTIONAL: only if the file exists
from app.api_worksheets import router as worksheets_router

# ✅ Import modèles "oubliés"
from app.models import submission_section_text  # noqa: F401
from app.models import form_module_answer  # noqa: F401
from app.seed import seed_db

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

app = FastAPI(title="AI DocGen API", version="0.1.0")
logger = logging.getLogger(__name__)

# ✅ Crée les tables
Base.metadata.create_all(bind=engine)
def _ensure_columns():
    dialect = engine.dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        return

    def has_column(table: str, column: str) -> bool:
        with engine.connect() as conn:
            if dialect == "sqlite":
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                return any(r[1] == column for r in rows)
            result = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = :column"
                ),
                {"table": table, "column": column},
            ).fetchone()
            return result is not None

    def add_column(table: str, column_def: str) -> None:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_def}"))
            conn.commit()

    techno_columns = {
        "template_doc_id": "template_doc_id INTEGER",
        "form_template_id": "form_template_id INTEGER",
        "cover_template_id": "cover_template_id INTEGER",
    }
    for col, col_def in techno_columns.items():
        if not has_column("technos", col):
            add_column("technos", col_def)

    json_type = "JSON" if dialect == "postgresql" else "TEXT"
    template_doc_columns = {
        "is_generated": "is_generated BOOLEAN DEFAULT FALSE",
        "outline_json": f"outline_json {json_type}",
        "template_text": "template_text TEXT",
    }
    for col, col_def in template_doc_columns.items():
        if not has_column("template_docs", col):
            add_column("template_docs", col_def)

    form_section_columns = {
        "status": "status VARCHAR(20) DEFAULT 'OK'",
        "error_message": "error_message TEXT",
    }
    for col, col_def in form_section_columns.items():
        if not has_column("form_sections", col):
            add_column("form_sections", col_def)

    submission_answer_columns = {
        "other_text": "other_text TEXT",
    }
    for col, col_def in submission_answer_columns.items():
        if not has_column("submission_answers", col):
            add_column("submission_answers", col_def)

    ai_template_job_columns = {
        "llm_provider": "llm_provider VARCHAR(20) DEFAULT 'openai' NOT NULL",
    }
    for col, col_def in ai_template_job_columns.items():
        if not has_column("ai_template_jobs", col):
            add_column("ai_template_jobs", col_def)


_ensure_columns()

# ✅ Static + UI
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
UI_DIR = APP_DIR / "ui"
UI_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _protected_file_response(path: Path) -> FileResponse:
    return FileResponse(
        path,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@app.middleware("http")
async def auth_page_guard(request: Request, call_next):
    path = request.url.path
    protected_admin = path.startswith("/admin")
    protected_user = path.startswith("/user")
    protected_hardware = path == "/hardware"

    if not (protected_admin or protected_user or protected_hardware):
        return await call_next(request)

    token = get_token_from_request(request)
    if not token:
        response = RedirectResponse(url="/login")
        response.delete_cookie(
            settings.AUTH_COOKIE_NAME,
            domain=settings.AUTH_COOKIE_DOMAIN,
            path=settings.AUTH_COOKIE_PATH,
        )
        return response

    db = SessionLocal()
    try:
        session_data = decode_access_token(token)
        user = get_user_from_token(token, db)
    except JWTError:
        response = RedirectResponse(url="/login")
        response.delete_cookie(
            settings.AUTH_COOKIE_NAME,
            domain=settings.AUTH_COOKIE_DOMAIN,
            path=settings.AUTH_COOKIE_PATH,
        )
        return response
    finally:
        db.close()

    if not user or not user.is_active:
        response = RedirectResponse(url="/login")
        response.delete_cookie(
            settings.AUTH_COOKIE_NAME,
            domain=settings.AUTH_COOKIE_DOMAIN,
            path=settings.AUTH_COOKIE_PATH,
        )
        return response

    role = str(user.role).split(".")[-1]
    if not role:
        response = RedirectResponse(url="/login")
        response.delete_cookie(
            settings.AUTH_COOKIE_NAME,
            domain=settings.AUTH_COOKIE_DOMAIN,
            path=settings.AUTH_COOKIE_PATH,
        )
        return response
    if protected_admin and role != "ADMIN":
        return PlainTextResponse("Forbidden", status_code=403)
    if protected_user and role != "USER":
        return PlainTextResponse("Forbidden", status_code=403)
    if protected_hardware and role not in {"ADMIN", "USER"}:
        return PlainTextResponse("Forbidden", status_code=403)

    return await call_next(request)




def _current_commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, cwd=str(BASE_DIR.parent)).strip()
    except Exception:
        return os.getenv("GIT_COMMIT", "unknown")


@app.on_event("startup")
def log_runtime_build_info() -> None:
    # Run DB seeder natively upon startup to ensure roles exist natively across any environment.
    seed_db()
    
    build_id = os.getenv("APP_BUILD_ID", "dev")
    logger.info(
        "startup_build_info commit=%s build_id=%s openai_model_outline=%s openai_model_form=%s",
        _current_commit_hash(),
        build_id,
        OUTLINE_MODEL,
        FORM_MODEL,
    )

# -----------------------
# Health
# -----------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/health/db")
def health_db():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"db": "ok"}


# -----------------------
# Pages UI (HTML)
# -----------------------
@app.get("/")
def root():
    return FileResponse(UI_DIR / "login.html")

@app.get("/login")
def login_page():
    return FileResponse(UI_DIR / "login.html")

# ---- Admin UI
@app.get("/admin")
def admin_page(_: None = Depends(require_admin)):
    logger.info("Serving admin UI template: %s", UI_DIR / "admin.html")
    return _protected_file_response(UI_DIR / "admin.html")

@app.get("/admin/forms")
def admin_forms_list_page(_: None = Depends(require_admin)):
    return _protected_file_response(UI_DIR / "admin_forms_list.html")

@app.get("/admin/form-builder")
def admin_form_builder_page(_: None = Depends(require_admin)):
    return _protected_file_response(UI_DIR / "admin_form_builder.html")

@app.get("/admin/forms/preview")
def admin_form_preview_page(_: None = Depends(require_admin)):
    return _protected_file_response(UI_DIR / "form_preview.html")

@app.get("/admin/users")
def admin_users_page(_: None = Depends(require_admin)):
    return _protected_file_response(UI_DIR / "admin_users.html")

@app.get("/admin/ai-template-builder")
def admin_ai_template_builder_page(_: None = Depends(require_admin)):
    return _protected_file_response(UI_DIR / "admin_ai_template_builder.html")

@app.get("/admin/ai-template-builder/new")
def admin_ai_template_builder_new_page(_: None = Depends(require_admin)):
    return _protected_file_response(UI_DIR / "admin_ai_template_builder_new.html")

@app.get("/admin/ai-template-builder/jobs/{job_id}")
def admin_ai_template_builder_job_page(job_id: int, _: None = Depends(require_admin)):
    return _protected_file_response(UI_DIR / "admin_ai_template_builder_job.html")

@app.get("/admin/technos/{techno_id}")
def admin_techno_detail_page(techno_id: int, _: None = Depends(require_admin)):
    return _protected_file_response(UI_DIR / "admin_techno_detail.html")

# ---- User UI
@app.get("/user")
def user_page(_: None = Depends(require_user)):
    return _protected_file_response(UI_DIR / "user_dashboard.html")

# ✅ Step 2
@app.get("/user/sections")
def user_sections_page(_: None = Depends(require_user)):
    return _protected_file_response(UI_DIR / "user_sections.html")

# ✅ Step 3 (without id)  <--- IMPORTANT
@app.get("/user/form")
def user_form_page_no_id(_: None = Depends(require_user)):
    return _protected_file_response(UI_DIR / "user_form.html")

# Step 3 (with id)
@app.get("/user/form/{form_id}")
def user_form_page(form_id: int, _: None = Depends(require_user)):
    return _protected_file_response(UI_DIR / "user_form.html")


# -----------------------
# Include API routers
# -----------------------
app.include_router(auth_router)
app.include_router(admin_users_router)
app.include_router(ai_template_builder_router)
app.include_router(llm_router)
app.include_router(ai_form_builder_router)
app.include_router(technos_router, dependencies=[Depends(require_authenticated)])
app.include_router(docs_router, dependencies=[Depends(require_authenticated)])
app.include_router(forms_router, dependencies=[Depends(require_authenticated)])
app.include_router(worksheets_router, dependencies=[Depends(require_authenticated)])
app.include_router(hardware_router)

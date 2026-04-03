from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

def _read(file: str) -> HTMLResponse:
    p = STATIC_DIR / file
    if not p.exists():
        return HTMLResponse(f"<h3>404 - File not found: {file}</h3>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"))

# ---- Pages ----
@router.get("/", response_class=HTMLResponse)
def root():
    return _read("login.html")

@router.get("/login", response_class=HTMLResponse)
def login():
    return _read("login.html")

@router.get("/admin", response_class=HTMLResponse)
def admin():
    return _read("admin.html")

@router.get("/user", response_class=HTMLResponse)
def user_dashboard():
    return _read("user_dashboard.html")

@router.get("/user/sections", response_class=HTMLResponse)
def user_sections():
    return _read("user_sections.html")

@router.get("/user/form", response_class=HTMLResponse)
def user_form():
    return _read("user_form.html")

# ✅ THIS is what you are missing
@router.get("/user/form/{form_id}", response_class=HTMLResponse)
def user_form_with_id(form_id: int):
    return _read("user_form.html")

@router.get("/admin/form-builder", response_class=HTMLResponse)
def admin_form_builder():
    return _read("admin_form_builder.html")

@router.get("/admin/forms", response_class=HTMLResponse)
def admin_forms_page():
    return _read("admin_forms_list.html")

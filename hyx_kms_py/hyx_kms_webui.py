"""密钥管理服务平台 web UI: routes, guards and rendering only."""
import datetime
import logging
import os
import secrets
import sqlite3
import struct
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

from flask import Flask, g, render_template, request, abort

from hyx_kms_catalog import WINDOWS_SOURCE_URL, get_activation_products
from hyx_kms_health import probe_kms
from hyx_kms_i18n import register_i18n, translate

app = Flask(__name__)
register_i18n(app)

loggersrv = logging.getLogger('logsrv')

_serve_count = 0
_serve_lock = threading.Lock()
_start_time = datetime.datetime.now()
_ready_lock = threading.Lock()
_ready_cache = (0.0, False)
_ready_cache_seconds = 5.0


@app.before_request
def protect_records():
    g.csp_nonce = secrets.token_urlsafe(16)
    g.request_id = secrets.token_hex(8)
    if not request.is_secure:
        return translate('仅允许 HTTPS 访问'), 400
    return None


@app.after_request
def security_headers(response):
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(), geolocation=(), microphone=(), payment=(), usb=()'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'nonce-%s'; "
        "style-src 'self'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "upgrade-insecure-requests"
    ) % g.csp_nonce
    if request.path.startswith('/static/') and response.status_code == 200:
        response.headers['Cache-Control'] = 'public, max-age=86400'
    else:
        response.headers['Cache-Control'] = 'no-store'
    return response


def _increase_serve_count():
    global _serve_count
    with _serve_lock:
        _serve_count += 1


def _get_serve_count():
    with _serve_lock:
        return _serve_count


def _random_uuid():
    return str(uuid.uuid4()).replace("-", "_")


def _get_version_info():
    path = os.environ.get("PYKMS_VERSION_PATH", str(Path(__file__).resolve().parent.parent / "VERSION"))
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle.readlines()[:2]]
    if len(lines) < 2:
        return None
    return {"hash": lines[0], "reference": lines[1]}


def _open_readonly(db_path, timeout=None):
    return sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=timeout or 5)


def _get_clients(db_path, page=1):
    if not db_path or not os.path.isfile(db_path):
        raise FileNotFoundError('客户端数据库不存在，请先启动启用 SQLite 的 KMS 服务。')
    with closing(_open_readonly(db_path)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM clients ORDER BY lastRequestTime DESC, rowid DESC LIMIT 50 OFFSET ?", ((page - 1) * 50,))
        rows = cur.fetchall()
    clients = []
    for row in rows:
        item = dict(row)
        if item.get("lastRequestTime") is not None:
            try:
                item["lastRequestTime"] = datetime.datetime.fromtimestamp(
                    item["lastRequestTime"], datetime.timezone.utc
                ).isoformat()
            except (OverflowError, OSError, ValueError):
                pass
        clients.append(item)
    return clients


app.jinja_env.globals.update(
    start_time=_start_time,
    get_serve_count=_get_serve_count,
    random_uuid=_random_uuid,
    version_info=_get_version_info(),
    windows_catalog_source=WINDOWS_SOURCE_URL,
)


@app.route("/")
def root():
    _increase_serve_count()
    error = None
    error_id = None
    db_path = os.environ.get("PYKMS_SQLITE_DB_PATH")
    if not db_path:
        error_id = g.request_id
        error = translate('服务暂不可用，请稍后重试。')
        loggersrv.error('Client database path is not configured', extra={'error_id': error_id})
    clients = []
    totals = (0, 0, 0)
    page = 1
    try:
        raw_page = request.args.get('page', '1')
        if len(raw_page) > 6:
            abort(400)
        page = int(raw_page)
        if not 1 <= page <= 10000:
            abort(400)
    except ValueError:
        abort(400)
    if db_path:
        try:
            clients = _get_clients(db_path, page)
            with closing(_open_readonly(db_path)) as con:
                totals = con.execute("SELECT count(*),coalesce(sum(applicationId='Windows'),0),coalesce(sum(applicationId LIKE 'Office%'),0) FROM clients").fetchone()
        except Exception:
            error_id = g.request_id
            error = translate('服务暂不可用，请稍后重试。')
            loggersrv.exception('Failed to load client records', extra={'error_id': error_id})
    products = get_activation_products()
    return render_template(
        "clients.html",
        path="/",
        error=error,
        error_id=error_id,
        clients=clients,
        page=page, has_next=page * 50 < totals[0],
        count_clients=totals[0],
        count_clients_windows=totals[1],
        count_clients_office=totals[2],
        count_projects=sum(len(group["items"]) for groups in products.values() for group in groups),
    ), 200 if error is None else 500


def _evaluate_readiness():
    global _ready_cache
    now = time.monotonic()
    with _ready_lock:
        expires_at, cached = _ready_cache
        if now < expires_at:
            return cached
        ready = False
        try:
            with closing(_open_readonly(os.environ['PYKMS_SQLITE_DB_PATH'], timeout=1)) as con:
                con.execute('SELECT clientMachineId FROM clients LIMIT 1').fetchall()
            probe_kms(os.environ.get('KMS_HEALTH_HOST', '127.0.0.1'), int(os.environ.get('PORT', '1688')))
            ready = True
        except (OSError, EOFError, sqlite3.Error, KeyError, ValueError, struct.error) as exc:
            loggersrv.warning('Readiness check failed: %s', exc)
        _ready_cache = (now + _ready_cache_seconds, ready)
        return ready


def _reset_ready_cache():
    global _ready_cache
    with _ready_lock:
        _ready_cache = (0.0, False)


@app.route("/readyz")
def readyz():
    if not _evaluate_readiness():
        return 'Not ready', 503
    return 'OK', 200


@app.route("/livez")
def livez():
    return 'OK', 200


@app.route("/license")
def license():
    _increase_serve_count()
    path = os.environ.get("PYKMS_LICENSE_PATH", "../LICENSE")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            license_text = handle.read()
    else:
        license_text = '项目及第三方许可材料：\n'
    directory = Path(__file__).with_name('licenses')
    for item in sorted(directory.iterdir()):
        if item.is_file() and item.suffix in ('.txt', '.md'):
            license_text += '\n\n--- ' + item.name + ' ---\n' + item.read_text(encoding='utf-8')
    return render_template("license.html", path="/license/", license=license_text)


@app.route("/products")
def products():
    _increase_serve_count()
    items = get_activation_products()
    return render_template(
        "products.html",
        path="/products/",
        products=items,
        count_products=sum(len(group["items"]) for groups in items.values() for group in groups),
        count_products_windows=sum(len(group["items"]) for group in items["Windows"]),
        count_products_server=sum(len(group["items"]) for group in items["Windows Server"]),
        count_products_office=sum(len(group["items"]) for group in items["Office"]),
    )


@app.route("/activate")
@app.route("/activate/windows")
def activate():
    _increase_serve_count()
    return render_template(
        "activate.html",
        path="/activate/",
        products=get_activation_products(),
        default_server=os.environ.get('KMS_PUBLIC_HOST', ''),
        default_port=os.environ.get('KMS_PUBLIC_PORT', os.environ.get('PORT', '1688')),
    )


@app.route("/usage")
def usage():
    _increase_serve_count()
    return render_template("usage.html", path="/usage/")

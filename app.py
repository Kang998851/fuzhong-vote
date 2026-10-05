#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
附中墙 · 太原师范学院附属中学校园社区站
Flask + SQLite 单文件应用，无构建步骤，python app.py 即可运行。
"""
import os
import base64
import json
import re
import sqlite3
import secrets
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
from functools import wraps

from flask import (Flask, g, request, session, redirect, url_for,
                   render_template, flash, abort, send_file, Response)
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False

TZ = ZoneInfo("Asia/Shanghai")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_deadline():
    raw = os.environ.get("VOTE_DEADLINE", "2026-10-07 23:59")
    return datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-insecure-change-me"),
    DATABASE=os.environ.get("DATABASE", os.path.join(BASE_DIR, "data", "app.db")),
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,  # 上传上限 4MB
)

ALLOWED_EXTS = {"jpg", "jpeg", "png", "webp"}
BOARDS = [("xiaohua", "校花"), ("xiaocao", "校草"), ("mascot", "吉祥物")]
BOARD_NAMES = dict(BOARDS)
CATEGORIES = ["学习", "生活", "活动", "树洞"]
FEEDBACK_TYPES = [("suggest", "功能建议"), ("bug", "问题反馈"),
                  ("report", "内容举报"), ("other", "其他")]
FEEDBACK_TYPE_NAMES = dict(FEEDBACK_TYPES)

# 数据库切换：默认 SQLite（本地/自有服务器）；设置 DATABASE_URL 环境变量则用 Postgres（Render）
USE_PG = bool(os.environ.get("DATABASE_URL"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS announcements(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forum_posts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forum_replies(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_likes(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
    PRIMARY KEY(user_id, post_id)
);
CREATE TABLE IF NOT EXISTS confessions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nickname TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS confession_likes(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    confession_id INTEGER NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
    PRIMARY KEY(user_id, confession_id)
);
CREATE TABLE IF NOT EXISTS candidates(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    board TEXT NOT NULL,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL,
    slogan TEXT NOT NULL,
    photo TEXT NOT NULL,
    photo_data BYTEA,
    photo_mime TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS votes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    board TEXT NOT NULL,
    day TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, board, day)
);
CREATE TABLE IF NOT EXISTS feedbacks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    body TEXT NOT NULL,
    contact TEXT NOT NULL DEFAULT '',
    status INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


# ---------- 基础工具 ----------
def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def build_schema():
    pk = "SERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", pk)


# 有 id 自增列的表（关联表 post_likes / confession_likes 没有 id，
# 对它们 INSERT 时不能追加 RETURNING id）
TABLES_WITH_ID = frozenset(["users", "announcements", "forum_posts",
                            "forum_replies", "confessions", "candidates",
                            "votes", "feedbacks"])


class Cursor:
    """统一 sqlite3 / psycopg2 的 cursor：SQL 里占位符一律写 ?，INSERT 后可用 .lastrowid。"""

    def __init__(self, raw_conn, is_pg):
        self._is_pg = is_pg
        if is_pg:
            import psycopg2.extras
            self._cur = raw_conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            self._cur = raw_conn.cursor()
        self._lastrowid = None

    def execute(self, sql, params=()):
        q = sql.replace("?", "%s") if self._is_pg else sql
        returning = False
        if self._is_pg and q.lstrip()[:6].upper() == "INSERT" \
                and "returning" not in q.lower():
            m = re.match(r"\s*INSERT\s+INTO\s+\"?(\w+)\"?", q, re.I)
            if m and m.group(1).lower() in TABLES_WITH_ID:
                q += " RETURNING id"
                returning = True
        self._cur.execute(q, params)
        if returning:
            row = self._cur.fetchone()
            self._lastrowid = row["id"] if row else None
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur.fetchall())

    @property
    def lastrowid(self):
        if self._is_pg:
            return self._lastrowid
        return self._cur.lastrowid


class DB:
    def __init__(self, is_pg):
        self.is_pg = is_pg
        if is_pg:
            import psycopg2
            self.raw = psycopg2.connect(os.environ["DATABASE_URL"])
        else:
            os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
            self.raw = sqlite3.connect(app.config["DATABASE"])
            self.raw.row_factory = sqlite3.Row
            self.raw.execute("PRAGMA journal_mode=WAL;")
            self.raw.execute("PRAGMA foreign_keys=ON;")

    def execute(self, sql, params=()):
        return Cursor(self.raw, self.is_pg).execute(sql, params)

    def executescript(self, script):
        if self.is_pg:
            cur = self.raw.cursor()
            for stmt in [s.strip() for s in script.split(";") if s.strip()]:
                cur.execute(stmt)
        else:
            self.raw.executescript(script)

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


def get_db():
    if "db" not in g:
        g.db = DB(USE_PG)
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(build_schema())
    # 存量库补列：照片改存数据库后，老表没有 photo_data / photo_mime
    for col, ddl in (("photo_data", "BYTEA"), ("photo_mime", "TEXT")):
        if USE_PG:
            exists = db.execute(
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_name=? AND column_name=?",
                ("candidates", col)).fetchone()
        else:
            exists = any(r["name"] == col
                         for r in db.execute("PRAGMA table_info(candidates)").fetchall())
        if not exists:
            db.execute(f"ALTER TABLE candidates ADD COLUMN {col} {ddl}")
    row = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not row:
        db.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES(?,?,1,?)",
            ("admin", generate_password_hash("admin12345"), now_str()))
    db.commit()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not current_user():
            flash("请先登录后再操作", "warn")
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        me = current_user()
        if not me or not me["is_admin"]:
            abort(403)
        return view(*a, **kw)
    return wrapper


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def check_csrf():
    if request.method == "POST":
        tok = request.form.get("csrf_token", "")
        if not tok or tok != session.get("_csrf"):
            abort(400, description="CSRF 校验失败，请刷新重试")


@app.context_processor
def inject_common():
    me = current_user()
    dl = get_deadline()
    now = datetime.now(TZ)
    delta = dl - now
    if delta.total_seconds() <= 0:
        days, hours, closed = 0, 0, True
    else:
        days, hours, closed = delta.days, delta.seconds // 3600, False
    return dict(
        me=me,
        boards=BOARDS,
        board_names=BOARD_NAMES,
        vote_closed=closed,
        cd_days=days,
        cd_hours=hours,
        deadline_str=dl.strftime("%Y-%m-%d %H:%M"),
        deadline_iso=dl.isoformat(),
        now_str=now_str,
    )


# ---------- 校徽图片（base64 内嵌：推送工具链无法正确处理二进制文件，故由服务端解码输出） ----------
try:
    from logo_mark import LOGO_MARK_B64
    from logo_full import LOGO_FULL_B64
except ImportError:  # pragma: no cover
    LOGO_MARK_B64 = LOGO_FULL_B64 = ""


@app.route("/img/logo-mark.png")
def logo_mark_img():
    return send_file(BytesIO(base64.b64decode(LOGO_MARK_B64)), mimetype="image/png")


@app.route("/img/logo-full.png")
def logo_full_img():
    return send_file(BytesIO(base64.b64decode(LOGO_FULL_B64)), mimetype="image/png")


# ---------- 账号 ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not (2 <= len(username) <= 20):
            flash("用户名长度需为 2-20 个字符", "error")
        elif len(password) < 4:
            flash("密码至少 4 位", "error")
        else:
            db = get_db()
            if db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                flash("用户名已存在", "error")
            else:
                cur = db.execute(
                    "INSERT INTO users(username, password_hash, created_at) VALUES(?,?,?)",
                    (username, generate_password_hash(password), now_str()))
                db.commit()
                session["user_id"] = cur.lastrowid
                flash(f"欢迎，{username}！", "ok")
                return redirect(request.args.get("next") or url_for("index"))
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if u and check_password_hash(u["password_hash"], password):
            session["user_id"] = u["id"]
            flash(f"欢迎回来，{username}！", "ok")
            return redirect(request.args.get("next") or url_for("index"))
        flash("用户名或密码错误", "error")
    return render_template("auth.html", mode="login")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("已退出登录", "ok")
    return redirect(url_for("index"))


# ---------- 首页 ----------
@app.route("/")
def index():
    db = get_db()
    announcements = db.execute(
        "SELECT * FROM announcements ORDER BY id DESC LIMIT 5").fetchall()
    posts = db.execute(
        """SELECT p.*, u.username,
                  (SELECT COUNT(*) FROM forum_replies r WHERE r.post_id=p.id) AS replies,
                  (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS likes
           FROM forum_posts p JOIN users u ON u.id=p.user_id
           ORDER BY p.id DESC LIMIT 3""").fetchall()
    confesses = db.execute(
        """SELECT c.*, (SELECT COUNT(*) FROM confession_likes l WHERE l.confession_id=c.id) AS likes
           FROM confessions c ORDER BY c.id DESC LIMIT 3""").fetchall()
    tops = {}
    for code, _name in BOARDS:
        tops[code] = db.execute(
            """SELECT c.id, c.name, c.class_name,
               (SELECT COUNT(*) FROM votes v WHERE v.candidate_id=c.id) AS votes
               FROM candidates c WHERE c.board=?
               ORDER BY votes DESC, c.id LIMIT 3""", (code,)).fetchall()
    return render_template("index.html", announcements=announcements,
                           posts=posts, confesses=confesses, tops=tops)


# ---------- 论坛 ----------
@app.route("/forum")
def forum():
    cat = request.args.get("cat", "全部")
    db = get_db()
    q = """SELECT p.*, u.username,
                  (SELECT COUNT(*) FROM forum_replies r WHERE r.post_id=p.id) AS replies,
                  (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS likes
           FROM forum_posts p JOIN users u ON u.id=p.user_id"""
    args = []
    if cat in CATEGORIES:
        q += " WHERE p.category=?"
        args.append(cat)
    q += " ORDER BY p.id DESC"
    posts = db.execute(q, args).fetchall()
    return render_template("forum_list.html", posts=posts, cat=cat,
                           categories=CATEGORIES)


@app.route("/forum/new", methods=["GET", "POST"])
@login_required
def forum_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "")
        body = request.form.get("body", "").strip()
        if not (2 <= len(title) <= 60):
            flash("标题长度需为 2-60 个字符", "error")
        elif category not in CATEGORIES:
            flash("请选择正确的分类", "error")
        elif len(body) < 5:
            flash("正文至少 5 个字符", "error")
        else:
            db = get_db()
            cur = db.execute(
                "INSERT INTO forum_posts(user_id, category, title, body, created_at)"
                " VALUES(?,?,?,?,?)",
                (current_user()["id"], category, title, body, now_str()))
            db.commit()
            flash("发帖成功", "ok")
            return redirect(url_for("forum_detail", pid=cur.lastrowid))
    return render_template("forum_new.html", categories=CATEGORIES)


@app.route("/forum/<int:pid>")
def forum_detail(pid):
    db = get_db()
    post = db.execute(
        """SELECT p.*, u.username,
                  (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS likes
           FROM forum_posts p JOIN users u ON u.id=p.user_id WHERE p.id=?""",
        (pid,)).fetchone()
    if not post:
        abort(404)
    replies = db.execute(
        """SELECT r.*, u.username FROM forum_replies r
           JOIN users u ON u.id=r.user_id WHERE r.post_id=? ORDER BY r.id""",
        (pid,)).fetchall()
    liked = False
    me = current_user()
    if me:
        liked = bool(db.execute(
            "SELECT 1 FROM post_likes WHERE user_id=? AND post_id=?",
            (me["id"], pid)).fetchone())
    return render_template("forum_detail.html", post=post, replies=replies,
                           liked=liked)


@app.route("/forum/<int:pid>/reply", methods=["POST"])
@login_required
def forum_reply(pid):
    db = get_db()
    if not db.execute("SELECT id FROM forum_posts WHERE id=?", (pid,)).fetchone():
        abort(404)
    body = request.form.get("body", "").strip()
    if len(body) < 2:
        flash("回复内容太短", "error")
    else:
        db.execute(
            "INSERT INTO forum_replies(post_id, user_id, body, created_at)"
            " VALUES(?,?,?,?)",
            (pid, current_user()["id"], body, now_str()))
        db.commit()
        flash("回复成功", "ok")
    return redirect(url_for("forum_detail", pid=pid))


@app.route("/forum/<int:pid>/like", methods=["POST"])
@login_required
def forum_like(pid):
    db = get_db()
    me = current_user()
    if db.execute("SELECT 1 FROM post_likes WHERE user_id=? AND post_id=?",
                  (me["id"], pid)).fetchone():
        db.execute("DELETE FROM post_likes WHERE user_id=? AND post_id=?",
                   (me["id"], pid))
    else:
        db.execute("INSERT INTO post_likes(user_id, post_id) VALUES(?,?)",
                   (me["id"], pid))
    db.commit()
    return redirect(url_for("forum_detail", pid=pid))


# ---------- 表白墙 ----------
@app.route("/confess")
def confess():
    sort = request.args.get("sort", "new")
    db = get_db()
    order = ("likes DESC, c.id DESC") if sort == "hot" else "c.id DESC"
    confesses = db.execute(
        f"""SELECT c.*, (SELECT COUNT(*) FROM confession_likes l
                        WHERE l.confession_id=c.id) AS likes
            FROM confessions c ORDER BY {order}""").fetchall()
    liked_ids = set()
    me = current_user()
    if me:
        liked_ids = {r["confession_id"] for r in db.execute(
            "SELECT confession_id FROM confession_likes WHERE user_id=?",
            (me["id"],))}
    return render_template("confess.html", confesses=confesses, sort=sort,
                           liked_ids=liked_ids)


@app.route("/confess/new", methods=["POST"])
@login_required
def confess_new():
    nickname = request.form.get("nickname", "").strip()[:20]
    body = request.form.get("body", "").strip()
    if len(body) < 2 or len(body) > 500:
        flash("表白内容需为 2-500 个字符", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO confessions(user_id, nickname, body, created_at)"
            " VALUES(?,?,?,?)",
            (current_user()["id"], nickname, body, now_str()))
        db.commit()
        flash("表白发布成功", "ok")
    return redirect(url_for("confess"))


@app.route("/confess/<int:cid>/like", methods=["POST"])
@login_required
def confess_like(cid):
    db = get_db()
    me = current_user()
    if db.execute("SELECT 1 FROM confession_likes WHERE user_id=? AND confession_id=?",
                  (me["id"], cid)).fetchone():
        db.execute("DELETE FROM confession_likes WHERE user_id=? AND confession_id=?",
                   (me["id"], cid))
    else:
        db.execute("INSERT INTO confession_likes(user_id, confession_id) VALUES(?,?)",
                   (me["id"], cid))
    db.commit()
    return redirect(url_for("confess", sort=request.args.get("sort", "new")))


# ---------- 搜索 ----------
@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    posts, confesses, candidates = [], [], []
    if q:
        like = f"%{q}%"
        db = get_db()
        posts = db.execute(
            """SELECT p.*, u.username FROM forum_posts p
               JOIN users u ON u.id=p.user_id
               WHERE p.title LIKE ? OR p.body LIKE ? ORDER BY p.id DESC LIMIT 20""",
            (like, like)).fetchall()
        confesses = db.execute(
            "SELECT * FROM confessions WHERE body LIKE ? OR nickname LIKE ?"
            " ORDER BY id DESC LIMIT 20", (like, like)).fetchall()
        candidates = db.execute(
            """SELECT c.id, c.board, c.name, c.class_name, c.slogan,
               (SELECT COUNT(*) FROM votes v WHERE v.candidate_id=c.id) AS votes
               FROM candidates c
               WHERE c.name LIKE ? OR c.class_name LIKE ? OR c.slogan LIKE ?
               ORDER BY votes DESC, c.id LIMIT 20""",
            (like, like, like)).fetchall()
    return render_template("search.html", q=q, posts=posts,
                           confesses=confesses, candidates=candidates)


# ---------- 评选 ----------
def board_candidates(board):
    return get_db().execute(
        """SELECT c.id, c.user_id, c.board, c.name, c.class_name, c.slogan, c.created_at,
           (c.photo_data IS NOT NULL) AS has_photo,
           (SELECT COUNT(*) FROM votes v WHERE v.candidate_id=c.id) AS votes
           FROM candidates c WHERE c.board=?
           ORDER BY votes DESC, c.id""", (board,)).fetchall()


@app.route("/vote")
def vote():
    board = request.args.get("board", "xiaohua")
    if board not in BOARD_NAMES:
        board = "xiaohua"
    db = get_db()
    candidates = board_candidates(board)
    my_vote = None
    me = current_user()
    if me:
        r = db.execute(
            "SELECT candidate_id FROM votes WHERE user_id=? AND board=? AND day=?",
            (me["id"], board, today_str())).fetchone()
        my_vote = r["candidate_id"] if r else None
    return render_template("vote.html", board=board, candidates=candidates,
                           my_vote=my_vote)


@app.route("/vote/cast", methods=["POST"])
@login_required
def vote_cast():
    if vote_closed_flag():
        flash("投票已截止", "error")
        return redirect(url_for("vote"))
    cid = request.form.get("candidate_id", type=int)
    db = get_db()
    cand = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not cand:
        flash("候选人不存在", "error")
        return redirect(url_for("vote"))
    me = current_user()
    day = today_str()
    old = db.execute(
        "SELECT candidate_id FROM votes WHERE user_id=? AND board=? AND day=?",
        (me["id"], cand["board"], day)).fetchone()
    db.execute("DELETE FROM votes WHERE user_id=? AND board=? AND day=?",
               (me["id"], cand["board"], day))
    db.execute(
        "INSERT INTO votes(user_id, candidate_id, board, day, created_at)"
        " VALUES(?,?,?,?,?)",
        (me["id"], cid, cand["board"], day, now_str()))
    db.commit()
    if old and old["candidate_id"] != cid:
        flash("改投成功！", "ok")
    else:
        flash("投票成功！", "ok")
    return redirect(url_for("vote", board=cand["board"]))


def vote_closed_flag():
    return datetime.now(TZ) > get_deadline()


PHOTO_MIMES = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
               "png": "image/png", "webp": "image/webp"}


def save_photo(file_storage):
    """校验上传照片，返回 (图片字节, mime, 错误信息)；失败时前两项为 None。"""
    if not file_storage or not file_storage.filename:
        return None, None, "请上传照片"
    filename = file_storage.filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTS:
        return None, None, "仅支持 JPG / PNG / WebP 格式"
    data = file_storage.read()
    if len(data) > app.config["MAX_CONTENT_LENGTH"]:
        return None, None, "照片不能超过 4MB"
    if HAS_PIL:
        try:
            Image.open(BytesIO(data)).verify()
        except Exception:
            return None, None, "照片文件损坏或格式不正确"
    return data, PHOTO_MIMES[ext], None


@app.route("/vote/signup", methods=["GET", "POST"])
@login_required
def vote_signup():
    if request.method == "POST":
        board = request.form.get("board", "")
        name = request.form.get("name", "").strip()
        class_name = request.form.get("class_name", "").strip()
        slogan = request.form.get("slogan", "").strip()
        if board not in BOARD_NAMES:
            flash("请选择正确的榜单", "error")
        elif not (2 <= len(name) <= 20):
            flash("姓名长度需为 2-20 个字符", "error")
        elif not (1 <= len(class_name) <= 30):
            flash("请填写班级", "error")
        elif not (2 <= len(slogan) <= 100):
            flash("参选宣言需为 2-100 个字符", "error")
        else:
            photo_data, photo_mime, err = save_photo(request.files.get("photo"))
            if err:
                flash(err, "error")
            else:
                db = get_db()
                db.execute(
                    "INSERT INTO candidates(user_id, board, name, class_name,"
                    " slogan, photo, photo_data, photo_mime, created_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (current_user()["id"], board, name, class_name,
                     slogan, "", photo_data, photo_mime, now_str()))
                db.commit()
                flash("报名成功，已进入榜单！", "ok")
                return redirect(url_for("vote", board=board))
    return render_template("vote_signup.html")


@app.route("/candidate-photo/<int:cid>")
def candidate_photo(cid):
    row = get_db().execute(
        "SELECT photo_data, photo_mime FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row or not row["photo_data"]:
        abort(404)
    data = row["photo_data"]
    if isinstance(data, memoryview):
        data = data.tobytes()
    return send_file(BytesIO(data), mimetype=row["photo_mime"] or "image/jpeg",
                     max_age=86400)


# ---------- 意见反馈 ----------
@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    me = current_user()
    db = get_db()
    if request.method == "POST":
        ftype = request.form.get("type", "")
        body = request.form.get("body", "").strip()
        contact = request.form.get("contact", "").strip()
        if ftype not in FEEDBACK_TYPE_NAMES:
            flash("请选择反馈类型", "error")
        elif not (2 <= len(body) <= 1000):
            flash("反馈内容需为 2-1000 个字符", "error")
        elif len(contact) > 100:
            flash("联系方式过长", "error")
        else:
            db.execute(
                "INSERT INTO feedbacks(user_id, type, body, contact, created_at)"
                " VALUES(?,?,?,?,?)",
                (me["id"], ftype, body, contact, now_str()))
            db.commit()
            flash("反馈已提交，感谢你的建议！", "ok")
            return redirect(url_for("feedback"))
    mine = db.execute(
        "SELECT * FROM feedbacks WHERE user_id=? ORDER BY id DESC",
        (me["id"],)).fetchall()
    return render_template("feedback.html", types=FEEDBACK_TYPES,
                           type_names=FEEDBACK_TYPE_NAMES, mine=mine)


# ---------- 管理员 ----------
@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    stats = {
        "users": db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "posts": db.execute("SELECT COUNT(*) c FROM forum_posts").fetchone()["c"],
        "replies": db.execute("SELECT COUNT(*) c FROM forum_replies").fetchone()["c"],
        "confesses": db.execute("SELECT COUNT(*) c FROM confessions").fetchone()["c"],
        "candidates": db.execute("SELECT COUNT(*) c FROM candidates").fetchone()["c"],
        "votes": db.execute("SELECT COUNT(*) c FROM votes").fetchone()["c"],
        "announcements": db.execute("SELECT COUNT(*) c FROM announcements").fetchone()["c"],
    }
    tops = {code: db.execute(
        """SELECT c.id, c.name, c.class_name,
           (SELECT COUNT(*) FROM votes v WHERE v.candidate_id=c.id) AS votes
           FROM candidates c WHERE c.board=?
           ORDER BY votes DESC, c.id LIMIT 5""",
        (code,)).fetchall() for code, _ in BOARDS}
    announcements = db.execute(
        "SELECT * FROM announcements ORDER BY id DESC").fetchall()
    users = db.execute(
        "SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
    feedbacks = db.execute(
        """SELECT f.*, u.username FROM feedbacks f
           JOIN users u ON u.id=f.user_id
           ORDER BY f.status, f.id DESC""").fetchall()
    stats["feedbacks"] = db.execute("SELECT COUNT(*) c FROM feedbacks").fetchone()["c"]
    stats["feedbacks_open"] = db.execute(
        "SELECT COUNT(*) c FROM feedbacks WHERE status=0").fetchone()["c"]
    return render_template("admin.html", stats=stats, tops=tops,
                           announcements=announcements, users=users,
                           feedbacks=feedbacks, type_names=FEEDBACK_TYPE_NAMES)


@app.route("/admin/user/<int:uid>/reset-password", methods=["POST"])
@admin_required
def admin_reset_password(uid):
    db = get_db()
    row = db.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        abort(404)
    temp = secrets.token_urlsafe(6)
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (generate_password_hash(temp), uid))
    db.commit()
    flash(f"用户 {row['username']} 的密码已重置为：{temp}（请复制后立即告知对方，对方可用此密码登录）", "ok")
    return redirect(url_for("admin"))


@app.route("/admin/feedback/<int:fid>/handle", methods=["POST"])
@admin_required
def admin_feedback_handle(fid):
    db = get_db()
    db.execute("UPDATE feedbacks SET status=1 WHERE id=?", (fid,))
    db.commit()
    flash("已标记为已处理", "ok")
    return redirect(url_for("admin"))


BACKUP_TABLES = ["users", "announcements", "forum_posts", "forum_replies",
                 "post_likes", "confessions", "confession_likes",
                 "candidates", "votes", "feedbacks"]


@app.route("/admin/backup")
def admin_backup():
    """下载全站数据备份（JSON）。管理员会话可直接下载；
    设置 BACKUP_TOKEN 环境变量后，自动备份任务可用 ?token=xxx 下载。"""
    token = request.args.get("token", "")
    backup_token = os.environ.get("BACKUP_TOKEN", "")
    authed = bool(backup_token) and secrets.compare_digest(token, backup_token)
    if not authed:
        me = current_user()
        if not me or not me["is_admin"]:
            abort(403)
    db = get_db()
    dump = {"exported_at": now_str(), "tables": {}}
    for t in BACKUP_TABLES:
        try:
            rows = db.execute(f"SELECT * FROM {t}").fetchall()
        except Exception:
            continue
        dump["tables"][t] = [dict(r) for r in rows]
    for c in dump["tables"].get("candidates", []):
        d = c.get("photo_data")
        if d is not None:
            c["photo_data"] = base64.b64encode(bytes(d)).decode("ascii")
    payload = json.dumps(dump, ensure_ascii=False)
    fname = "fuzhong-backup-%s.json" % datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    return Response(payload, mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


RESTORE_ORDER = ["users", "announcements", "forum_posts", "forum_replies",
                 "post_likes", "confessions", "confession_likes",
                 "candidates", "votes", "feedbacks"]
# 只有这些表有 id 自增列（关联表 post_likes / confession_likes 没有 id）
ID_TABLES = TABLES_WITH_ID


def restore_dump(dump):
    """用备份 JSON 恢复全站数据：先清空，再按父表优先顺序写入（含原始 id）。
    返回恢复的总记录数。"""
    tables = dump.get("tables") or {}
    if "users" not in tables or "candidates" not in tables:
        raise ValueError("备份文件无效：缺少必要的数据表")
    present = [t for t in RESTORE_ORDER if t in tables]
    db = get_db()
    if USE_PG:
        db.execute("TRUNCATE %s RESTART IDENTITY CASCADE" % ", ".join(present))
    else:
        for t in reversed(present):
            db.execute(f"DELETE FROM {t}")
    total = 0
    for t in present:
        for r in tables[t] or []:
            r = dict(r)
            if t == "candidates" and r.get("photo_data"):
                r["photo_data"] = base64.b64decode(r["photo_data"])
            cols = list(r.keys())
            db.execute(
                f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join(['?'] * len(cols))})",
                tuple(r[c] for c in cols))
            total += 1
    if USE_PG:
        for t in present:
            if t in ID_TABLES:
                db.execute(
                    "SELECT setval(pg_get_serial_sequence(?, 'id'),"
                    " (SELECT COALESCE(MAX(id), 1) FROM %s))" % t, (t,))
    db.commit()
    return total


@app.route("/admin/restore", methods=["POST"])
@admin_required
def admin_restore():
    f = request.files.get("backup")
    if not f or not f.filename:
        flash("请选择备份文件", "error")
        return redirect(url_for("admin"))
    try:
        dump = json.load(f.stream)
    except Exception:
        flash("备份文件格式不正确", "error")
        return redirect(url_for("admin"))
    try:
        n = restore_dump(dump)
    except Exception as e:
        flash(f"恢复失败：{e}", "error")
        return redirect(url_for("admin"))
    session.clear()
    flash(f"恢复成功，共 {n} 条记录。请用备份时的账号重新登录", "ok")
    return redirect(url_for("login"))


@app.route("/admin/announce", methods=["POST"])
@admin_required
def admin_announce():
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    if not title or not body:
        flash("标题和内容不能为空", "error")
    else:
        db = get_db()
        db.execute("INSERT INTO announcements(title, body, created_at)"
                   " VALUES(?,?,?)", (title, body, now_str()))
        db.commit()
        flash("公告已发布", "ok")
    return redirect(url_for("admin"))


@app.route("/admin/delete/<kind>/<int:oid>", methods=["POST"])
@admin_required
def admin_delete(kind, oid):
    db = get_db()
    if kind == "post":
        db.execute("DELETE FROM forum_posts WHERE id=?", (oid,))
    elif kind == "confession":
        db.execute("DELETE FROM confessions WHERE id=?", (oid,))
    elif kind == "candidate":
        db.execute("DELETE FROM candidates WHERE id=?", (oid,))
    elif kind == "announcement":
        db.execute("DELETE FROM announcements WHERE id=?", (oid,))
    elif kind == "feedback":
        db.execute("DELETE FROM feedbacks WHERE id=?", (oid,))
    else:
        abort(400)
    db.commit()
    flash("已删除", "ok")
    return redirect(url_for("admin"))


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("数据库初始化完成，管理员账号：admin")


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

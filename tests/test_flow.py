#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全流程自测：注册→发帖→回帖→点赞→表白→报名(照片)→投票→改投→搜索→管理后台。
运行：cd school-vote-deploy && .venv/bin/python tests/test_flow.py
要求：全程无 500，所有断言通过。"""
import io
import os
import re
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

tmp = tempfile.mkdtemp(prefix="fzwall_test_")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DATABASE"] = os.path.join(tmp, "test.db")
os.environ["UPLOAD_FOLDER"] = os.path.join(tmp, "uploads")

import app as appmod

TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
passed = []


def check(name, cond):
    assert cond, f"FAILED: {name}"
    passed.append(name)
    print(f"  ✓ {name}")


def token(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"GET {path} -> {r.status_code}"
    m = TOKEN_RE.search(r.get_data(as_text=True))
    assert m, f"no csrf token on {path}"
    return m.group(1)


def make_photo():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (180, 40, 40)).save(buf, "PNG")
    buf.seek(0)
    return buf


def main():
    appmod.app.config["TESTING"] = True
    with appmod.app.app_context():
        appmod.init_db()
    c = appmod.app.test_client()

    print("== 账号 ==")
    t = token(c, "/register")
    r = c.post("/register", data={"username": "tester", "password": "pw123456",
                                  "csrf_token": t}, follow_redirects=True)
    check("注册成功", "欢迎，tester" in r.get_data(as_text=True))
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    r = c.post("/login", data={"username": "tester", "password": "pw123456",
                               "csrf_token": t}, follow_redirects=True)
    check("登录成功", "欢迎回来" in r.get_data(as_text=True))
    # 未登录拦截
    c.post("/logout", data={"csrf_token": token(c, "/")})
    r = c.post("/forum/new", data={"csrf_token": "x"})
    check("未登录发帖被拦截(400 csrf)", r.status_code in (302, 400))
    t = token(c, "/login")
    c.post("/login", data={"username": "tester", "password": "pw123456",
                           "csrf_token": t})

    print("== 论坛 ==")
    t = token(c, "/forum/new")
    r = c.post("/forum/new", data={"title": "测试帖标题", "category": "学习",
                                   "body": "这是正文内容测试",
                                   "csrf_token": t}, follow_redirects=True)
    check("发帖成功", "测试帖标题" in r.get_data(as_text=True))
    pid = 1
    r = c.get(f"/forum/{pid}")
    check("帖子详情 200", r.status_code == 200)
    t = token(c, f"/forum/{pid}")
    r = c.post(f"/forum/{pid}/reply",
               data={"body": "测试回帖", "csrf_token": t}, follow_redirects=True)
    check("回帖成功", "测试回帖" in r.get_data(as_text=True))
    r = c.post(f"/forum/{pid}/like", data={"csrf_token": t},
               follow_redirects=True)
    check("点赞成功", "♥ 已赞 1" in r.get_data(as_text=True) or "已赞" in r.get_data(as_text=True))

    print("== 表白墙 ==")
    t = token(c, "/confess")
    r = c.post("/confess/new", data={"nickname": "小测", "body": "测试表白内容啦啦",
                                     "csrf_token": t}, follow_redirects=True)
    check("表白发布成功", "测试表白内容啦啦" in r.get_data(as_text=True))
    r = c.post("/confess/1/like", data={"csrf_token": t}, follow_redirects=True)
    check("表白点赞成功", r.status_code == 200)

    print("== 评选报名（含照片） ==")
    t = token(c, "/vote/signup")
    photo = (make_photo(), "me.png")
    r = c.post("/vote/signup",
               data={"board": "xiaohua", "name": "测试候选人", "class_name": "高一(3)班",
                     "slogan": "请为我投票", "csrf_token": t, "photo": photo},
               content_type="multipart/form-data", follow_redirects=True)
    body = r.get_data(as_text=True)
    check("报名成功直上榜", "测试候选人" in body and "报名成功" in body)
    import sqlite3 as _sq3
    _con = _sq3.connect(os.environ["DATABASE"])
    _row = _con.execute("SELECT photo_data, photo_mime FROM candidates WHERE name='测试候选人'").fetchone()
    check("照片已存入数据库", _row is not None and _row[0] is not None and len(_row[0]) > 100
          and _row[1] == "image/png")
    _con.close()
    m = re.search(r"/candidate-photo/(\d+)", body)
    check("榜单页含照片链接", m is not None)
    r = c.get(f"/candidate-photo/{m.group(1)}")
    check("照片可正常访问", r.status_code == 200 and r.content_type == "image/png"
          and len(r.get_data()) > 100)

    print("== 投票 / 改投 ==")
    t = token(c, "/vote?board=xiaohua")
    r = c.post("/vote/cast", data={"candidate_id": "1", "csrf_token": t},
               follow_redirects=True)
    check("投票成功", "投票成功" in r.get_data(as_text=True))
    # 第二位候选人
    photo2 = (make_photo(), "me2.png")
    c.post("/vote/signup",
           data={"board": "xiaohua", "name": "候选人二号", "class_name": "高二(1)班",
                 "slogan": "二号宣言", "csrf_token": t, "photo": photo2},
           content_type="multipart/form-data")
    t = token(c, "/vote?board=xiaohua")
    r = c.post("/vote/cast", data={"candidate_id": "2", "csrf_token": t},
               follow_redirects=True)
    body = r.get_data(as_text=True)
    check("改投成功", "改投成功" in body)
    # 验票数：一号 0、二号 1
    import sqlite3
    db = sqlite3.connect(os.path.join(tmp, "test.db"))
    v1 = db.execute("SELECT COUNT(*) FROM votes WHERE candidate_id=1").fetchone()[0]
    v2 = db.execute("SELECT COUNT(*) FROM votes WHERE candidate_id=2").fetchone()[0]
    check("改投后票数正确(0/1)", v1 == 0 and v2 == 1)
    db.close()

    print("== 搜索 ==")
    r = c.get("/search?q=测试帖")
    check("搜到帖子", "测试帖标题" in r.get_data(as_text=True))
    r = c.get("/search?q=表白内容")
    check("搜到表白", "测试表白内容啦啦" in r.get_data(as_text=True))
    r = c.get("/search?q=候选人二号")
    check("搜到候选人", "候选人二号" in r.get_data(as_text=True))
    r = c.get("/search?q=不存在xyz")
    check("无结果友好提示", "没有找到" in r.get_data(as_text=True))

    print("== 页面无 500 ==")
    for path in ["/", "/forum", "/forum?cat=学习", "/confess", "/search",
                 "/vote", "/vote?board=xiaocao", "/vote?board=mascot",
                 "/vote/signup", "/register", "/login"]:
        r = c.get(path)
        check(f"GET {path} -> {r.status_code}", r.status_code == 200)

    print("== 管理后台 ==")
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "admin", "password": "admin12345",
                           "csrf_token": t})
    r = c.get("/admin")
    check("管理员后台 200 且有统计", r.status_code == 200 and "数据统计" in r.get_data(as_text=True))

    print(f"\n全部通过：{len(passed)} 项 ✓")


if __name__ == "__main__":
    main()

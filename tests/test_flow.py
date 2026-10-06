#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全流程自测：注册→发帖→回帖→点赞→表白→报名(照片)→投票→改投→搜索→管理后台。
运行：cd school-vote-deploy && .venv/bin/python tests/test_flow.py
要求：全程无 500，所有断言通过。"""
import io
import os
import re
import sqlite3
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
    # 注册 IP 已记录，属地已解析缓存（127.0.0.1 → 内网，不调外网）
    _dbb = sqlite3.connect(os.path.join(tmp, "test.db"))
    _u = _dbb.execute("SELECT reg_ip FROM users WHERE username='tester'").fetchone()
    check("注册记录 IP", _u and _u[0] == "127.0.0.1")
    _g = _dbb.execute("SELECT region FROM ip_geo WHERE ip='127.0.0.1'").fetchone()
    check("IP 属地缓存", _g and _g[0] == "内网")
    _dbb.close()
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
    check("点赞成功", "is-liked" in r.get_data(as_text=True))
    # AJAX 点赞：返回 JSON，再点一次取消
    r = c.post(f"/forum/{pid}/like", data={"csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("AJAX 取消点赞 JSON", d["ok"] and d["liked"] is False and d["likes"] == 0)
    r = c.post(f"/forum/{pid}/like", data={"csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("AJAX 点赞 JSON", d["ok"] and d["liked"] is True and d["likes"] == 1)

    print("== 表白墙 ==")
    t = token(c, "/confess")
    r = c.post("/confess/new", data={"nickname": "小测", "kind": "表白",
                                     "target": "高二(3)班小王",
                                     "body": "测试表白内容啦啦",
                                     "csrf_token": t}, follow_redirects=True)
    body = r.get_data(as_text=True)
    check("表白发布成功", "测试表白内容啦啦" in body)
    check("表白XXX 格式显示", "表白高二(3)班小王" in body)
    check("表白卡显示 IP 属地", "IP属地" in body and "内网" in body)
    r = c.post("/confess/new", data={"kind": "捞人", "target": "食堂的长发女生",
                                     "body": "今天中午食堂二楼，有认识的吗",
                                     "csrf_token": t}, follow_redirects=True)
    check("捞人发布成功", "捞人食堂的长发女生" in r.get_data(as_text=True))
    r = c.post("/confess/new", data={"kind": "表白", "target": "",
                                     "body": "没有对象的内容",
                                     "csrf_token": t}, follow_redirects=True)
    check("缺少对象被拒绝", "请填写表白对象" in r.get_data(as_text=True))
    r = c.post("/confess/1/like", data={"csrf_token": t}, follow_redirects=True)
    check("表白点赞成功", r.status_code == 200)
    r = c.post("/confess/1/like", data={"csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("AJAX 表白取消点赞 JSON", d["ok"] and d["liked"] is False and d["likes"] == 0)

    print("== 评论区与屏蔽词 ==")
    r = c.post("/confess/1/comment", data={"body": "祝福你们！", "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("AJAX 评论成功", d["ok"] and d["comment"]["body"] == "祝福你们！")
    r = c.get("/confess")
    check("评论显示在卡片下", "祝福你们！" in r.get_data(as_text=True))
    r = c.post("/confess/1/comment", data={"body": "你这个傻逼", "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("评论屏蔽词被拦截", not d["ok"] and "屏蔽词" in d["error"])
    r = c.post("/confess/new", data={"kind": "表白", "target": "小王",
                                     "body": "你这个傻逼", "csrf_token": t},
               follow_redirects=True)
    check("表白屏蔽词被拦截", "屏蔽词" in r.get_data(as_text=True))
    r = c.post("/forum/new", data={"title": "正常标题", "category": "学习",
                                   "body": "这篇正文很正常没有问题",
                                   "csrf_token": t}, follow_redirects=True)
    check("正常发帖不受影响", "发帖成功" in r.get_data(as_text=True) or "正常标题" in r.get_data(as_text=True))

    print("== 评选报名（含照片） ==")
    t = token(c, "/vote/signup")
    photo = (make_photo(), "me.png")
    r = c.post("/vote/signup",
               data={"board": "xiaohua", "name": "测试候选人", "class_name": "高一(3)班",
                     "slogan": "请为我投票", "csrf_token": t, "photo": photo},
               content_type="multipart/form-data", follow_redirects=True)
    body = r.get_data(as_text=True)
    check("报名成功直上榜", "测试候选人" in body and "报名成功" in body)
    _con = sqlite3.connect(os.environ["DATABASE"])
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
    db = sqlite3.connect(os.path.join(tmp, "test.db"))
    v1 = db.execute("SELECT COUNT(*) FROM votes WHERE candidate_id=1").fetchone()[0]
    v2 = db.execute("SELECT COUNT(*) FROM votes WHERE candidate_id=2").fetchone()[0]
    check("改投后票数正确(0/1)", v1 == 0 and v2 == 1)
    db.close()
    # AJAX 投票：改投回一号，返回 JSON
    t = token(c, "/vote?board=xiaohua")
    r = c.post("/vote/cast", data={"candidate_id": "1", "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("AJAX 投票 JSON", d["ok"] and d["candidate_id"] == 1
          and d["changed"] is True and d["votes"] == 1)
    # 手动补票：extra_votes 计入展示票数
    _dbb = sqlite3.connect(os.path.join(tmp, "test.db"))
    _dbb.execute("UPDATE candidates SET extra_votes=34 WHERE id=1")
    _dbb.commit()
    _v = _dbb.execute("SELECT ip FROM votes LIMIT 1").fetchone()
    check("投票记录 IP", _v and _v[0] == "127.0.0.1")
    _dbb.close()
    r = c.get("/vote?board=xiaohua")
    check("补票后展示票数含 extra_votes", ">35</span>" in r.get_data(as_text=True))

    print("== 搜索 ==")
    r = c.get("/search?q=测试帖")
    check("搜到帖子", "测试帖标题" in r.get_data(as_text=True))
    r = c.get("/search?q=表白内容")
    check("搜到表白", "测试表白内容啦啦" in r.get_data(as_text=True))
    r = c.get("/search?q=小王")
    check("按对象名搜到表白", "表白高二(3)班小王" in r.get_data(as_text=True))
    r = c.get("/search?q=候选人二号")
    check("搜到候选人", "候选人二号" in r.get_data(as_text=True))
    r = c.get("/search?q=不存在xyz")
    check("无结果友好提示", "没有找到" in r.get_data(as_text=True))

    print("== 意见反馈 ==")
    anon = appmod.app.test_client()
    check("反馈页需登录", anon.get("/feedback").status_code == 302)
    t = token(c, "/register")
    c.post("/register", data={"username": "fbuser", "password": "fbpass123",
                              "csrf_token": t})
    t = token(c, "/login")
    c.post("/login", data={"username": "fbuser", "password": "fbpass123",
                           "csrf_token": t})
    t = token(c, "/feedback")
    r = c.post("/feedback", data={"type": "suggest", "body": "希望增加暗色模式",
                                  "contact": "", "csrf_token": t},
               follow_redirects=True)
    body = r.get_data(as_text=True)
    check("反馈提交成功", "反馈已提交" in body and "希望增加暗色模式" in body)
    check("我的反馈显示待处理", "待处理" in body)

    print("== 页面无 500 ==")
    for path in ["/", "/forum", "/forum?cat=学习", "/confess", "/search",
                 "/vote", "/vote?board=xiaocao", "/vote?board=mascot",
                 "/vote/signup", "/feedback", "/register", "/login"]:
        r = c.get(path)
        check(f"GET {path} -> {r.status_code}", r.status_code == 200)

    print("== 管理后台 ==")
    c.post("/logout", data={"csrf_token": token(c, "/")})
    # 注册两个小号，制造同 IP 多账号场景（同一设备指纹）
    c.set_cookie("did", "testdeviceABC")
    for _u2 in ("brush1", "brush2"):
        t = token(c, "/register")
        c.post("/register", data={"username": _u2, "password": "pw123456",
                                  "csrf_token": t})
        c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "admin", "password": "admin12345",
                           "csrf_token": t})
    r = c.get("/admin")
    check("管理员后台 200 且有统计", r.status_code == 200 and "数据统计" in r.get_data(as_text=True))
    check("后台看到用户反馈", "希望增加暗色模式" in r.get_data(as_text=True))
    check("IP 审计区列出多账号 IP", "IP 审计" in r.get_data(as_text=True)
          and "127.0.0.1" in r.get_data(as_text=True))
    check("设备审计区列出关联设备", "设备关联" in r.get_data(as_text=True)
          and "testdeviceAB" in r.get_data(as_text=True))
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    _d = _db.execute("SELECT reg_device FROM users WHERE username='brush1'").fetchone()
    check("注册记录设备指纹", _d and _d[0] == "testdeviceABC")
    _db.close()
    # 小号 brush1 刷一票，管理员清票
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    _brush = _db.execute("SELECT id FROM users WHERE username='brush1'").fetchone()[0]
    _db.close()
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "brush1", "password": "pw123456",
                           "csrf_token": t})
    t = token(c, "/vote?board=xiaohua")
    c.post("/vote/cast", data={"candidate_id": "2", "csrf_token": t})
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    _vd = _db.execute("SELECT device FROM votes WHERE user_id=?",
                      (_brush,)).fetchone()
    _db.close()
    check("投票记录设备指纹", _vd and _vd[0] == "testdeviceABC")
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "admin", "password": "admin12345",
                           "csrf_token": t})
    t = token(c, "/admin")
    r = c.post(f"/admin/purge-votes/{_brush}", data={"csrf_token": t},
               follow_redirects=True)
    check("清票成功", "已清除该账号 1 张投票" in r.get_data(as_text=True))
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    _n = _db.execute("SELECT COUNT(*) FROM votes WHERE user_id=?",
                     (_brush,)).fetchone()[0]
    _db.close()
    check("刷票已清除", _n == 0)
    # 一键清除异常账号组：brush2 投一票，按设备一键清除整组
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "brush2", "password": "pw123456",
                           "csrf_token": t})
    t = token(c, "/vote?board=xiaohua")
    c.post("/vote/cast", data={"candidate_id": "2", "csrf_token": t})
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "admin", "password": "admin12345",
                           "csrf_token": t})
    t = token(c, "/admin")
    r = c.post("/admin/purge-group", data={"kind": "device", "key": "testdeviceABC",
                                           "csrf_token": t}, follow_redirects=True)
    check("一键清除异常组", "已清除 2 个账号的 1 张投票" in r.get_data(as_text=True))
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    _n = _db.execute("SELECT COUNT(*) FROM votes WHERE user_id IN"
                     " (SELECT id FROM users WHERE reg_device='testdeviceABC')").fetchone()[0]
    _a = _db.execute("SELECT COUNT(*) FROM users WHERE reg_device='testdeviceABC'").fetchone()[0]
    _db.close()
    check("整组投票已清除且账号保留", _n == 0 and _a == 2)
    m = re.search(r"/admin/feedback/(\d+)/handle", r.get_data(as_text=True))
    check("反馈处理按钮存在", m is not None)
    t = token(c, "/admin")
    r = c.post(f"/admin/feedback/{m.group(1)}/handle", data={"csrf_token": t},
               follow_redirects=True)
    check("反馈标为已处理", "已处理" in r.get_data(as_text=True))
    t = token(c, "/admin")
    r = c.post("/admin/blocked-words", data={"word": "测试屏蔽词", "csrf_token": t},
               follow_redirects=True)
    check("后台添加屏蔽词", "测试屏蔽词" in r.get_data(as_text=True))
    import re as _re2
    m2 = _re2.search(r"测试屏蔽词\s*<form action=\"/admin/delete/blockedword/(\d+)\"",
                     r.get_data(as_text=True), _re2.S)
    check("找到测试屏蔽词的删除链接", m2 is not None)
    r = c.post(f"/admin/delete/blockedword/{m2.group(1)}",
               data={"csrf_token": t}, follow_redirects=True)
    check("后台删除屏蔽词", "测试屏蔽词" not in r.get_data(as_text=True))

    print("== 公告投票 ==")
    t = token(c, "/admin")
    r = c.post("/admin/announce",
               data={"title": "周末活动投票", "body": "请大家投票选择",
                     "poll_question": "周六下午去哪玩？",
                     "poll_options": "图书馆\n操场\n电竞馆",
                     "csrf_token": t}, follow_redirects=True)
    check("公告+投票发布成功", "公告已发布（含投票）" in r.get_data(as_text=True))
    r = c.post("/admin/announce",
               data={"title": "无效投票", "body": "只有一个选项",
                     "poll_question": "选一个？", "poll_options": "唯一选项",
                     "csrf_token": t}, follow_redirects=True)
    check("选项不足被拒绝", "至少两个选项" in r.get_data(as_text=True))
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    _db.row_factory = sqlite3.Row
    _poll = _db.execute(
        "SELECT * FROM polls WHERE question='周六下午去哪玩？'").fetchone()
    check("投票已入库", _poll is not None)
    _opts = _db.execute("SELECT * FROM poll_options WHERE poll_id=? ORDER BY sort",
                        (_poll["id"],)).fetchall()
    check("三个选项已入库", len(_opts) == 3)
    _db.close()
    # 普通用户投票
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "tester", "password": "pw123456",
                           "csrf_token": t})
    r = c.get("/")
    check("首页显示投票问题", "周六下午去哪玩？" in r.get_data(as_text=True))
    t = token(c, "/")
    pid = _poll["id"]
    oid1, oid2 = _opts[0]["id"], _opts[1]["id"]
    r = c.post(f"/poll/{pid}/vote", data={"option_id": str(oid1), "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("AJAX 投票 JSON", d["ok"] and d["option_id"] == oid1
          and d["total"] == 1 and d["options"][0]["votes"] == 1
          and d["options"][0]["pct"] == 100)
    r = c.post(f"/poll/{pid}/vote", data={"option_id": str(oid1), "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    check("重复投同一选项不重复计票", r.get_json()["total"] == 1)
    r = c.post(f"/poll/{pid}/vote", data={"option_id": str(oid2), "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("改投后票数转移",
          d["options"][0]["votes"] == 0 and d["options"][1]["votes"] == 1)
    # 管理员也投一票
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "admin", "password": "admin12345",
                           "csrf_token": t})
    t = token(c, "/")
    r = c.post(f"/poll/{pid}/vote", data={"option_id": str(oid1), "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("两人投票总数 2", d["total"] == 2 and d["options"][0]["pct"] == 50)
    # 管理员关闭投票
    t = token(c, "/admin")
    r = c.post(f"/admin/poll/{pid}/toggle", data={"csrf_token": t},
               follow_redirects=True)
    check("关闭投票", "投票已关闭" in r.get_data(as_text=True))
    r = c.get("/admin")
    check("后台显示已关闭", "已关闭" in r.get_data(as_text=True))
    t = token(c, "/")
    r = c.post(f"/poll/{pid}/vote", data={"option_id": str(oid2), "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    d = r.get_json()
    check("关闭后投票被拒绝", not d["ok"] and "已结束" in d["error"])
    r = c.get("/")
    check("首页显示投票已结束", "投票已结束" in r.get_data(as_text=True))
    # 重新开启
    t = token(c, "/admin")
    r = c.post(f"/admin/poll/{pid}/toggle", data={"csrf_token": t},
               follow_redirects=True)
    check("重新开启投票", "重新开启" in r.get_data(as_text=True))
    t = token(c, "/")
    r = c.post(f"/poll/{pid}/vote", data={"option_id": str(oid2), "csrf_token": t},
               headers={"X-Requested-With": "XMLHttpRequest"})
    check("重开后可投票", r.get_json()["ok"])
    # 删除公告级联删除投票
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    _aid = _db.execute("SELECT id FROM announcements WHERE title='周末活动投票'").fetchone()[0]
    _db.close()
    t = token(c, "/admin")
    c.post(f"/admin/delete/announcement/{_aid}", data={"csrf_token": t},
           follow_redirects=True)
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    n = _db.execute("SELECT COUNT(*) FROM polls").fetchone()[0]
    _db.close()
    check("删除公告级联删除投票", n == 0)
    # 登回管理员，供后续备份/恢复测试使用
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "admin", "password": "admin12345",
                           "csrf_token": t})

    print("== 冠军与成就 ==")
    os.environ["VOTE_DEADLINE"] = "2020-01-01 00:00"  # 模拟投票已截止
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "tester", "password": "pw123456",
                           "csrf_token": t})
    r = c.get("/")
    body = r.get_data(as_text=True)
    check("首页展示评选结果", "评选结果揭晓" in body and "测试候选人" in body)
    check("冠军照片带皇冠", "👑" in body)
    check("冠军账号首次打开弹出成就", "恭喜夺冠" in body and "achieveOverlay" in body)
    check("侧栏显示成就徽章", "👑校花" in body)
    r = c.get("/vote?board=xiaohua")
    check("榜单冠军照片带皇冠", "👑" in r.get_data(as_text=True))
    t = token(c, "/")
    c.post("/achievement/seen", data={"csrf_token": t}, follow_redirects=True)
    r = c.get("/")
    check("确认后不再弹窗", "achieveOverlay" not in r.get_data(as_text=True))
    check("成就徽章保留", "👑校花" in r.get_data(as_text=True))
    _db = sqlite3.connect(os.path.join(tmp, "test.db"))
    _a = _db.execute("SELECT seen FROM achievements WHERE board='xiaohua'").fetchone()
    _db.close()
    check("成就已标记已看", _a and _a[0] == 1)
    del os.environ["VOTE_DEADLINE"]  # 恢复默认截止时间
    c.post("/logout", data={"csrf_token": token(c, "/")})
    t = token(c, "/login")
    c.post("/login", data={"username": "admin", "password": "admin12345",
                           "csrf_token": t})

    print("== 数据备份 ==")
    r = c.get("/admin/backup")
    check("备份下载 200", r.status_code == 200)
    import json as _json
    dump = _json.loads(r.get_data(as_text=True))
    check("备份含全部表", set(["users", "forum_posts", "confessions",
                             "candidates", "votes", "feedbacks",
                             "polls", "poll_options", "poll_votes",
                             "confession_comments", "blocked_words"]) <= set(dump["tables"].keys()))
    check("备份含反馈数据", any(f["body"] == "希望增加暗色模式"
                             for f in dump["tables"]["feedbacks"]))
    c2 = appmod.app.test_client()
    check("备份拒绝未登录", c2.get("/admin/backup").status_code == 403)

    print("== 数据恢复 ==")
    import tempfile as _tf
    _bak_path = os.path.join(_tf.mkdtemp(prefix="fzwall_restore_"), "bak.json")
    with open(_bak_path, "w", encoding="utf-8") as _f:
        _f.write(r.get_data(as_text=True))
    with open(_bak_path, "rb") as _f:
        r = c.post("/admin/restore",
                   data={"backup": (_f, "bak.json"), "csrf_token": token(c, "/admin")},
                   content_type="multipart/form-data", follow_redirects=True)
    check("恢复成功", "恢复成功" in r.get_data(as_text=True))
    t = token(c, "/login")
    c.post("/login", data={"username": "admin", "password": "admin12345",
                           "csrf_token": t})
    r = c.get("/admin")
    check("恢复后反馈数据仍在", "希望增加暗色模式" in r.get_data(as_text=True))
    r = c.get("/vote?board=xiaohua")
    check("恢复后候选人仍在", "测试候选人" in r.get_data(as_text=True))

    print("== 恢复逻辑一致性 ==")
    import re as _re
    _blocks = _re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\((.*?)\);",
                          appmod.SCHEMA, _re.S)
    _with_id = {n for n, b in _blocks
                if _re.search(r"^\s*id INTEGER PRIMARY KEY", b, _re.M)}
    check("ID_TABLES 与表结构一致",
          set(appmod.ID_TABLES) == (_with_id & set(appmod.RESTORE_ORDER)))

    print("== PG 兼容：INSERT 改写 ==")

    class _FakeRaw:
        def __init__(self):
            self.sqls = []

        def execute(self, q, params=()):
            self.sqls.append(q)

        def fetchone(self):
            return {"id": 1}

    _fake = _FakeRaw()
    _cur = appmod.Cursor.__new__(appmod.Cursor)
    _cur._is_pg = True
    _cur._cur = _fake
    _cur._lastrowid = None
    _cur.execute("INSERT INTO confession_likes(user_id, confession_id) VALUES(?,?)",
                 (1, 2))
    _cur.execute("INSERT INTO post_likes(user_id, post_id) VALUES(?,?)", (1, 2))
    _cur.execute("INSERT INTO confessions(nickname, body) VALUES(?,?)", ("a", "b"))
    check("关联表 INSERT 不追加 RETURNING id",
          all("RETURNING" not in s for s in _fake.sqls[:2]))
    check("普通表 INSERT 追加 RETURNING id",
          "RETURNING id" in _fake.sqls[2])
    check("? 占位符转为 %s",
          "%s" in _fake.sqls[0] and "?" not in _fake.sqls[0])

    print(f"\n全部通过：{len(passed)} 项 ✓")


if __name__ == "__main__":
    main()

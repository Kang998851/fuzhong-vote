# 附中墙 · 太原师范学院附属中学校园社区站

Flask + SQLite/Postgres + Jinja2 + 原生 CSS/JS，无构建步骤。
功能：首页仪表盘、论坛（发帖/回帖/点赞）、表白墙（发布/点赞/最热排序）、
全站搜索、评选（三榜单/每日每榜限投/当天改投/照片报名直上榜/倒计时）、
注册登录、管理后台统计。管理员账号：`admin` / `admin12345`（首次部署后请登录改密）。

## 一、本地运行（5 分钟）

```bash
cd school-vote-deploy
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export SECRET_KEY=随便换个随机字符串
# 初始化数据库（建表 + admin 账号），默认 SQLite：./data/app.db（WAL 模式）
python -c "from app import app, init_db; ctx=app.app_context(); ctx.push(); init_db()"

python app.py   # 浏览器打开 http://127.0.0.1:5000
```

生产启动用 gunicorn：`gunicorn app:app --bind 0.0.0.0:5000 --workers 3`

## 二、数据库切换：SQLite / Postgres

- **默认 SQLite**：不设置 `DATABASE_URL` 即用 `./data/app.db`，并发写已开 WAL，适合本地和自有服务器。
- **Postgres**：设置环境变量 `DATABASE_URL=postgresql://user:pass@host:5432/dbname`，
  应用启动时自动建表（SERIAL 主键），SQL 已做双兼容（`?` 占位符自动转 `%s`，
  排行查询用子查询写法，Postgres 的 GROUP BY 限制已规避）。

## 三、部署到自有服务器（systemd + nginx）

```bash
# 1. 传代码到服务器，如 /srv/school-vote-deploy，建 venv 装依赖
python3 -m venv /srv/school-vote-deploy/.venv
/srv/school-vote-deploy/.venv/bin/pip install -r requirements.txt

# 2. 初始化数据库（SQLite，文件会落在 ./data/app.db）
cd /srv/school-vote-deploy
SECRET_KEY=换随机串 ./.venv/bin/python -c \
  "from app import app, init_db; ctx=app.app_context(); ctx.push(); init_db()"

# 3. 安装 systemd 服务（先改 deploy/school-vote.service 里的路径/用户/SECRET_KEY）
sudo cp deploy/school-vote.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now school-vote

# 4. nginx 反向代理（先改 deploy/nginx-school-vote.conf 里的域名）
sudo cp deploy/nginx-school-vote.conf /etc/nginx/sites-available/school-vote
sudo ln -s /etc/nginx/sites-available/school-vote /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 5. HTTPS（推荐）：sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d vote.example.com
```

备份：SQLite 直接拷贝 `./data/app.db*`；`uploads/` 为用户上传照片，一并备份。

## 四、Render 一键部署（免费方案）

1. 把本目录推到 GitHub 仓库。
2. Render Dashboard → New → **Blueprint**，选择该仓库，`render.yaml` 会自动创建：
   - Web 服务（Python，免费）：`pip install -r requirements.txt` → 初始化数据库 → `gunicorn app:app`
   - Postgres 数据库（免费）：通过 `DATABASE_URL` 自动注入，应用自动切换到 Postgres 模式。
3. 部署完成后会给一个 `https://xxx.onrender.com` 公网地址。

⚠️ **Render 免费版的两个限制，务必知晓：**
- **磁盘是临时的**：`uploads/` 下的用户上传照片在服务重启/重新部署后会丢失。
  长期运营请把照片存到对象存储（如 Cloudflare R2 / AWS S3），或改用自有服务器部署。
- **免费 Postgres 有有效期**（到期后数据会被清理）：正式长期使用请升级付费数据库，
  或改用上面的自有服务器 + SQLite 方案（数据完全自己掌控）。

## 五、环境变量一览

| 变量 | 说明 | 默认 |
|---|---|---|
| `SECRET_KEY` | Flask 会话密钥，生产务必更换 | `dev-insecure-change-me` |
| `DATABASE_URL` | 设置即用 Postgres；留空用 SQLite | 空 |
| `DATABASE` | SQLite 文件路径（仅 SQLite 模式） | `./data/app.db` |
| `UPLOAD_FOLDER` | 照片上传目录 | `./uploads` |
| `VOTE_DEADLINE` | 投票截止（Asia/Shanghai），`YYYY-MM-DD HH:MM` | `2026-10-07 23:59` |
| `PORT` | 监听端口 | `5000` |

## 六、目录结构

```
school-vote-deploy/
├── app.py                 # 应用主体（路由 + 双数据库层）
├── templates/             # Jinja2 模板
├── static/                # style.css / app.js / 校徽图片
├── uploads/               # 用户上传照片（.gitkeep）
├── data/                  # SQLite 文件（运行时生成）
├── tests/test_flow.py     # 全流程自测
├── requirements.txt
├── render.yaml            # Render 一键部署
├── Dockerfile             # 自有服务器 Docker 部署（可选）
├── .env.example
├── deploy/                # systemd + nginx 样例
└── README.md
```

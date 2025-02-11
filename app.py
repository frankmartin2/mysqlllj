from flask import Flask, render_template, request, session, redirect, url_for, jsonify, make_response
from sqlalchemy import create_engine, MetaData, Table, select, inspect, text, func
import os
import csv
from io import StringIO
from sshtunnel import SSHTunnelForwarder
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 设置会话密钥

# 存储多个数据库连接信息
DATABASES = {}

# 存储 SSH 隧道信息
SSH_TUNNELS = {}

# 配置日志记录
handler = RotatingFileHandler("app.log", maxBytes=1024 * 1024, backupCount=5)  # 每个文件最大 1MB，保留 5 个备份
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
app.logger.addHandler(handler)

# 获取所有表名
def get_table_names(engine):
    inspector = inspect(engine)
    return inspector.get_table_names()

# 加载表结构
def load_table(engine, table_name):
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=engine)

# 获取表的索引信息
def get_table_indexes(engine, table_name):
    inspector = inspect(engine)
    return inspector.get_indexes(table_name)

# 获取表的注释信息
def get_table_comment(engine, table_name):
    inspector = inspect(engine)
    return inspector.get_table_comment(table_name)

# 分页查询表数据
def get_table_data(engine, table_name, page=1, per_page=10):
    table = load_table(engine, table_name)
    with engine.connect() as connection:
        # 查询总数
        count = connection.execute(select(func.count()).select_from(table)).scalar()
        # 分页查询数据
        stmt = select(table).limit(per_page).offset((page - 1) * per_page)
        result = connection.execute(stmt)
        rows = result.fetchall()
        columns = result.keys()
    return rows, columns, count

# 首页（展示数据库连接表单）
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # 获取用户输入的数据库信息
        db_name = request.form.get("db_name")
        db_host = request.form.get("db_host")
        db_port = int(request.form.get("db_port", 3306))  # 默认 MySQL 端口
        db_user = request.form.get("db_user")
        db_password = request.form.get("db_password")
        db_database = request.form.get("db_database")

        # SSH 隧道配置
        use_ssh = request.form.get("use_ssh") == "on"
        ssh_host = request.form.get("ssh_host")
        ssh_port = int(request.form.get("ssh_port", 22))  # 默认 SSH 端口
        ssh_user = request.form.get("ssh_user")
        ssh_password = request.form.get("ssh_password")
        ssh_pkey = request.form.get("ssh_pkey")

        try:
            if use_ssh:
                # 创建 SSH 隧道
                ssh_tunnel = SSHTunnelForwarder(
                    (ssh_host, ssh_port),
                    ssh_username=ssh_user,
                    ssh_password=ssh_password,
                    ssh_pkey=ssh_pkey,
                    remote_bind_address=(db_host, db_port),
                    local_bind_address=('127.0.0.1', 0)  # 自动分配本地端口
                )
                ssh_tunnel.start()

                # 更新数据库连接信息
                db_host = '127.0.0.1'
                db_port = ssh_tunnel.local_bind_port
                SSH_TUNNELS[db_name] = ssh_tunnel  # 存储 SSH 隧道

            # 创建数据库连接
            DATABASE_URI = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_database}"
            engine = create_engine(DATABASE_URI)
            with engine.connect() as connection:
                print("Database connection successful!")

            DATABASES[db_name] = engine  # 存储数据库连接
            session["current_db"] = db_name  # 设置当前数据库
            return redirect(url_for("manage"))  # 跳转到管理页面
        except Exception as e:
            error_message = f"连接失败：{str(e)}"
            if "Access denied" in str(e):
                error_message = "用户名或密码错误，请检查后重试。"
            elif "Unknown MySQL server host" in str(e):
                error_message = "主机地址错误，请检查后重试。"
            return render_template("index.html", error=error_message)

    return render_template("index.html", databases=DATABASES)

# 测试数据库连接
@app.route("/test_connection", methods=["POST"])
def test_connection():
    # 获取用户输入的数据库信息
    db_host = request.form.get("db_host")
    db_port = int(request.form.get("db_port", 3306))  # 默认 MySQL 端口
    db_user = request.form.get("db_user")
    db_password = request.form.get("db_password")
    db_database = request.form.get("db_database")

    # SSH 隧道配置
    use_ssh = request.form.get("use_ssh") == "on"
    ssh_host = request.form.get("ssh_host")
    ssh_port = int(request.form.get("ssh_port", 22))  # 默认 SSH 端口
    ssh_user = request.form.get("ssh_user")
    ssh_password = request.form.get("ssh_password")
    ssh_pkey = request.form.get("ssh_pkey")

    try:
        if use_ssh:
            # 创建 SSH 隧道
            ssh_tunnel = SSHTunnelForwarder(
                (ssh_host, ssh_port),
                ssh_username=ssh_user,
                ssh_password=ssh_password,
                ssh_pkey=ssh_pkey,
                remote_bind_address=(db_host, db_port),
                local_bind_address=('127.0.0.1', 0)  # 自动分配本地端口
            )
            ssh_tunnel.start()

            # 更新数据库连接信息
            db_host = '127.0.0.1'
            db_port = ssh_tunnel.local_bind_port

        # 创建数据库连接
        DATABASE_URI = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_database}"
        engine = create_engine(DATABASE_URI)
        with engine.connect() as connection:
            print("Database connection successful!")
        return jsonify({"success": True, "message": "连接成功！"})
    except Exception as e:
        error_message = f"连接失败：{str(e)}"
        if "Authentication failed" in str(e):
            error_message = "SSH 认证失败，请检查用户名、密码或私钥。"
        elif "Could not establish connection" in str(e):
            error_message = "无法连接到 SSH 主机，请检查主机地址和端口。"
        return jsonify({"success": False, "message": error_message}), 500

# 数据库管理页面
@app.route("/manage", methods=["GET"])
def manage():
    current_db = session.get("current_db")
    if not current_db:
        return redirect(url_for("index"))

    engine = DATABASES.get(current_db)
    if not engine:
        return redirect(url_for("index"))

    table_name = request.args.get("table_name")  # 获取用户点击的表名
    page = int(request.args.get("page", 1))  # 获取当前页码
    per_page = int(request.args.get("per_page", 10))  # 获取每页显示的行数

    rows = []
    columns = []
    total_count = 0
    indexes = []
    comment = ""

    if table_name:
        try:
            # 获取表数据
            rows, columns, total_count = get_table_data(engine, table_name, page, per_page)
            # 获取表的索引和注释
            indexes = get_table_indexes(engine, table_name)
            comment = get_table_comment(engine, table_name)
        except Exception as e:
            error = f"查询失败：{str(e)}"
            return render_template("manage.html", error=error, databases=DATABASES, current_db=current_db)

    return render_template(
        "manage.html",
        databases=DATABASES,
        current_db=current_db,
        table_name=table_name,
        rows=rows,
        columns=columns,
        indexes=indexes,
        comment=comment,
        page=page,
        per_page=per_page,
        total_count=total_count,
        get_table_names=get_table_names,  # 将函数传递给模板
    )

# 切换数据库
@app.route("/switch_db/<db_name>", methods=["GET"])
def switch_db(db_name):
    if db_name in DATABASES:
        session["current_db"] = db_name
    return redirect(url_for("manage"))

# 连接新数据库
@app.route("/connect_new_db", methods=["POST"])
def connect_new_db():
    # 获取表单数据
    db_name = request.form.get("new_db_name")
    db_host = request.form.get("new_db_host")  # 确保这里获取的是新 IP 地址
    db_port = int(request.form.get("new_db_port", 3306))
    db_user = request.form.get("new_db_user")
    db_password = request.form.get("new_db_password")
    db_database = request.form.get("new_db_database")

    # SSH 隧道配置
    use_ssh = request.form.get("use_ssh") == "on"
    ssh_host = request.form.get("ssh_host")
    ssh_port = int(request.form.get("ssh_port", 22))  # 默认 SSH 端口
    ssh_user = request.form.get("ssh_user")
    ssh_password = request.form.get("ssh_password")
    ssh_pkey = request.form.get("ssh_pkey")

    try:
        if use_ssh:
            # 创建 SSH 隧道
            ssh_tunnel = SSHTunnelForwarder(
                (ssh_host, ssh_port),
                ssh_username=ssh_user,
                ssh_password=ssh_password,
                ssh_pkey=ssh_pkey,
                remote_bind_address=(db_host, db_port),
                local_bind_address=('127.0.0.1', 0)  # 自动分配本地端口
            )
            ssh_tunnel.start()

            # 更新数据库连接信息
            db_host = '127.0.0.1'
            db_port = ssh_tunnel.local_bind_port

        # 创建数据库连接
        DATABASE_URI = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_database}"
        engine = create_engine(DATABASE_URI)
        with engine.connect() as connection:
            print("New database connection successful!")
        DATABASES[db_name] = engine  # 存储新的数据库连接
        session["current_db"] = db_name  # 设置当前数据库
        return redirect(url_for("manage"))  # 跳转到管理页面
    except Exception as e:
        return render_template(
            "manage.html",
            error=f"连接失败：{str(e)}",
            databases=DATABASES,
            current_db=session.get("current_db"),
            get_table_names=get_table_names,  # 传递 get_table_names 函数
        )

# 导出表数据为 CSV
@app.route("/export_csv/<table_name>")
def export_csv(table_name):
    engine = DATABASES.get(session.get("current_db"))
    if not engine:
        return redirect(url_for("index"))

    table = load_table(engine, table_name)
    with engine.connect() as connection:
        result = connection.execute(select(table))
        rows = result.fetchall()
        columns = result.keys()

    # 生成 CSV 文件
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)  # 写入列名
    writer.writerows(rows)    # 写入数据

    # 返回 CSV 文件
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename={table_name}.csv"
    response.headers["Content-type"] = "text/csv"
    return response

# 关闭 SSH 隧道
def close_ssh_tunnels():
    for db_name, tunnel in SSH_TUNNELS.items():
        print(f"Closing SSH tunnel for {db_name}")
        tunnel.stop()

# 全局错误处理
@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"500 Error: {str(e)}")
    return render_template("500.html"), 500

@app.errorhandler(404)
def page_not_found(e):
    app.logger.error(f"404 Error: {str(e)}")
    return render_template("404.html"), 404

# 运行应用
if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5000, debug=True)
    finally:
        close_ssh_tunnels()  # 确保应用退出时关闭所有 SSH 隧道

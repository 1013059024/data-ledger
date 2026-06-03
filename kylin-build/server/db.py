"""
麒麟版数据库操作工具 — SQLite 实现
包含 MySQL 语法兼容层（自动转换 %s→?、反引号→双引号）
"""
import re, datetime, sqlite3, os
from config import DB_PATH


# ── MySQL 语法兼容转换 ───────────────────────────────
# 让 app.py 中的 MySQL 风格 SQL 自动适配 SQLite

def _convert_sql(sql):
    """将 MySQL 语法转换为 SQLite 兼容语法"""
    # 1. %s 占位符 → ? （SQLite 原生占位符）
    sql = re.sub(r'(?<!%)%s', '?', sql)
    # 2. 反引号引用 → SQLite 双引号引用
    sql = re.sub(r'`([^`]+)`', r'"\1"', sql)
    return sql


# ── 内部工具 ─────────────────────────────────────────

def _get_conn():
    """获取 SQLite 连接（row_factory = Row，支持按列名访问）"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    return conn


def _ensure_meta():
    """确保 _meta 表存在（用于存储表注释、列注释等元数据）"""
    conn = _get_conn()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS \"_meta\" (\"key\" TEXT PRIMARY KEY, \"value\" TEXT)")
        conn.commit()
    finally:
        conn.close()


def _meta_get(key):
    _ensure_meta()
    conn = _get_conn()
    try:
        r = conn.execute("SELECT \"value\" FROM \"_meta\" WHERE \"key\"=?", (key,)).fetchone()
        return r["value"] if r else None
    finally:
        conn.close()


def _meta_set(key, val):
    _ensure_meta()
    conn = _get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO \"_meta\" (\"key\", \"value\") VALUES (?, ?)", (key, val))
        conn.commit()
    finally:
        conn.close()


def _meta_del(key):
    _ensure_meta()
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM \"_meta\" WHERE \"key\"=?", (key,))
        conn.commit()
    finally:
        conn.close()


# ── 核心查询接口（带语法转换） ──────────────────────

def query(sql, params=None):
    """执行 SELECT，返回所有行（dict 列表）"""
    sql = _convert_sql(sql)  # ← MySQL→SQLite 转换
    conn = _get_conn()
    try:
        cur = conn.execute(sql, params or ())
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql, params=None):
    """执行 SELECT，返回第一行（dict）或 None"""
    sql = _convert_sql(sql)  # ← MySQL→SQLite 转换
    conn = _get_conn()
    try:
        cur = conn.execute(sql, params or ())
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def execute(sql, params=None):
    """执行 INSERT/UPDATE/DELETE/DDL，返回影响行数"""
    sql = _convert_sql(sql)  # ← MySQL→SQLite 转换
    conn = _get_conn()
    try:
        cur = conn.execute(sql, params or ())
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ── 元数据查询 ───────────────────────────────────────

def get_tables():
    """获取所有用户表（排除 _meta、sqlite_ 系统表）"""
    rows = query(
        "SELECT \"name\" FROM \"sqlite_master\" WHERE \"type\"='table' "
        "AND \"name\" NOT LIKE 'sqlite_%' AND \"name\" != '_meta' "
        "ORDER BY \"name\""
    )
    result = []
    for r in rows:
        name = r["name"]
        comment = _meta_get(f"comment:{name}") or ""
        result.append({"name": name, "comment": comment})
    return result


def get_table_comment(tn):
    """获取表注释"""
    return _meta_get(f"comment:{tn}") or ""


def set_table_comment(tn, comment):
    """设置表注释"""
    if comment:
        _meta_set(f"comment:{tn}", comment)
    else:
        _meta_del(f"comment:{tn}")


def get_schema(tn):
    """获取表字段信息（与 MySQL 版返回值一致）"""
    conn = _get_conn()
    try:
        cur = conn.execute("PRAGMA table_info(\"" + tn + "\")")
        cols = cur.fetchall()
        result = []
        for c in cols:
            d = dict(c)
            result.append({
                "field": d["name"],
                "type": d["type"] or "TEXT",
                "nullable": "YES" if d["notnull"] == 0 else "NO",
                "default": d["dflt_value"],
                "comment": "",
            })
        return result
    finally:
        conn.close()


def get_pk_column(tn):
    """获取主键字段名"""
    conn = _get_conn()
    try:
        cur = conn.execute("PRAGMA table_info(\"" + tn + "\")")
        for c in cur.fetchall():
            if c["pk"] > 0:
                return c["name"]
        return None
    finally:
        conn.close()


# ── 去重值（筛选面板用） ─────────────────────────────

def distinct_values(tn, field, search="", filters=None):
    """获取某列的去重值，支持搜索过滤和级联筛选"""
    schema = get_schema(tn)
    if not any(s["field"] == field for s in schema):
        return []
    conds = []
    pa = []
    has_del = any(s["field"] == "_deleted" for s in schema)
    if has_del:
        conds.append("IFNULL(\"_deleted\",0) NOT IN (1,2)")
    if filters and isinstance(filters, dict):
        for fld, vals in filters.items():
            if fld != field and fld in [s["field"] for s in schema] and vals and isinstance(vals, list) and len(vals):
                phs = ", ".join(["?"] * len(vals))
                conds.append(f"\"{fld}\" IN ({phs})")
                pa.extend(vals)
    if search:
        conds.append(f"\"{field}\" LIKE ?")
        pa.append(f"%{search}%")
    ws = " WHERE " + " AND ".join(conds) if conds else ""
    rows = query(
        f"SELECT \"{field}\" AS v, COUNT(*) AS c FROM \"{tn}\"{ws} GROUP BY \"{field}\" ORDER BY \"{field}\"",
        pa,
    )
    return [{"value": r["v"], "count": r["c"]} for r in rows if r["v"] is not None]


# ── 分页查询 ─────────────────────────────────────────

def get_page(tn, page=1, per_page=50, search="", order_field=None, order_dir="asc", hide_deleted=False, filters=None):
    """分页查询（与 MySQL 版接口一致）"""
    offset = (page - 1) * per_page
    schema = get_schema(tn)
    if not schema:
        return 0, []
    fields = [s["field"] for s in schema]
    tf = [s["field"] for s in schema if "varchar" in s["type"].lower() or "text" in s["type"].lower()]
    so = order_field if order_field in fields else fields[0]
    sd = "DESC" if order_dir.upper() == "DESC" else "ASC"
    pa = []
    has_del = any(s["field"] == "_deleted" for s in schema)
    conds = []
    if hide_deleted and has_del:
        conds.append("IFNULL(\"_deleted\",0) NOT IN (1,2)")
    if filters and isinstance(filters, dict):
        for fld, vals in filters.items():
            if fld in fields and vals and isinstance(vals, list) and len(vals):
                phs = ", ".join(["?"] * len(vals))
                conds.append(f"\"{fld}\" IN ({phs})")
                pa.extend(vals)
    if search:
        lc = [f"\"{f}\" LIKE ?" for f in tf]
        pa.extend([f"%{search}%" for _ in tf])
        conds.append("(" + " OR ".join(lc) + ")")
    ws = " WHERE " + " AND ".join(conds) if conds else ""
    cr = query_one(f"SELECT COUNT(*) AS cnt FROM \"{tn}\"{ws}", pa)
    total = cr["cnt"] if cr else 0
    if per_page == -1:
        rows = query(f"SELECT * FROM \"{tn}\"{ws} ORDER BY \"{so}\" {sd}", pa)
    else:
        rows = query(f"SELECT * FROM \"{tn}\"{ws} ORDER BY \"{so}\" {sd} LIMIT ? OFFSET ?", pa + [per_page, offset])
    return total, rows


# ── 表结构变更 ───────────────────────────────────────

def rename_table(old_name, new_name):
    query_one("ALTER TABLE \"" + old_name + "\" RENAME TO \"" + new_name + "\"")
    comment = _meta_get(f"comment:{old_name}")
    if comment:
        _meta_set(f"comment:{new_name}", comment)
        _meta_del(f"comment:{old_name}")
    return True


def drop_table(tn):
    query_one("DROP TABLE IF EXISTS \"" + tn + "\"")
    _meta_del(f"comment:{tn}")
    return True


def update_cell(tn, row_id, field, value):
    pk = get_pk_column(tn) or "id"
    execute("UPDATE \"" + tn + "\" SET \"" + field + "\"=? WHERE \"" + pk + "\"=?", (value, row_id))
    return True


def rename_column(tn, old_name, new_name):
    schema = get_schema(tn)
    col_names = [s["field"] for s in schema]
    if old_name not in col_names:
        raise ValueError(f"字段 {old_name} 不存在")
    if new_name in col_names:
        raise ValueError(f"字段 '{new_name}' 已存在，无法重命名")
    execute("ALTER TABLE \"" + tn + "\" RENAME COLUMN \"" + old_name + "\" TO \"" + new_name + "\"")


# ── 建表 ─────────────────────────────────────────────

def _safe_colname(name):
    if not name:
        return "col"
    s = str(name).strip()
    safe = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', '_', s).strip("_")
    if not safe or safe[0].isdigit():
        safe = "col_" + safe
    kw = {"id", "key", "index", "order", "group", "select", "from", "where", "table", "column", "date", "desc", "asc", "delete", "update", "insert", "drop", "alter", "add", "primary", "unique", "foreign", "check", "default"}
    if safe.lower() in kw:
        safe += "_"
    return safe


def _infer_type(values):
    nv = [v for v in values if v is not None and str(v).strip() != ""]
    if not nv: return "TEXT"
    ai = True; af = True
    for v in nv:
        s = str(v).strip()
        try: int(s)
        except: ai = False
        try: float(s)
        except: af = False
    if ai:
        for v in nv:
            try:
                if abs(int(v)) > 2147483647: return "BIGINT"
            except: pass
        return "INT"
    if af: return "DOUBLE"
    return "TEXT"


def create_empty_table(tn, columns=None, comment=""):
    safe_name = _safe_colname(tn)
    if not safe_name: return False, "无效的表名"
    existing = {t["name"] for t in get_tables()}
    if safe_name in existing: return False, f"表 `{safe_name}` 已存在"
    col_defs = []
    if columns:
        for col in columns:
            col_name = col.get("name", "").strip()
            col_type = col.get("type", "VARCHAR(255)").strip()
            if col_name and col_name.lower() != "id":
                safe_cn = _safe_colname(col_name)
                col_defs.append(f"\"{safe_cn}\" {col_type}")
    cols_sql = ", " + ", ".join(col_defs) if col_defs else ""
    sql = f'CREATE TABLE "{safe_name}" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT{cols_sql})'
    try:
        execute(sql)
    except Exception as e:
        return False, f"建表失败: {e}"
    if comment:
        set_table_comment(safe_name, comment)
    return True, f"表 `{safe_name}` 创建成功" + (f"，已添加 {len(col_defs)} 个字段" if col_defs else "")


def create_table_from_data(headers, rows, tn):
    if not headers or not rows: return False, "表头或数据为空"
    sh = [_safe_colname(h) for h in headers]
    cd = list(zip(*rows))
    cd2 = []
    for i, cn in enumerate(sh):
        ct = _infer_type(cd[i] if i < len(cd) else [])
        cd2.append(f"\"{cn}\" {ct}")
    try:
        execute(f'CREATE TABLE "{tn}" ("id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, {", ".join(cd2)})')
    except Exception as e:
        return False, f"建表失败: {e}"
    ph = ", ".join(["?"] * len(sh))
    fl = ", ".join([f"\"{h}\"" for h in sh])
    conn = _get_conn()
    try:
        cur = conn.cursor()
        for row in rows:
            cr = [None if v is None or (isinstance(v, str) and v.strip() == "") else v for v in row]
            cur.execute(f"INSERT INTO \"{tn}\" ({fl}) VALUES ({ph})", cr)
        conn.commit()
        return True, f"表 `{tn}` 建表成功，已导入 {len(rows)} 条记录"
    except Exception as e:
        conn.rollback()
        try: execute(f"DROP TABLE IF EXISTS \"{tn}\"")
        except: pass
        return False, f"导入失败: {e}"
    finally:
        conn.close()


# ── 数据库整体导出/导入 ─────────────────────────────

def get_create_sql(tn):
    r = query_one("SELECT \"sql\" FROM \"sqlite_master\" WHERE \"type\"='table' AND \"name\"=?", (tn,))
    return r["sql"] if r else None


def export_all_tables():
    tables = get_tables()
    result = []
    for t in tables:
        tn = t["name"]
        create_sql = get_create_sql(tn)
        if not create_sql: continue
        pk = get_pk_column(tn) or "id"
        rows = query(f"SELECT * FROM \"{tn}\" ORDER BY \"{pk}\"")
        serialized = []
        for row in rows:
            sr = {}
            for k, v in row.items():
                if isinstance(v, (datetime.datetime, datetime.date)):
                    sr[k] = v.isoformat()
                elif isinstance(v, bytes):
                    sr[k] = str(v)
                elif v is None or isinstance(v, (str, int, float, bool)):
                    sr[k] = v
                else:
                    sr[k] = str(v)
            serialized.append(sr)
        result.append({"name": tn, "create_sql": create_sql, "rows": serialized})
    return result


def import_tables(table_list, drop_existing=True):
    ok = 0; fail = 0; errors = []
    for td in table_list:
        tn = td["name"]; create_sql = td["create_sql"]; rows = td.get("rows", [])
        try:
            if drop_existing:
                existing = get_schema(tn)
                if existing: execute(f"DROP TABLE IF EXISTS \"{tn}\"")
            execute(create_sql)
            if rows:
                schema = get_schema(tn)
                fields = [s["field"] for s in schema if s["field"] != "id"]
                if fields:
                    ph = ", ".join(["?"] * len(fields))
                    fl = ", ".join([f"\"{f}\"" for f in fields])
                    for row in rows:
                        vals = [row.get(f) for f in fields]
                        execute(f"INSERT INTO \"{tn}\" ({fl}) VALUES ({ph})", vals)
            ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"{tn}: {e}")
    return ok, fail, errors

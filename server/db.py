"""
MySQL 数据库操作工具
"""
import re, pymysql
from config import DB_CONFIG


def get_conn():
    return pymysql.connect(host=DB_CONFIG["host"], port=DB_CONFIG["port"],
        user=DB_CONFIG["user"], password=DB_CONFIG["password"],
        database=DB_CONFIG["database"], charset=DB_CONFIG["charset"],
        cursorclass=pymysql.cursors.DictCursor)


def query(sql, params=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ()); return cur.fetchall()
    finally: conn.close()


def query_one(sql, params=None):
    rows = query(sql, params); return rows[0] if rows else None


def execute(sql, params=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            a = cur.execute(sql, params or ()); conn.commit(); return a
    finally: conn.close()


def get_tables():
    return query("SELECT TABLE_NAME AS name, TABLE_COMMENT AS comment FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME", (DB_CONFIG["database"],))


def get_schema(tn):
    return query("SELECT COLUMN_NAME AS field, COLUMN_TYPE AS type, IS_NULLABLE AS nullable, COLUMN_DEFAULT AS `default`, COLUMN_COMMENT AS comment FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION", (DB_CONFIG["database"], tn))


def get_pk_column(tn):
    r = query_one("SELECT COLUMN_NAME AS field FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_KEY='PRI' LIMIT 1", (DB_CONFIG["database"], tn))
    return r["field"] if r else None


def get_page(tn, page=1, per_page=50, search="", order_field=None, order_dir="asc", hide_deleted=False):
    offset = (page-1)*per_page; schema = get_schema(tn)
    if not schema: return 0, []
    fields = [s["field"] for s in schema]; tf = [s["field"] for s in schema if "varchar" in s["type"].lower() or "text" in s["type"].lower()]
    so = order_field if order_field in fields else fields[0]; sd = "DESC" if order_dir.upper()=="DESC" else "ASC"
    ws = ""; pa = []
    has_del = any(s["field"] == "_deleted" for s in schema)
    if hide_deleted and has_del:
        ws = " WHERE IFNULL(`_deleted`,0) != 1"
    if search:
        lc = [f"`{f}` LIKE %s" for f in tf]; pa = [f"%{search}%" for _ in tf]
        ws = " WHERE "+" OR ".join(lc)
    cr = query_one(f"SELECT COUNT(*) AS cnt FROM `{tn}`{ws}", pa); total = cr["cnt"] if cr else 0
    rows = query(f"SELECT * FROM `{tn}`{ws} ORDER BY `{so}` {sd} LIMIT %s OFFSET %s", pa+[per_page, offset])
    return total, rows


def rename_table(old_name, new_name):
    execute(f"RENAME TABLE `{old_name}` TO `{new_name}`"); return True


def drop_table(tn):
    execute(f"DROP TABLE IF EXISTS `{tn}`"); return True


def update_cell(tn, row_id, field, value):
    pk = get_pk_column(tn) or "id"
    execute(f"UPDATE `{tn}` SET `{field}`=%s WHERE `{pk}`=%s", (value, row_id))
    return True


def rename_column(tn, old_name, new_name):
    schema = get_schema(tn); col_type = None
    for s in schema:
        if s["field"] == old_name: col_type = s["type"]; break
    if not col_type: raise ValueError(f"字段 {old_name} 不存在")
    nullable = "NULL" if any(s.get("nullable")=="YES" for s in schema if s["field"]==old_name) else "NOT NULL"
    default = ""
    for s in schema:
        if s["field"] == old_name and s.get("default") is not None:
            d = str(s["default"])
            if d.isdigit(): default = f" DEFAULT {d}"
            elif d.upper() == "NULL": default = " DEFAULT NULL"
            else: default = f" DEFAULT '{d}'"
    execute(f"ALTER TABLE `{tn}` CHANGE COLUMN `{old_name}` `{new_name}` {col_type} {nullable}{default}")


def sync_related(src_tn, row_id, field, value, key_field):
    """
    更新源表一个字段后，检查其他表同 key 值同名字段，自动同步。
    返回: (synced_count, details)
    """
    pk = get_pk_column(src_tn) or "id"
    row = query_one(f"SELECT `{key_field}` AS kv FROM `{src_tn}` WHERE `{pk}`=%s", (row_id,))
    if not row or row["kv"] is None: return 0, []
    key_val = row["kv"]
    all_tables = get_tables()
    synced = []
    for t in all_tables:
        tname = t["name"]
        if tname == src_tn: continue
        tfields = [s["field"] for s in get_schema(tname)]
        if key_field not in tfields or field not in tfields: continue
        aff = execute(f"UPDATE `{tname}` SET `{field}`=%s WHERE `{key_field}`=%s", (value, key_val))
        if aff > 0:
            synced.append({"table": tname, "rows": aff})
    return len(synced), synced


def _safe_colname(name):
    if not name: return "col"
    s = str(name).strip(); safe = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', '_', s).strip("_")
    if not safe or safe[0].isdigit(): safe = "col_"+safe
    kw = {"id","key","index","order","group","select","from","where","table","column","date","desc","asc","delete","update","insert","drop","alter","add","primary","unique","foreign","check","default"}
    if safe.lower() in kw: safe += "_"
    return safe


def _infer_type(values):
    nv = [v for v in values if v is not None and str(v).strip()!=""]
    if not nv: return "TEXT"
    ai=af=True
    for v in nv:
        s=str(v).strip()
        try: int(s)
        except: ai=False
        try: float(s)
        except: af=False
    if ai:
        for v in nv:
            try:
                if abs(int(v))>2147483647: return "BIGINT"
            except: pass
        return "INT"
    if af: return "DOUBLE"
    return "TEXT"


def create_table_from_data(headers, rows, tn):
    if not headers or not rows: return False, "表头或数据为空"
    sh = [_safe_colname(h) for h in headers]
    cd = list(zip(*rows))
    cd2 = []
    for i, cn in enumerate(sh):
        ct = _infer_type(cd[i] if i<len(cd) else []); cd2.append(f"  `{cn}` {ct}")
    try: execute(f"CREATE TABLE `{tn}` (`id` INT NOT NULL AUTO_INCREMENT, {', '.join(cd2)}, PRIMARY KEY (`id`)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
    except Exception as e: return False, f"建表失败: {e}"
    ph = ", ".join(["%s"]*len(sh)); fl = ", ".join([f"`{h}`" for h in sh])
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for row in rows:
                cr = [None if v is None or (isinstance(v,str) and v.strip()=="") else v for v in row]
                cur.execute(f"INSERT INTO `{tn}` ({fl}) VALUES ({ph})", cr)
        conn.commit(); return True, f"表 `{tn}` 建表成功，已导入 {len(rows)} 条记录"
    except Exception as e:
        conn.rollback()
        try: execute(f"DROP TABLE IF EXISTS `{tn}`")
        except: pass
        return False, f"导入失败: {e}"
    finally: conn.close()

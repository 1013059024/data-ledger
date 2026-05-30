"""
MySQL 数据库操作工具
"""
import re, datetime, pymysql
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


def distinct_values(tn, field, search="", filters=None):
    """获取某列的去重值，支持搜索过滤和级联筛选"""
    schema = get_schema(tn)
    if not any(s["field"] == field for s in schema):
        return []
    conds = []; pa = []
    has_del = any(s["field"] == "_deleted" for s in schema)
    if has_del:
        conds.append("IFNULL(`_deleted`,0) NOT IN (1,2)")
    # 级联筛选：排除自身字段，用其他字段的筛选值做条件
    if filters and isinstance(filters, dict):
        for fld, vals in filters.items():
            if fld != field and fld in [s["field"] for s in schema] and vals and isinstance(vals, list) and len(vals):
                phs = ", ".join(["%s"]*len(vals))
                conds.append(f"`{fld}` IN ({phs})")
                pa.extend(vals)
    if search:
        conds.append(f"`{field}` LIKE %s")
        pa.append(f"%{search}%")
    ws = " WHERE " + " AND ".join(conds) if conds else ""
    rows = query(f"SELECT `{field}` AS v, COUNT(*) AS c FROM `{tn}`{ws} GROUP BY `{field}` ORDER BY `{field}`", pa)
    return [{"value": r["v"], "count": r["c"]} for r in rows if r["v"] is not None]


def get_page(tn, page=1, per_page=50, search="", order_field=None, order_dir="asc", hide_deleted=False, filters=None):
    offset = (page-1)*per_page; schema = get_schema(tn)
    if not schema: return 0, []
    fields = [s["field"] for s in schema]; tf = [s["field"] for s in schema if "varchar" in s["type"].lower() or "text" in s["type"].lower()]
    so = order_field if order_field in fields else fields[0]; sd = "DESC" if order_dir.upper()=="DESC" else "ASC"
    ws = ""; pa = []
    has_del = any(s["field"] == "_deleted" for s in schema)
    # 筛选条件
    conds = []
    if hide_deleted and has_del:
        conds.append("IFNULL(`_deleted`,0) NOT IN (1,2)")
    if filters and isinstance(filters, dict):
        for fld, vals in filters.items():
            if fld in fields and vals and isinstance(vals, list) and len(vals):
                phs = ", ".join(["%s"]*len(vals))
                conds.append(f"`{fld}` IN ({phs})")
                pa.extend(vals)
    if search:
        lc = [f"`{f}` LIKE %s" for f in tf]; pa.extend([f"%{search}%" for _ in tf])
        conds.append("("+" OR ".join(lc)+")")
    if conds:
        ws = " WHERE " + " AND ".join(conds)
    cr = query_one(f"SELECT COUNT(*) AS cnt FROM `{tn}`{ws}", pa); total = cr["cnt"] if cr else 0
    if per_page == -1:
        rows = query(f"SELECT * FROM `{tn}`{ws} ORDER BY `{so}` {sd}", pa)
    else:
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
    # 检查新名字是否已存在（避免 MySQL Duplicate column name 错误）
    for s in schema:
        if s["field"] == new_name:
            raise ValueError(f"字段 '{new_name}' 已存在，无法重命名")
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


def create_empty_table(tn, columns=None, comment=""):
    """创建一个空表，可指定字段列表
    
    columns: [{"name": "...", "type": "VARCHAR(255)"}, ...]
    """
    safe_name = _safe_colname(tn)
    if not safe_name:
        return False, "无效的表名"
    # 检查重名
    existing = {t["name"] for t in get_tables()}
    if safe_name in existing:
        return False, f"表 `{safe_name}` 已存在"
    
    # 构建字段定义
    col_defs = []
    if columns:
        for col in columns:
            col_name = col.get("name", "").strip()
            col_type = col.get("type", "VARCHAR(255)").strip()
            if col_name and col_name.lower() != "id":
                safe_cn = _safe_colname(col_name)
                col_defs.append(f"  `{safe_cn}` {col_type} NULL")
    cols_sql = ", " + ", ".join(col_defs) if col_defs else ""
    
    sql = f"CREATE TABLE `{safe_name}` (`id` INT NOT NULL AUTO_INCREMENT{cols_sql}, PRIMARY KEY (`id`)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    execute(sql)
    if comment:
        execute(f"ALTER TABLE `{safe_name}` COMMENT = %s", (comment,))
    return True, f"表 `{safe_name}` 创建成功" + (f"，已添加 {len(col_defs)} 个字段" if col_defs else "")


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


# ── 数据库整体导出/导入 ─────────────────────────────

def get_create_sql(tn):
    """获取 CREATE TABLE 语句"""
    r = query_one(f"SHOW CREATE TABLE `{tn}`")
    return r.get("Create Table") if r else None


def export_all_tables():
    """导出所有表的结构+数据+配置，返回可 JSON 序列化的 dict"""
    tables = get_tables()
    result = []
    for t in tables:
        tn = t["name"]
        create_sql = get_create_sql(tn)
        if not create_sql:
            continue
        pk = get_pk_column(tn) or "id"
        rows = query(f"SELECT * FROM `{tn}` ORDER BY `{pk}`")
        # datetime 转字符串
        serialized = []
        for row in rows:
            sr = {}
            for k, v in row.items():
                if isinstance(v, (datetime.datetime, datetime.date)):
                    sr[k] = v.isoformat()
                elif v is None or isinstance(v, (str, int, float, bool)):
                    sr[k] = v
                else:
                    sr[k] = str(v)
            serialized.append(sr)
        result.append({
            "name": tn,
            "create_sql": create_sql,
            "rows": serialized,
        })
    return result


def import_tables(table_list, drop_existing=True):
    """从 export_all_tables 的输出恢复表。
    返回: (ok_count, fail_count, errors)
    """
    ok = 0
    fail = 0
    errors = []
    for td in table_list:
        tn = td["name"]
        create_sql = td["create_sql"]
        rows = td.get("rows", [])
        try:
            if drop_existing:
                # 检查表是否存在
                existing = get_schema(tn)
                if existing:
                    execute(f"DROP TABLE IF EXISTS `{tn}`")
            # 重建表
            execute(create_sql)
            # 逐批插入数据
            if rows:
                # 获取新表的字段（排除 id）
                schema = get_schema(tn)
                fields = [s["field"] for s in schema if s["field"] != "id"]
                if fields:
                    ph = ", ".join(["%s"] * len(fields))
                    fl = ", ".join([f"`{f}`" for f in fields])
                    for row in rows:
                        vals = [row.get(f) for f in fields]
                        execute(f"INSERT INTO `{tn}` ({fl}) VALUES ({ph})", vals)
            ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"{tn}: {e}")
    return ok, fail, errors

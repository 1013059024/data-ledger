"""
农村公路台账 — Web 表格浏览服务
"""
import os, json, uuid, tempfile, re, datetime
from flask import Flask, jsonify, render_template, request, send_file
from config import FLASK_SECRET, DB_CONFIG
from db import get_tables, get_schema, get_page, get_pk_column, create_table_from_data, drop_table, rename_table, update_cell, rename_column, query_one, query, execute

app = Flask(__name__)
app.secret_key = FLASK_SECRET
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
_upload_cache = {}
_MAP_FILE = os.path.join(os.path.dirname(__file__), "_sync_mappings.json")
_GROUP_FILE = os.path.join(os.path.dirname(__file__), "_table_groups.json")


def _load_m():
    if not os.path.exists(_MAP_FILE): return []
    try:
        with open(_MAP_FILE, encoding="utf-8") as f: return json.load(f)
    except: return []

def _save_m(m):
    with open(_MAP_FILE, "w", encoding="utf-8") as f: json.dump(m, f, ensure_ascii=False, indent=2)


def _load_g():
    if not os.path.exists(_GROUP_FILE): return []
    try:
        with open(_GROUP_FILE, encoding="utf-8") as f: return json.load(f)
    except: return []

def _save_g(g):
    with open(_GROUP_FILE, "w", encoding="utf-8") as f: json.dump(g, f, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tables")
def api_tables():
    return jsonify({"code": 0, "data": get_tables()})

# ========== 表分组 ==========

@app.route("/api/table-groups", methods=["GET"])
def api_get_groups():
    return jsonify({"code": 0, "data": _load_g()})

@app.route("/api/table-groups", methods=["POST"])
def api_save_groups():
    d = request.get_json()
    if not d or "groups" not in d: return jsonify({"code": 1, "msg": "参数为空"})
    _save_g(d["groups"])
    return jsonify({"code": 0, "msg": f"已保存 {len(d['groups'])} 个分组"})


@app.route("/api/table/<table_name>", methods=["DELETE"])
def api_delete_table(table_name):
    try: drop_table(table_name); return jsonify({"code": 0, "msg": "已删除"})
    except Exception as e: return jsonify({"code": 1, "msg": f"删除失败: {str(e)}"})


@app.route("/api/table/<table_name>", methods=["PUT"])
def api_rename_table(table_name):
    d = request.get_json(); nn = (d or {}).get("new_name","")
    if not nn.strip(): return jsonify({"code": 1, "msg": "新表名为空"})
    nn = nn.strip()
    if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', nn):
        return jsonify({"code": 1, "msg": "表名只允许字母、数字、下划线和中文"})
    if len(nn) > 64: return jsonify({"code": 1, "msg": "表名不能超过64个字符"})
    if nn == table_name: return jsonify({"code": 0, "msg": "未改变"})
    try: rename_table(table_name, nn); db_execute(f"ALTER TABLE `{nn}` COMMENT = %s", (nn,)); return jsonify({"code": 0, "msg": f"已重命名为 `{nn}`"})
    except Exception as e: return jsonify({"code": 1, "msg": f"重命名失败: {str(e)}"})


@app.route("/api/table/<table_name>/column", methods=["PUT"])
def api_rename_column(table_name):
    d = request.get_json(); old = (d or {}).get("old",""); nn = (d or {}).get("new","")
    if not old or not nn: return jsonify({"code": 1, "msg": "参数不全"})
    if nn.lower() == "id": return jsonify({"code": 1, "msg": "id 字段不能修改"})
    try: rename_column(table_name, old, nn); return jsonify({"code": 0, "msg": "字段已重命名"})
    except Exception as e: return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/table/<table_name>/row", methods=["POST"])
def api_add_row(table_name):
    """插入一条空记录"""
    pk = get_pk_column(table_name)
    schema = get_schema(table_name)
    fields = [s["field"] for s in schema if s["field"] != pk and s["field"] != "_deleted"]
    if not fields: return jsonify({"code": 1, "msg": "无可用字段"})
    cols = ", ".join([f"`{f}`" for f in fields])
    try:
        from db import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"INSERT INTO `{table_name}` ({cols}) VALUES ({', '.join(['NULL']*len(fields))})")
                conn.commit()
                new_id = cur.lastrowid
            return jsonify({"code": 0, "msg": "已添加", "id": new_id})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"code": 1, "msg": f"添加失败: {e}"})

@app.route("/api/table/<table_name>/row/<int:row_id>", methods=["DELETE"])
def api_delete_row(table_name, row_id):
    """删除指定行（级联删除关联表同关键字段值的记录）"""
    try:
        pk = get_pk_column(table_name) or "id"
        kv_map = {}
        for mp in _load_m():
            if table_name not in (mp["st"], mp["tt"]): continue
            kf = mp["kf"]
            if kf not in kv_map:
                r = query_one(f"SELECT `{kf}` AS v FROM `{table_name}` WHERE `{pk}`=%s", (row_id,))
                if r: kv_map[kf] = r["v"]
        execute(f"DELETE FROM `{table_name}` WHERE `{pk}`=%s", (row_id,))
        del_cnt = 0
        for mp in _load_m():
            if table_name not in (mp["st"], mp["tt"]): continue
            kf = mp["kf"]; kv = kv_map.get(kf)
            if kv is None: continue
            other = mp["tt"] if table_name == mp["st"] else mp["st"]
            a = execute(f"DELETE FROM `{other}` WHERE `{kf}`=%s", (kv,))
            if a: del_cnt += a
        msg = "已删除"
        if del_cnt: msg += f"（级联删除 {del_cnt} 条关联记录）"
        return jsonify({"code": 0, "msg": msg})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"删除失败: {e}"})

@app.route("/api/table/<table_name>/row/<int:row_id>/hide", methods=["POST"])
def api_hide_row(table_name, row_id):
    """隐藏行：关键字段为空则硬删除，否则软删除"""
    try:
        kfs = set()
        for mp in _load_m():
            if table_name in (mp["st"], mp["tt"]):
                kfs.add(mp["kf"])
        should_del = False
        for kf in kfs:
            row = query_one(f"SELECT `{kf}` FROM `{table_name}` WHERE `id`=%s", (row_id,))
            if row and (row[kf] is None or str(row[kf]).strip() == ""):
                should_del = True; break
        if should_del:
            execute(f"DELETE FROM `{table_name}` WHERE `id`=%s", (row_id,))
            return jsonify({"code": 0, "msg": "已删除（关键字段为空）"})
        schema = get_schema(table_name)
        if not any(s["field"] == "_deleted" for s in schema):
            execute(f"ALTER TABLE `{table_name}` ADD COLUMN `_deleted` TINYINT DEFAULT 0")
        execute(f"UPDATE `{table_name}` SET `_deleted`=1 WHERE `id`=%s", (row_id,))
        return jsonify({"code": 0, "msg": "已隐藏"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"隐藏失败: {e}"})

@app.route("/api/table/<table_name>/column", methods=["POST"])
def api_add_column(table_name):
    """插入空列（after 指定在某列之后）"""
    d = request.get_json(); name = (d or {}).get("name","").strip()
    if not name: return jsonify({"code": 1, "msg": "列名不能为空"})
    if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', name):
        return jsonify({"code": 1, "msg": "列名只允许字母、数字、下划线和中文"})
    after = (d or {}).get("after","")
    try:
        sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{name}` VARCHAR(255) NULL"
        if after:
            sql += f" AFTER `{after}`"
        execute(sql)
        return jsonify({"code": 0, "msg": f"列 `{name}` 已添加"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"添加失败: {e}"})

@app.route("/api/table/<table_name>/column/<column_name>/type", methods=["PATCH"])
def api_set_column_type(table_name, column_name):
    """修改列数据类型"""
    d = request.get_json(); new_type = (d or {}).get("type","").strip()
    if not new_type: return jsonify({"code": 1, "msg": "类型不能为空"})
    if column_name.lower() == "id": return jsonify({"code": 1, "msg": "id 列不允许修改"})
    try:
        execute(f"ALTER TABLE `{table_name}` MODIFY COLUMN `{column_name}` {new_type}")
        return jsonify({"code": 0, "msg": f"已修改为 {new_type}"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"修改失败: {e}"})

@app.route("/api/table/<table_name>/column/<column_name>", methods=["DELETE"])
def api_delete_column(table_name, column_name):
    """删除指定列"""
    if column_name.lower() == "id": return jsonify({"code": 1, "msg": "id 列不能删除"})
    try:
        execute(f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`")
        return jsonify({"code": 0, "msg": f"列 `{column_name}` 已删除"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"删除失败: {e}"})

@app.route("/api/table/<table_name>/lookup")
def api_lookup(table_name):
    """按字段值查找同表已有记录（用于自动补全）"""
    field = request.args.get("field"); value = request.args.get("value"); exclude = request.args.get("exclude", 0, type=int)
    if not field or value is None: return jsonify({"code": 1, "msg": "参数不全"})
    pk = get_pk_column(table_name) or "id"
    rows = query(f"SELECT * FROM `{table_name}` WHERE `{field}`=%s AND `{pk}`!=%s LIMIT 1", (value, exclude))
    if not rows: return jsonify({"code": 1, "msg": "未找到匹配"})
    row = rows[0]
    if "_deleted" in row and row["_deleted"] == 1: return jsonify({"code": 1, "msg": "未找到匹配"})
    return jsonify({"code": 0, "data": _serialize_rows([row])[0]})

@app.route("/api/table/<table_name>/record/<int:row_id>")
def api_view_record(table_name, row_id):
    """查看数据库记录（含关联表信息），分组返回"""
    pk = get_pk_column(table_name) or "id"
    curr = query_one(f"SELECT * FROM `{table_name}` WHERE `{pk}`=%s", (row_id,))
    if not curr: return jsonify({"code": 1, "msg": "记录不存在"})
    groups = []
    cur_f = {}
    for k, v in curr.items():
        if k in (pk, "_deleted"): continue
        if isinstance(v, (datetime.date, datetime.datetime)): v = v.isoformat()
        cur_f[k] = v
    groups.append({"table": table_name, "id": curr[pk], "fields": cur_f})
    for mp in _load_m():
        if table_name not in (mp["st"], mp["tt"]): continue
        kf = mp["kf"]; kv = curr.get(kf)
        if kv is None: continue
        other = mp["tt"] if table_name == mp["st"] else mp["st"]
        opk = get_pk_column(other) or "id"
        rows = query(f"SELECT * FROM `{other}` WHERE `{kf}`=%s", (kv,))
        for row in rows:
            if "_deleted" in row and row["_deleted"] == 1: continue
            of = {}
            for k, v in row.items():
                if k in (opk, "_deleted"): continue
                if isinstance(v, (datetime.date, datetime.datetime)): v = v.isoformat()
                of[k] = v
            groups.append({"table": other, "id": row[opk], "fields": of})
    return jsonify({"code": 0, "data": {"groups": groups}})

@app.route("/api/table/batch-update", methods=["POST"])
def api_batch_update():
    """批量更新字段值"""
    d = request.get_json()
    updates = d.get("updates", [])
    if not updates: return jsonify({"code": 1, "msg": "无更新"})
    ok = 0; fails = []
    for u in updates:
        tbl, rid, fld, val = u.get("table"), u.get("id"), u.get("field"), u.get("value")
        if not tbl or not rid or not fld: fails.append({"msg": "参数不全", "update": u}); continue
        try:
            execute(f"UPDATE `{tbl}` SET `{fld}`=%s WHERE `id`=%s", (val, rid))
            ok += 1
        except Exception as e:
            fails.append({"msg": str(e), "update": u})
    return jsonify({"code": 0, "msg": f"成功 {ok} 条" + (f", 失败 {len(fails)} 条" if fails else ""), "fails": fails})

@app.route("/api/table/<table_name>/export")
def api_export_table(table_name):
    """导出表数据为 Excel"""
    try:
        import openpyxl; from openpyxl.styles import Font; from io import BytesIO
        schema = get_schema(table_name)
        if not schema: return jsonify({"code": 1, "msg": "表不存在"})
        pk = get_pk_column(table_name) or "id"
        fields = [s["field"] for s in schema if s["field"] not in (pk, "_deleted")]
        rows = query(f"SELECT * FROM `{table_name}` ORDER BY `{pk}`")
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = (table_name or "sheet")[:31]
        hf = Font(bold=True)
        for ci, f in enumerate(fields, 1): ws.cell(1, ci, f).font = hf
        ri = 2
        for row in rows:
            if "_deleted" in row and row["_deleted"] == 1: continue
            for ci, f in enumerate(fields, 1): ws.cell(ri, ci, row.get(f))
            ri += 1
        for col in ws.columns:
            ml = max((len(str(c.value or "")) for c in col), default=0)
            ws.column_dimensions[col[0].column_letter].width = min(ml + 2, 50)
        buf = BytesIO(); wb.save(buf); buf.seek(0)
        return send_file(buf, download_name=f"{table_name}.xlsx", as_attachment=True)
    except Exception as e:
        return jsonify({"code": 1, "msg": f"导出失败: {e}"})

@app.route("/api/table/<table_name>", methods=["PATCH"])
def api_update_cell(table_name):
    d = request.get_json()
    if not d: return jsonify({"code": 1, "msg": "请求为空"})
    row_id, field, value = d.get("id"), d.get("field"), d.get("value")
    if row_id is None or not field: return jsonify({"code": 1, "msg": "参数不全"})
    # 关键字段唯一性检查
    if value is not None and str(value).strip():
        for mp in _load_m():
            if table_name in (mp["st"], mp["tt"]) and mp["kf"] == field:
                pk = get_pk_column(table_name) or "id"
                has_del = any(s["field"] == "_deleted" for s in get_schema(table_name))
                del_cond = "AND (`_deleted` IS NULL OR `_deleted`!=1)" if has_del else ""
                cnt = query_one(f"SELECT COUNT(*) AS c FROM `{table_name}` WHERE `{field}`=%s AND `{pk}`!=%s {del_cond}", (value, row_id))
                if cnt and cnt["c"] > 0:
                    return jsonify({"code": 1, "msg": f"关键字段「{field}」值「{value}」已存在，不能重复"})
                break
    try:
        update_cell(table_name, row_id, field, value)
        msg = "已更新"
        # 检查映射同步
        for mp in _load_m():
            if table_name not in (mp["st"], mp["tt"]): continue
            kf = mp["kf"]; pairs = mp["ps"]
            kv_r = query_one(f"SELECT `{kf}` AS v FROM `{table_name}` WHERE `id`=%s", (row_id,))
            kv = kv_r["v"] if kv_r else None
            if kv is None: continue
            other = mp["tt"] if table_name == mp["st"] else mp["st"]
            tfs = [s["field"] for s in get_schema(other)]
            if kf not in tfs: continue
            for p in pairs:
                tf = None
                if table_name == mp["st"] and field == p["s"]: tf = p["t"]
                elif table_name == mp["tt"] and field == p["t"]: tf = p["s"]
                if tf and tf in tfs:
                    execute(f"UPDATE `{other}` SET `{tf}`=%s WHERE `{kf}`=%s", (value, kv))
                    msg += f"（同步至 {other}）"
        return jsonify({"code": 0, "msg": msg})
    except Exception as e: return jsonify({"code": 1, "msg": f"更新失败: {str(e)}"})


def db_execute(sql, params=None):
    from db import execute as _e
    try: _e(sql, params); return True
    except: return False


@app.route("/api/table/<table_name>")
def api_table(table_name):
    s = get_schema(table_name)
    if not s: return jsonify({"code": 1, "msg": f"表 {table_name} 不存在"})
    p = request.args.get("page", 1, type=int)
    total, rows = get_page(table_name, p, 50,
        request.args.get("search", "", type=str),
        request.args.get("order_field", default=None, type=str),
        request.args.get("order_dir", default="asc", type=str), hide_deleted=True)
    r = query_one("SELECT TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (DB_CONFIG["database"], table_name))
    comment = r["TABLE_COMMENT"] if r else ""
    s = [c for c in s if c["field"] != "_deleted"]
    rows = [{k:v for k,v in row.items() if k != "_deleted"} for row in rows]
    return jsonify({"code": 0, "data": {"name": table_name, "comment": comment, "schema": s,
        "pk": get_pk_column(table_name), "total": total, "page": p, "per_page": 50, "rows": _serialize_rows(rows)}})


# ========== 字段映射 API ==========

@app.route("/api/sync/mappings", methods=["GET"])
def api_get_mappings():
    return jsonify({"code": 0, "data": _load_m()})

@app.route("/api/sync/mappings", methods=["POST"])
def api_save_mappings():
    d = request.get_json()
    if not d or "mappings" not in d: return jsonify({"code": 1, "msg": "请求为空"})
    _save_m(d["mappings"])
    return jsonify({"code": 0, "msg": f"已保存 {len(d['mappings'])} 条映射"})

@app.route("/api/sync/schema/<table_name>")
def api_sync_schema(table_name):
    """返回指定表的非主键字段列表"""
    s = get_schema(table_name)
    pk = get_pk_column(table_name)
    fields = [{"field": c["field"], "type": c["type"]} for c in s if c["field"] != pk]
    return jsonify({"code": 0, "data": fields})

@app.route("/api/sync/verify", methods=["POST"])
def api_sync_verify():
    """核实两个表映射字段的数据是否一致"""
    d = request.get_json()
    st, tt, kf = d.get("source"), d.get("target"), d.get("key_field")
    ps = d.get("pairs", [])
    if not st or not tt or not kf or not ps:
        return jsonify({"code": 1, "msg": "参数不全"})
    # 只查必要的字段，避免全表扫描
    sf_set = {kf}; tf_set = {kf}
    for p in ps:
        if p.get("s"): sf_set.add(p["s"])
        if p.get("t"): tf_set.add(p["t"])
    src_cols = ', '.join('`'+f+'`' for f in sf_set)
    tgt_cols = ', '.join('`'+f+'`' for f in tf_set)
    try:
        src_has_del = any(s["field"] == "_deleted" for s in get_schema(st))
        tgt_has_del = any(s["field"] == "_deleted" for s in get_schema(tt))
        src_sql = f"SELECT {src_cols}" + (", `_deleted`" if src_has_del else "") + f" FROM `{st}` ORDER BY `{kf}`"
        tgt_sql = f"SELECT {tgt_cols}" + (", `_deleted`" if tgt_has_del else "") + f" FROM `{tt}` ORDER BY `{kf}`"
        src_rows = query(src_sql); tgt_rows = query(tgt_sql)
    except Exception as e:
        return jsonify({"code": 1, "msg": f"查询失败: {e}"})
    src_rows = [r for r in src_rows if r.get("_deleted", 0) != 1]
    tgt_rows = [r for r in tgt_rows if r.get("_deleted", 0) != 1]
    tgt_map = {}
    for row in tgt_rows:
        k = row.get(kf)
        if k is not None:
            tgt_map[k] = row
    src_keys = set(); errors = []; matched = 0; src_only = 0
    for srow in src_rows:
        sk = srow.get(kf)
        if sk is None: continue
        sk_str = str(sk).strip()
        if not sk_str: continue
        src_keys.add(sk_str)
        trow = tgt_map.get(sk)
        if trow is None:
            src_only += 1
            continue
        matched += 1
        for p in ps:
            sf, tf = p.get("s"), p.get("t")
            if not sf or not tf: continue
            sv, tv = srow.get(sf), trow.get(tf)
            if sv is None and tv is None: continue
            if sv is None or tv is None or str(sv).strip() != str(tv).strip():
                errors.append({"key": sk_str, "field_src": sf, "field_tgt": tf,
                    "val_src": str(sv) if sv is not None else "(空)",
                    "val_tgt": str(tv) if tv is not None else "(空)"})
    tgt_only = sum(1 for k in tgt_map if k not in src_keys)
    return jsonify({"code": 0, "data": {"total_src": len(src_rows), "total_tgt": len(tgt_rows),
        "matched": matched, "src_only": src_only, "tgt_only": tgt_only, "errors": errors}})

@app.route("/api/sync/auto-fill", methods=["POST"])
def api_auto_fill():
    """编辑关键字段后，从关联表拉取数据补全"""
    d = request.get_json(); tbl, kf, kv, rid = d.get("table"), d.get("key_field"), d.get("key_value"), d.get("row_id")
    if not tbl or not kf or kv is None: return jsonify({"code": 1, "msg": "参数不全"})
    fills = {}
    for mp in _load_m():
        if tbl not in (mp["st"], mp["tt"]) or mp["kf"] != kf: continue
        other = mp["tt"] if tbl == mp["st"] else mp["st"]
        pk = get_pk_column(other) or "id"
        rows = query(f"SELECT * FROM `{other}` WHERE `{kf}`=%s LIMIT 1", (kv,))
        if not rows: continue
        row = rows[0]
        if "_deleted" in row and row["_deleted"] == 1: continue
        for p in mp["ps"]:
            sf, tf = (p["t"], p["s"]) if tbl == mp["st"] else (p["s"], p["t"])
            if sf in row and row[sf] is not None:
                fills[tf] = row[sf]
        break
    if not fills: return jsonify({"code": 1, "msg": "未找到匹配"})
    return jsonify({"code": 0, "data": fills})

@app.route("/api/sync/backfill", methods=["POST"])
def api_sync_backfill():
    """补填：扫描表中的空映射字段，从关联表拉取补齐"""
    d = request.get_json(); tbl = d.get("table", "")
    if not tbl: return jsonify({"code": 1, "msg": "表名为空"})
    pk = get_pk_column(tbl) or "id"
    filled = 0; errors = []
    for mp in _load_m():
        if tbl not in (mp["st"], mp["tt"]): continue
        kf = mp["kf"]
        other = mp["tt"] if tbl == mp["st"] else mp["st"]
        try:
            rows = query(f"SELECT `id`,`{kf}` FROM `{tbl}` WHERE `{kf}` IS NOT NULL AND TRIM(`{kf}`)!=''")
        except: continue
        for row in rows:
            kv = str(row[kf]).strip()
            src_row = query_one(f"SELECT * FROM `{other}` WHERE `{kf}`=%s LIMIT 1", (kv,))
            if not src_row: continue
            if "_deleted" in src_row and src_row["_deleted"] == 1: continue
            af_vals = {}
            for p in mp["ps"]:
                sf, tf = (p["t"], p["s"]) if tbl == mp["st"] else (p["s"], p["t"])
                if sf in src_row and src_row[sf] is not None and str(src_row[sf]).strip():
                    af_vals[tf] = src_row[sf]
            if af_vals:
                sets = ", ".join([f"`{f}`=%s" for f in af_vals])
                try:
                    execute(f"UPDATE `{tbl}` SET {sets} WHERE `{kf}`=%s", list(af_vals.values()) + [kv])
                    filled += 1
                except Exception as e:
                    es = str(e)
                    # Data too long → 自动扩字段为 TEXT 后重试
                    if "Data too long" in es:
                        import re as re2
                        m = re2.search(r"column '(\w+)'", es)
                        if m:
                            try:
                                execute(f"ALTER TABLE `{tbl}` MODIFY COLUMN `{m.group(1)}` TEXT")
                                execute(f"UPDATE `{tbl}` SET {sets} WHERE `{kf}`=%s", list(af_vals.values()) + [kv])
                                filled += 1
                                continue
                            except: pass
                    errors.append(es)
    msg = f"补填完成：更新 {filled} 行"
    if errors:
        details = "; ".join(errors[:5])
        msg += f"，{len(errors)} 个错误（{details}）"
    return jsonify({"code": 0, "msg": msg, "filled": filled})

# ========== 剪贴板 ==========
_clipboard = None  # {table, key_field, fields: [...], rows: [[...], ...]}

@app.route("/api/clipboard/copy", methods=["POST"])
def api_clipboard_copy():
    d = request.get_json()
    if not d or "fields" not in d or "rows" not in d:
        return jsonify({"code": 1, "msg": "参数不全"})
    global _clipboard
    _clipboard = {
        "table": d.get("table", ""),
        "key_field": d.get("key_field", ""),
        "fields": d["fields"],
        "rows": d["rows"]
    }
    return jsonify({"code": 0, "msg": f"已复制 {len(d['rows'])} 行 {len(d['fields'])} 列"})

@app.route("/api/clipboard/paste", methods=["POST"])
def api_clipboard_paste():
    global _clipboard
    if not _clipboard: return jsonify({"code": 1, "msg": "剪贴板为空，请先复制"})
    d = request.get_json()
    tgt = d.get("target", "")
    if not tgt: return jsonify({"code": 1, "msg": "目标表名为空"})
    schema = get_schema(tgt)
    tgt_all_fields = [s["field"] for s in schema]
    pk = get_pk_column(tgt) or "id"
    src_fields = _clipboard["fields"]
    # 字段名称匹配（排除 id 自增主键）
    col_map = {}
    for sf in src_fields:
        if sf in tgt_all_fields and sf != pk:
            col_map[sf] = src_fields.index(sf)
    if not col_map: return jsonify({"code": 1, "msg": "源字段与目标表无匹配字段"})
    # 自动识别关键字段：优先用与目标表 PK 同名的字段
    kf = pk if pk in src_fields else list(col_map.keys())[0]
    # 读取目标表已有记录的关键值
    tgt_exists = {}
    if kf:
        try:
            for row in query(f"SELECT `id`,`{kf}` FROM `{tgt}` WHERE `{kf}` IS NOT NULL AND TRIM(`{kf}`)!=''"):
                tgt_exists[str(row[kf]).strip()] = row["id"]
        except: pass
    updated, inserted = 0, 0
    for crow in _clipboard["rows"]:
        kv = ""
        if kf in src_fields:
            ki = src_fields.index(kf)
            kv = str(crow[ki]).strip() if ki < len(crow) and crow[ki] is not None else ""
        tf_vals = {}
        for tf, ci in col_map.items():
            if ci < len(crow) and crow[ci] is not None and str(crow[ci]).strip():
                tf_vals[tf] = crow[ci]
        if kv and kv in tgt_exists:
            if not tf_vals: continue
            sets = ", ".join([f"`{f}`=%s" for f in tf_vals])
            try:
                execute(f"UPDATE `{tgt}` SET {sets} WHERE `{kf}`=%s", list(tf_vals.values()) + [kv])
                updated += 1
            except: pass
        else:
            all_cols = list(tf_vals.keys())
            all_vals = list(tf_vals.values())
            if kv and kf:
                all_cols.insert(0, kf)
                all_vals.insert(0, kv)
            if not all_cols: continue
            ph = ", ".join(["%s"] * len(all_cols))
            try:
                execute(f"INSERT INTO `{tgt}` (`{'`,`'.join(all_cols)}`) VALUES ({ph})", all_vals)
                inserted += 1
            except: pass
        # 粘贴后自动填充：利用已有字段映射从关联表拉取
        if kv and kf:
            for mp in _load_m():
                if tgt not in (mp["st"], mp["tt"]) or mp["kf"] != kf: continue
                other = mp["tt"] if tgt == mp["st"] else mp["st"]
                pk_o = get_pk_column(other) or "id"
                src_row = query_one(f"SELECT * FROM `{other}` WHERE `{kf}`=%s LIMIT 1", (kv,))
                if not src_row: continue
                if "_deleted" in src_row and src_row["_deleted"] == 1: continue
                af_vals = {}
                for p in mp["ps"]:
                    sf, tf = (p["t"], p["s"]) if tgt == mp["st"] else (p["s"], p["t"])
                    if sf in src_row and src_row[sf] is not None and str(src_row[sf]).strip():
                        af_vals[tf] = src_row[sf]
                if af_vals:
                    sets = ", ".join([f"`{f}`=%s" for f in af_vals])
                    try:
                        execute(f"UPDATE `{tgt}` SET {sets} WHERE `{kf}`=%s", list(af_vals.values()) + [kv])
                    except: pass
                break
    return jsonify({"code": 0, "msg": f"粘贴完成：更新 {updated} 行，新增 {inserted} 行",
        "updated": updated, "inserted": inserted})

@app.route("/api/clipboard/clear", methods=["POST"])
def api_clipboard_clear():
    global _clipboard
    _clipboard = None
    return jsonify({"code": 0, "msg": "剪贴板已清空"})

@app.route("/api/clipboard", methods=["GET"])
def api_clipboard_status():
    global _clipboard
    if not _clipboard:
        return jsonify({"code": 1, "msg": "空"})
    return jsonify({"code": 0, "data": {
        "table": _clipboard["table"],
        "rows": len(_clipboard["rows"]),
        "cols": len(_clipboard["fields"])
    }})


# ========== 上传 ==========

@app.route("/api/upload/parse", methods=["POST"])
def api_upload_parse():
    file = request.files.get("file")
    if not file or file.filename == "": return jsonify({"code": 1, "msg": "请选择文件"})
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".csv", ".xls", ".xlsx", ".et"): return jsonify({"code": 1, "msg": "仅支持 .csv/.xls/.xlsx/.et"})
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        file.save(tmp.name); tmp.close(); sid = uuid.uuid4().hex[:12]
        if ext == ".csv":
            h, r = _parse_csv(tmp.name)
            raw = [h] + r; dt = ""; hr = 1
            if len(raw) > 1:
                ne = [c for c in raw[0] if c is not None and str(c).strip()]
                if len(ne) <= 2 and ne and len(str(ne[0])) > 2 and len([c for c in raw[1] if c is not None and str(c).strip()]) > 2:
                    dt = str(ne[0]).strip(); hr = 2
            _upload_cache[sid] = {"path": tmp.name, "type": "csv", "filename": file.filename,
                "sheets": {"Sheet1": {"raw_rows": raw}}, "current_sheet": "Sheet1", "header_rows": hr}
            _recalc(sid); s = _upload_cache[sid]["sheets"]["Sheet1"]
            return jsonify({"code": 0, "data": {"session_id": sid, "sheets": ["Sheet1"],
                "filename": file.filename, "detected_title": dt,
                "headers": s["headers"], "total_rows": len(s["rows"]), "preview": s["rows"][:5], "header_rows": hr}})
        else:
            _upload_cache[sid] = {"path": tmp.name, "type": "excel", "filename": file.filename}
            ns, ra = _parse_excel_raw(tmp.name)
            dt = ""; hr = 1
            if ns and ra and len(ra[0]) > 1:
                ne = [c for c in ra[0][0] if c is not None and str(c).strip()]
                if len(ne) <= 2 and ne and len(str(ne[0])) > 2 and len([c for c in ra[0][1] if c is not None and str(c).strip()]) > 2:
                    dt = str(ne[0]).strip(); hr = 2
            _upload_cache[sid]["sheets"] = {n: {"raw_rows": r} for n, r in zip(ns, ra)}
            _upload_cache[sid]["current_sheet"] = ns[0]; _upload_cache[sid]["header_rows"] = hr
            _recalc(sid); s = _upload_cache[sid]["sheets"][ns[0]]
            return jsonify({"code": 0, "data": {"session_id": sid, "sheets": ns,
                "filename": file.filename, "detected_title": dt,
                "headers": s["headers"], "total_rows": len(s["rows"]), "preview": s["rows"][:5], "header_rows": hr}})
    except Exception as e:
        try: os.unlink(tmp.name)
        except: pass
        return jsonify({"code": 1, "msg": f"解析失败: {str(e)}"})


@app.route("/api/upload/select_sheet", methods=["POST"])
def api_upload_select_sheet():
    d = request.get_json(); sid, sn = d.get("session_id"), d.get("sheet","")
    if sid not in _upload_cache: return jsonify({"code": 1, "msg": "过期"})
    if sn not in _upload_cache[sid]["sheets"]: return jsonify({"code": 1, "msg": "Sheet不存在"})
    _upload_cache[sid]["current_sheet"] = sn; _recalc(sid)
    s = _upload_cache[sid]["sheets"][sn]
    return jsonify({"code": 0, "data": {"headers": s["headers"], "total_rows": len(s["rows"]), "preview": s["rows"][:5]}})


@app.route("/api/upload/set_header_rows", methods=["POST"])
def api_upload_set_header_rows():
    d = request.get_json(); sid, n = d.get("session_id"), d.get("header_rows", 1)
    if sid not in _upload_cache: return jsonify({"code": 1, "msg": "过期"})
    _upload_cache[sid]["header_rows"] = n; _recalc(sid)
    s = _upload_cache[sid]["sheets"][_upload_cache[sid]["current_sheet"]]
    return jsonify({"code": 0, "data": {"headers": s["headers"], "total_rows": len(s["rows"]), "preview": s["rows"][:5]}})


def _recalc(sid):
    c = _upload_cache[sid]; sn = c["current_sheet"]; raw = c["sheets"][sn]["raw_rows"]
    n = max(1, min(c["header_rows"], len(raw)))
    hrows = [list(r) for r in raw[:n]]; drows = raw[n:]
    ncols = max((len(r) for r in hrows), default=0)
    if n >= 1:
        row = hrows[0]; carry = ""
        for ci in range(ncols):
            if ci >= len(row): row.append(carry or None); continue
            v = row[ci]; sv = str(v).strip() if v is not None else ""
            if sv: carry = sv; continue
            row[ci] = carry or None
    for col in range(ncols):
        carry = ""
        for ri in range(n):
            if col >= len(hrows[ri]): hrows[ri].append(carry or None); continue
            v = hrows[ri][col]; sv = str(v).strip() if v is not None else ""
            if sv: carry = sv
            else: hrows[ri][col] = carry or None
    merged = []; seen = {}
    for col in range(ncols):
        parts = []; carry = ""
        for ri in range(n):
            v = hrows[ri][col] if col < len(hrows[ri]) else None
            sv = str(v).strip() if v is not None and str(v).strip() else ""
            if sv: carry = sv; parts.append(carry)
        nm = "_".join([p for i,p in enumerate(parts) if p and (i==0 or p!=parts[i-1])]) or f"col_{col+1}"
        merged.append(nm)
    for i in range(len(merged)):
        nm = merged[i]
        if nm in seen: seen[nm] += 1; merged[i] = f"{nm}_{seen[nm]}"
        else: seen[nm] = 0
    clean = []
    for row in drows:
        cr = [row[i] if i < len(row) else None for i in range(ncols)]
        if any(v is not None and str(v).strip()!="" for v in cr): clean.append(cr)
    c["sheets"][sn]["headers"] = merged; c["sheets"][sn]["rows"] = clean


@app.route("/api/upload/import", methods=["POST"])
def api_upload_import():
    d = request.get_json(); sid = d.get("session_id"); kf = (d.get("key_field") or "").strip(); sf = d.get("fields"); title = (d.get("title") or "").strip()
    if sid not in _upload_cache: return jsonify({"code": 1, "msg": "过期"})
    c = _upload_cache[sid]; s = c["sheets"].get(c["current_sheet"])
    if not s: return jsonify({"code": 1, "msg": "无数据"})
    ah, rows = s["headers"], s["rows"]
    if not kf: _cleanup(sid); return jsonify({"code": 0, "msg": "已取消"})
    if kf not in ah: return jsonify({"code": 1, "msg": f"字段 '{kf}' 不存在"})
    uh = [h for h in ah if h in sf] if sf and isinstance(sf,list) else list(ah)
    if kf not in uh: return jsonify({"code": 1, "msg": "关键字段未勾选"})
    ui = [ah.index(h) for h in uh]; ki_ah = ah.index(kf)
    flt = []; before = len(rows)
    for row in rows:
        v = row[ki_ah] if ki_ah < len(row) else None
        if v is not None and str(v).strip()!="": flt.append([row[i] for i in ui])
    if not flt: _cleanup(sid); return jsonify({"code": 1, "msg": "过滤后无数据"})
    tn = _safe_tablename(title) if title else f"imported_{uuid.uuid4().hex[:6]}"
    ok, msg = create_table_from_data(uh, flt, tn); _cleanup(sid)
    if ok:
        db_execute(f"ALTER TABLE `{tn}` COMMENT = %s", (title or tn,))
    if ok: msg += f"（省略 {len(ah)-len(uh)} 列，过滤 {before-len(flt)} 行）"
    return jsonify({"code": 0 if ok else 1, "msg": msg, "table_name": tn})


def _cleanup(sid):
    c = _upload_cache.pop(sid, {}); p = c.get("path","")
    if p:
        try: os.unlink(p)
        except: pass


def _parse_csv(path):
    import csv
    with open(path, encoding="utf-8-sig") as f: rows = list(csv.reader(f))
    return ([h.strip() for h in rows[0]], [row[:len(rows[0])] for row in rows[1:]]) if rows else ([],[])


def _parse_excel_raw(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        import xlrd; wb = xlrd.open_workbook(path); ns = wb.sheet_names()
        ra = [[[ws.cell_value(r,c) for c in range(ws.ncols)] for r in range(ws.nrows)] for ws in [wb.sheet_by_name(n) for n in ns]]
        return ns, ra
    elif ext == ".et":
        # .et = WPS 表格格式，先后尝试 openpyxl / xlrd
        try:
            from openpyxl import load_workbook
            wb = load_workbook(filename=path, read_only=True); ns = wb.sheetnames
            ra = [list(ws.iter_rows(values_only=True)) for ws in [wb[n] for n in ns]]
            wb.close(); return ns, [list(r) for r in ra]
        except:
            import xlrd
            wb = xlrd.open_workbook(path); ns = wb.sheet_names()
            ra = [[[ws.cell_value(r,c) for c in range(ws.ncols)] for r in range(ws.nrows)] for ws in [wb.sheet_by_name(n) for n in ns]]
            return ns, ra
    else:
        from openpyxl import load_workbook
        wb = load_workbook(filename=path, read_only=True); ns = wb.sheetnames
        ra = [list(ws.iter_rows(values_only=True)) for ws in [wb[n] for n in ns]]
        wb.close(); return ns, [list(r) for r in ra]


def _serialize_rows(rows):
    """将 rows 中的 date/datetime 转为 ISO 字符串"""
    for row in rows:
        for k, v in list(row.items()):
            if isinstance(v, (datetime.date, datetime.datetime)):
                row[k] = v.isoformat()
    return rows

def _safe_tablename(name):
    """将标题转为安全的 MySQL 表名，自动处理重名"""
    s = str(name).strip()
    safe = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\s]', '_', s)
    safe = re.sub(r'\s+', '_', safe).strip('_')
    if not safe or safe[0].isdigit():
        safe = 't_' + safe
    if not safe:
        return f"imported_{uuid.uuid4().hex[:6]}"
    if len(safe) > 60:
        safe = safe[:60]
    # 重名自动加后缀
    base = safe; idx = 1
    existing = {t["name"] for t in get_tables()}
    while safe in existing:
        suffix = f"_{idx}"
        safe = base[:60-len(suffix)] + suffix
        idx += 1
    return safe


if __name__ == "__main__":
    print("="*50); print("农村公路台账"); print(f"  地址: http://127.0.0.1:5000"); print("="*50)
    app.run(host="0.0.0.0", port=5000, debug=True)

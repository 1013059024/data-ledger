"""
数据台账系统 — Web 表格浏览服务
"""
import os, json, uuid, tempfile, re, datetime
from flask import Flask, jsonify, render_template, request, send_file
from config import FLASK_SECRET
from db import get_tables, get_schema, get_page, get_pk_column, create_empty_table, create_table_from_data, drop_table, rename_table, update_cell, rename_column, query_one, query, execute, distinct_values, get_table_comment, set_table_comment

app = Flask(__name__)
app.secret_key = FLASK_SECRET
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
_upload_cache = {}
_DATA_DIR = os.environ.get('DATA_LEDGER_DATA') or os.path.dirname(__file__)
_MAP_FILE = os.path.join(_DATA_DIR, "_sync_mappings.json")
_GROUP_FILE = os.path.join(_DATA_DIR, "_table_groups.json")
_KF_FILE = os.path.join(_DATA_DIR, "_key_fields.json")
_AGG_FILE = os.path.join(_DATA_DIR, "_agg_sources.json")
_BACKUP_DIR = os.path.join(_DATA_DIR, "_backup")
_DEL_TOKEN = os.urandom(8).hex()  # 每次启动随机生成，只有页面知道


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


def _load_kf():
    if not os.path.exists(_KF_FILE): return {}
    try:
        with open(_KF_FILE, encoding="utf-8") as f: return json.load(f)
    except: return {}

def _save_kf(kf):
    with open(_KF_FILE, "w", encoding="utf-8") as f: json.dump(kf, f, ensure_ascii=False, indent=2)


def _load_agg():
    if not os.path.exists(_AGG_FILE): return {}
    try:
        with open(_AGG_FILE, encoding="utf-8") as f: return json.load(f)
    except: return {}

def _save_agg(agg):
    with open(_AGG_FILE, "w", encoding="utf-8") as f: json.dump(agg, f, ensure_ascii=False, indent=2)


# ── 自动备份 ──────────────────────────────────────────
def _to_json_safe(v):
    """将不可 JSON 序列化的类型转为 float"""
    if v is None: return None
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    if isinstance(v, (int, float)): return v
    if isinstance(v, decimal.Decimal): return float(v)
    try:
        json.dumps(v)
        return v
    except: return str(v)

import decimal

def _backup_table(table_name):
    """删表前自动备份到 _backup/ 目录"""
    try:
        schema = get_schema(table_name)
        if not schema: return
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        pk = get_pk_column(table_name) or "id"
        rows = query(f"SELECT * FROM `{table_name}` ORDER BY `{pk}`")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r'[\\/:*?"<>|]', '_', table_name)
        path = os.path.join(_BACKUP_DIR, f"{safe}_{ts}.json")
        # 备份到临时文件再重命名，避免写一半崩溃留残文件
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({
                "table": table_name,
                "backup_at": ts,
                "schema": schema,
                "rows": [{k: _to_json_safe(v) for k, v in row.items()} for row in rows]
            }, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"[backup] {table_name} 备份失败: {e}")
        try: os.unlink(tmp_path)
        except: pass


def _save_table_manifest():
    """建表/导表后记录表结构到 manifest"""
    try:
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        manifest = []
        for t in get_tables():
            manifest.append({
                "name": t["name"],
                "comment": t["comment"],
                "schema": get_schema(t["name"]),
                "created_at": datetime.datetime.now().isoformat()
            })
        with open(os.path.join(_BACKUP_DIR, "_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except: pass


@app.route("/")
def index():
    return render_template("index.html", del_token=_DEL_TOKEN)


@app.route("/api/tables")
def api_tables():
    return jsonify({"code": 0, "data": get_tables()})

@app.route("/api/tables", methods=["POST"])
def api_create_table():
    """新建空表（手动，非导入）"""
    d = request.get_json()
    if not d or not d.get("name"):
        return jsonify({"code": 1, "msg": "表名为空"})
    name = d["name"].strip()
    if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', name):
        return jsonify({"code": 1, "msg": "表名只允许字母、数字、下划线和中文"})
    if len(name) > 64:
        return jsonify({"code": 1, "msg": "表名不能超过64个字符"})
    columns = d.get("columns", [])
    for col in columns:
        cn = col.get("name", "").strip()
        if not cn:
            return jsonify({"code": 1, "msg": "字段名不能为空"})
        if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', cn):
            return jsonify({"code": 1, "msg": f"字段名「{cn}」只允许字母、数字、下划线和中文"})
    key_field = d.get("key_field", "").strip()
    if key_field and not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', key_field):
        return jsonify({"code": 1, "msg": "关键字段名只允许字母、数字、下划线和中文"})
    try:
        ok, msg = create_empty_table(name, columns)
        if ok:
            if key_field:
                kf_map = _load_kf()
                kf_map[name] = key_field
                _save_kf(kf_map)
            _save_table_manifest()
            return jsonify({"code": 0, "msg": msg + (f"，关键字段: {key_field}" if key_field else "")})
        else:
            return jsonify({"code": 1, "msg": msg})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"建表失败: {str(e)}"})

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


# ========== 关键字段 ==========

@app.route("/api/table/<table_name>/key-field", methods=["GET"])
def api_get_key_field(table_name):
    kf = _load_kf().get(table_name, "")
    return jsonify({"code": 0, "data": {"key_field": kf}})

@app.route("/api/table/<table_name>/key-field", methods=["PUT"])
def api_set_key_field(table_name):
    d = request.get_json()
    kf = (d or {}).get("key_field", "").strip()
    sch = get_schema(table_name)
    if not sch: return jsonify({"code": 1, "msg": "表不存在"})
    if kf and kf not in [s["field"] for s in sch]:
        return jsonify({"code": 1, "msg": f"字段 `{kf}` 不存在于表中"})
    km = _load_kf()
    if kf:
        km[table_name] = kf
    else:
        km.pop(table_name, None)
    _save_kf(km)
    return jsonify({"code": 0, "msg": f"关键字段已设置为 `{kf}`" if kf else "关键字段已清除"})


@app.route("/api/table/<table_name>", methods=["DELETE"])
def api_delete_table(table_name):
    try:
        # 安全防护：有数据的表必须传正确的删除令牌（从页面获取）才能删除
        d = request.get_json(silent=True) or {}
        token = d.get("del_token", "") if isinstance(d, dict) else ""
        if token != _DEL_TOKEN:
            return jsonify({"code": 1, "msg": "拒绝删除缺少有效的删除令牌（仅页面 UI 可执行删除操作）"})
        _backup_table(table_name)
        km = _load_kf(); km.pop(table_name, None); _save_kf(km)
        drop_table(table_name)
        _save_table_manifest()
        return jsonify({"code": 0, "msg": "已删除（已备份到 _backup/）"})
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
    try:
        rename_table(table_name, nn)
        set_table_comment(nn, nn)
        km = _load_kf()
        if table_name in km:
            km[nn] = km.pop(table_name)
            _save_kf(km)
        return jsonify({"code": 0, "msg": f"已重命名为 `{nn}`"})
    except Exception as e: return jsonify({"code": 1, "msg": f"重命名失败: {str(e)}"})


@app.route("/api/table/<table_name>/column", methods=["PUT"])
def api_rename_column(table_name):
    d = request.get_json(); old = (d or {}).get("old",""); nn = (d or {}).get("new","")
    if not old or not nn: return jsonify({"code": 1, "msg": "参数不全"})
    if nn.lower() == "id": return jsonify({"code": 1, "msg": "id 字段不能修改"})
    try:
        rename_column(table_name, old, nn)
        # 更新所有映射中的字段名
        mappings = _load_m()
        changed = False
        for mp in mappings:
            if mp["st"] == table_name:
                for p in mp["ps"]:
                    if p["s"] == old: p["s"] = nn; changed = True
            if mp["tt"] == table_name:
                for p in mp["ps"]:
                    if p["t"] == old: p["t"] = nn; changed = True
        if changed:
            _save_m(mappings)
        return jsonify({"code": 0, "msg": "字段已重命名，相关映射已更新"})
    except Exception as e: return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/table/<table_name>/dedup", methods=["POST"])
def api_dedup(table_name):
    """对关键字段查重
    POST body: {"preview": true}  → 预览重复记录（不删除）
    POST body: {}                 → 执行删除（保留每组ID最小的）
    """
    kf = _load_kf().get(table_name, "")
    if not kf:
        return jsonify({"code": 1, "msg": "请先设置关键字段"})
    schema = get_schema(table_name)
    all_fields = [s["field"] for s in schema]
    if kf not in all_fields:
        return jsonify({"code": 1, "msg": f"字段 `{kf}` 已不存在"})
    pk = get_pk_column(table_name) or "id"
    has_del = "_deleted" in all_fields
    del_cond = "AND IFNULL(`_deleted`,0)!=1" if has_del else ""
    d = request.get_json(silent=True) or {}
    preview = d.get("preview", False)
    try:
        if preview:
            # ── 预览模式：查出重复记录，不删 ──
            rows = query(f"SELECT * FROM `{table_name}` WHERE 1=1 {del_cond} ORDER BY `{kf}`,`{pk}`")
            # 分组找出重复的
            groups = []  # [{key_value, records: [{id, fields}], keep_id, del_ids}]
            i = 0
            while i < len(rows):
                cur_key = rows[i].get(kf)
                if cur_key is None:
                    i += 1
                    continue
                group = [rows[i]]
                i += 1
                while i < len(rows) and rows[i].get(kf) == cur_key:
                    group.append(rows[i])
                    i += 1
                if len(group) > 1:
                    # 保留ID最小的，其余标记为删除
                    group.sort(key=lambda r: r[pk])
                    keep = group[0]
                    to_del = group[1:]
                    recs = []
                    for r in group:
                        fv = {}
                        for f in all_fields:
                            if f in (pk, "_deleted"):
                                continue
                            v = r.get(f)
                            if isinstance(v, (datetime.date, datetime.datetime)):
                                v = v.isoformat()
                            fv[f] = v
                        recs.append({
                            "id": r[pk],
                            "is_keep": r[pk] == keep[pk],
                            "fields": fv
                        })
                    groups.append({
                        "key_value": str(cur_key) if cur_key is not None else "",
                        "records": recs,
                        "keep_id": keep[pk],
                        "del_ids": [r[pk] for r in to_del]
                    })
            total_duplicates = sum(len(g["del_ids"]) for g in groups)
            return jsonify({"code": 0, "data": {
                "groups": len(groups),
                "records": total_duplicates,
                "items": groups,
                "key_field": kf,
                "all_fields": [f for f in all_fields if f not in (pk, "_deleted")]
            }})
        else:
            # ── 执行删除 ──
            deleted = execute(f"DELETE t1 FROM `{table_name}` t1 INNER JOIN `{table_name}` t2 WHERE t1.`{kf}`=t2.`{kf}` AND t1.`{pk}`>t2.`{pk}`")
            return jsonify({"code": 0, "msg": f"已删除 {deleted} 条重复记录"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"去重失败: {e}"})

@app.route("/api/table/<table_name>/row", methods=["POST"])
def api_add_row(table_name):
    """插入一条空记录"""
    pk = get_pk_column(table_name)
    schema = get_schema(table_name)
    fields = [s["field"] for s in schema if s["field"] != pk and s["field"] != "_deleted"]
    if not fields: return jsonify({"code": 1, "msg": "无可用字段"})
    cols = ", ".join([f"`{f}`" for f in fields])
    try:
        from db import execute, query_one
        ph = ", ".join(["NULL"] * len(fields))
        execute(f"INSERT INTO `{table_name}` ({cols}) VALUES ({ph})")
        pk = get_pk_column(table_name) or "id"
        new_row = query_one(f"SELECT MAX(`{pk}`) as new_id FROM `{table_name}`")
        new_id = new_row["new_id"] if new_row else 0
        return jsonify({"code": 0, "msg": "已添加", "id": new_id})
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


@app.route("/api/table/<table_name>/rows/hide", methods=["POST"])
def api_hide_rows(table_name):
    """批量隐藏多行"""
    d = request.get_json()
    ids = d.get("ids", [])
    if not ids: return jsonify({"code": 1, "msg": "请指定要隐藏的行"})
    try:
        schema = get_schema(table_name)
        if not any(s["field"] == "_deleted" for s in schema):
            execute(f"ALTER TABLE `{table_name}` ADD COLUMN `_deleted` TINYINT DEFAULT 0")
        ph = ",".join(["%s"] * len(ids))
        execute(f"UPDATE `{table_name}` SET `_deleted`=1 WHERE `id` IN ({ph})", ids)
        return jsonify({"code": 0, "msg": f"已隐藏 {len(ids)} 行"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"批量隐藏失败: {e}"})


@app.route("/api/table/<table_name>/rows/unhide", methods=["POST"])
def api_unhide_rows(table_name):
    """恢复隐藏的行"""
    d = request.get_json()
    ids = d.get("ids", [])
    try:
        if ids:
            ph = ",".join(["%s"] * len(ids))
            execute(f"UPDATE `{table_name}` SET `_deleted`=0 WHERE `id` IN ({ph})", ids)
        else:
            execute(f"UPDATE `{table_name}` SET `_deleted`=0 WHERE `_deleted`=1")
        return jsonify({"code": 0, "msg": "已恢复"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"恢复失败: {e}"})


@app.route("/api/table/<table_name>/row/<int:row_id>/table-delete", methods=["POST"])
def api_table_delete_row(table_name, row_id):
    """表删除：从当前表视图移除，保留 DB 记录（_deleted=2，不在隐藏列表显示）"""
    try:
        schema = get_schema(table_name)
        if not any(s["field"] == "_deleted" for s in schema):
            execute(f"ALTER TABLE `{table_name}` ADD COLUMN `_deleted` TINYINT DEFAULT 0")
        execute(f"UPDATE `{table_name}` SET `_deleted`=2 WHERE `id`=%s", (row_id,))
        return jsonify({"code": 0, "msg": "已从本表移除"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"表删除失败: {e}"})


@app.route("/api/table/<table_name>/hidden-count", methods=["GET"])
def api_hidden_count(table_name):
    try:
        schema = get_schema(table_name)
        has_del = any(s["field"] == "_deleted" for s in schema)
        if not has_del: return jsonify({"code": 0, "data": {"count": 0}})
        r = query_one(f"SELECT COUNT(*) AS cnt FROM `{table_name}` WHERE IFNULL(`_deleted`,0)=1")
        return jsonify({"code": 0, "data": {"count": r["cnt"] if r else 0}})
    except:
        return jsonify({"code": 0, "data": {"count": 0}})


@app.route("/api/table/<table_name>/hidden-rows", methods=["GET"])
def api_hidden_rows(table_name):
    try:
        schema = get_schema(table_name)
        has_del = any(s["field"] == "_deleted" for s in schema)
        if not has_del: return jsonify({"code": 0, "data": []})
        rows = query(f"SELECT * FROM `{table_name}` WHERE IFNULL(`_deleted`,0)=1")
        # 计算每条隐藏行在默认 id 排序下的序号
        for r in rows:
            rid = r["id"]
            cnt = query_one(f"SELECT COUNT(*) AS c FROM `{table_name}` WHERE IFNULL(`_deleted`,0) NOT IN (1,2) AND `id`<%s", (rid,))
            r["_seq"] = (cnt["c"] if cnt else 0) + 1
        kf = _load_kf().get(table_name, "")
        return jsonify({"code": 0, "data": rows, "key_field": kf})
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/table/<table_name>/deleted-rows", methods=["GET"])
def api_deleted_rows(table_name):
    """获取表删除的记录（_deleted=2），带序号"""
    try:
        schema = get_schema(table_name)
        has_del = any(s["field"] == "_deleted" for s in schema)
        if not has_del: return jsonify({"code": 0, "data": []})
        rows = query(f"SELECT * FROM `{table_name}` WHERE IFNULL(`_deleted`,0)=2")
        for r in rows:
            rid = r["id"]
            cnt = query_one(f"SELECT COUNT(*) AS c FROM `{table_name}` WHERE IFNULL(`_deleted`,0)=2 AND `id`<%s", (rid,))
            r["_seq"] = (cnt["c"] if cnt else 0) + 1
        return jsonify({"code": 0, "data": rows})
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/table/<table_name>/all-rows", methods=["GET"])
def api_all_rows(table_name):
    """返回表内所有记录（含隐藏/表删除），带状态标记"""
    try:
        schema = get_schema(table_name)
        has_del = any(s["field"] == "_deleted" for s in schema)
        rows = query(f"SELECT * FROM `{table_name}` ORDER BY `id`")
        for r in rows:
            r["_del_status"] = ""
            if has_del:
                dv = r.get("_deleted")
                if dv == 1: r["_del_status"] = "隐藏"
                elif dv == 2: r["_del_status"] = "表删除"
        return jsonify({"code": 0, "data": rows, "schema": schema})
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/table/<table_name>/rows/un-table-delete", methods=["POST"])
def api_un_table_delete_rows(table_name):
    """恢复表删除的行（_deleted=2 → 0）"""
    d = request.get_json()
    ids = d.get("ids", [])
    try:
        if ids:
            ph = ",".join(["%s"] * len(ids))
            execute(f"UPDATE `{table_name}` SET `_deleted`=0 WHERE `id` IN ({ph})", ids)
        else:
            execute(f"UPDATE `{table_name}` SET `_deleted`=0 WHERE `_deleted`=2")
        return jsonify({"code": 0, "msg": "已恢复"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"恢复失败: {e}"})


# ── 列隐藏 ──────────────────────────────────────────
_HIDDEN_COL_FILE = os.path.join(_DATA_DIR, "_hidden_columns.json")
def _load_hidden_cols():
    try:
        if os.path.exists(_HIDDEN_COL_FILE):
            with open(_HIDDEN_COL_FILE, encoding="utf-8") as f: return json.load(f) or {}
        return {}
    except: return {}
def _save_hidden_cols(d):
    with open(_HIDDEN_COL_FILE, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=2)

@app.route("/api/table/<table_name>/column/hide", methods=["POST"])
def api_hide_column(table_name):
    d = request.get_json(); cols = d.get("columns", [])
    hc = _load_hidden_cols()
    if table_name not in hc: hc[table_name] = []
    for c in cols:
        if c not in hc[table_name]: hc[table_name].append(c)
    _save_hidden_cols(hc)
    return jsonify({"code": 0, "msg": f"已隐藏 {len(cols)} 列"})

@app.route("/api/table/<table_name>/column/unhide", methods=["POST"])
def api_unhide_column(table_name):
    d = request.get_json(); cols = d.get("columns", [])
    hc = _load_hidden_cols()
    if table_name in hc:
        if cols:
            hc[table_name] = [c for c in hc[table_name] if c not in cols]
        else:
            del hc[table_name]
        _save_hidden_cols(hc)
    return jsonify({"code": 0, "msg": "已恢复"})

@app.route("/api/table/<table_name>/hidden-cols", methods=["GET"])
def api_hidden_cols(table_name):
    hc = _load_hidden_cols()
    return jsonify({"code": 0, "data": hc.get(table_name, [])})


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

# api_set_column_type 和 api_reorder_columns 在 routes_column.py 中定义
# 通过 pyi_entry.py 中的 import routes_column 注册到 app


# api_reorder_columns 在 routes_column.py 中定义


@app.route("/api/table/<table_name>/column/<column_name>", methods=["DELETE"])
def api_delete_column(table_name, column_name):
    """删除指定列"""
    if column_name.lower() == "id": return jsonify({"code": 1, "msg": "id 列不能删除"})
    try:
        execute(f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`")
        return jsonify({"code": 0, "msg": f"列 `{column_name}` 已删除"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"删除失败: {e}"})

@app.route("/api/table/<table_name>/column/<column_name>/values")
def api_column_values(table_name, column_name):
    """获取某列的所有唯一值（用于筛选器），支持级联 filters"""
    s = request.args.get("search", "", type=str)
    filters_json = request.args.get("filters", default=None, type=str)
    filters = None
    if filters_json:
        try: filters = json.loads(filters_json)
        except: pass
    try:
        vals = distinct_values(table_name, column_name, s, filters)
        return jsonify({"code": 0, "data": vals})
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})


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
    """导出表数据为 Excel（公文格式：标题+黑体表头+仿宋正文+全框线+居中）"""
    try:
        import openpyxl; from openpyxl.styles import Font, Alignment, Border, Side; from openpyxl.utils import get_column_letter; from io import BytesIO
        schema = get_schema(table_name)
        if not schema: return jsonify({"code": 1, "msg": "表不存在"})
        pk = get_pk_column(table_name) or "id"
        fields = [s["field"] for s in schema if s["field"] not in (pk, "_deleted")]
        # 排除隐藏列
        hidden_cols = _load_hidden_cols().get(table_name, [])
        if hidden_cols:
            fields = [f for f in fields if f not in hidden_cols]
        if not fields:
            return jsonify({"code": 1, "msg": "没有可导出的列"})
        # 读取筛选条件（从 URL query string），仅导出筛选后的行
        filters_json = request.args.get("filters", "")
        order_field = request.args.get("order_field", default=None, type=str)
        order_dir = request.args.get("order_dir", default="asc", type=str)
        # 构建 WHERE
        has_where = False; where_parts = []; params = []; schema_fields = {s["field"] for s in schema}
        if filters_json:
            try:
                filters = json.loads(filters_json)
                for fld, vals in filters.items():
                    if fld in schema_fields and vals and len(vals) > 0:
                        ph = ",".join(["%s"]*len(vals))
                        where_parts.append(f"`{fld}` IN ({ph})")
                        params.extend(vals)
            except: pass
        if where_parts:
            has_where = True
        # 构建 ORDER BY
        order_sql = f"ORDER BY `{pk}`"
        if order_field and order_field in schema_fields:
            dir_sql = "DESC" if order_dir == "desc" else "ASC"
            order_sql = f"ORDER BY `{order_field}` {dir_sql}, `{pk}`"
        # 执行查询
        if has_where:
            where = " AND ".join(where_parts)
            rows = query(f"SELECT * FROM `{table_name}` WHERE {where} {order_sql}", params)
        else:
            rows = query(f"SELECT * FROM `{table_name}` {order_sql}")
        # 标题：使用表注释（comment），没有则用表名
        tables = get_tables()
        table_comment = {t["name"]: t["comment"] for t in tables}.get(table_name, "")
        title_text = table_comment or table_name
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = (table_name or "sheet")[:31]
        # ── 公文格式样式 ──────────────────────────────
        title_font   = Font(name="黑体", size=16, bold=True)          # 三号黑体
        hdr_font     = Font(name="黑体", size=10.5, bold=True)         # 五号黑体加粗
        body_font    = Font(name="仿宋", size=10.5)                     # 五号仿宋
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=False)
        thin_line    = Side(style="thin", color="000000")               # 0.5pt 黑色实线
        thin_border  = Border(left=thin_line, right=thin_line, top=thin_line, bottom=thin_line)
        # ── 行 1：标题 ─────────────────────────────────
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(fields))
        title_cell = ws.cell(1, 1, title_text)
        title_cell.font = title_font
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 36  # 标题行高
        # ── 行 2：表头 ─────────────────────────────────
        for ci, f in enumerate(fields, 1):
            cell = ws.cell(2, ci, f)
            cell.font = hdr_font
            cell.alignment = center_align
            cell.border = thin_border
        ws.row_dimensions[2].height = 24
        # ── 写数据 + 列宽计算 ──────────────────────────
        col_widths = {}
        for ci, f in enumerate(fields, 1):
            cw = sum(18 if ord(ch) > 0x4e00 else 7 for ch in str(f))
            col_widths[ci] = cw + 4
        ri = 3
        for row in rows:
            if "_deleted" in row and row["_deleted"] == 1: continue
            ws.row_dimensions[ri].height = 22
            for ci, f in enumerate(fields, 1):
                val = row.get(f)
                cell = ws.cell(ri, ci, val)
                cell.font = body_font
                cell.alignment = center_align
                cell.border = thin_border
                sv = str(val) if val is not None else ""
                cw = sum(18 if ord(ch) > 0x4e00 else 7 for ch in sv)
                if cw > col_widths.get(ci, 0):
                    col_widths[ci] = cw
            ri += 1
        # ── 应用列宽 ───────────────────────────────────
        for ci in col_widths:
            ws.column_dimensions[get_column_letter(ci)].width = min(max(col_widths[ci] / 7 + 2, 8), 80)
        # ── 打印设置 ───────────────────────────────────
        last_row = ri - 1
        ws.print_area = f"A1:{get_column_letter(len(fields))}{last_row}"
        ws.page_setup.orientation = "landscape" if len(fields) > 6 else "portrait"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.page_margins.left = 0.5
        ws.page_margins.right = 0.5
        # 冻结标题+表头行
        ws.freeze_panes = "A3"
        buf = BytesIO(); wb.save(buf); buf.seek(0)
        return send_file(buf, download_name=f"{table_name}.xlsx", as_attachment=True)
    except Exception as e:
        return jsonify({"code": 1, "msg": f"导出失败: {e}"})

@app.route("/api/table/<table_name>", methods=["PATCH"])
def api_update_cell(table_name):
    """更新单元格
    PATCH /api/table/<table_name>
    参数: {"id": row_id, "field": "列名", "value": "新值"}
    自动同步到映射表中同关键字段值的记录。
    """
    d = request.get_json()
    if not d: return jsonify({"code": 1, "msg": "请求为空"})
    row_id, field, value = d.get("id"), d.get("field"), d.get("value")
    if row_id is None or not field: return jsonify({"code": 1, "msg": "参数不全"})
    # 关键字段唯一性检查
    if value is not None and str(value).strip():
        is_key = False
        # 检查同步映射中的关键字段
        for mp in _load_m():
            if table_name in (mp["st"], mp["tt"]) and mp["kf"] == field:
                is_key = True; break
        # 检查表自身设定的关键字段
        if not is_key:
            stored_kf = _load_kf().get(table_name, "")
            if stored_kf == field:
                is_key = True
        if is_key:
            pk = get_pk_column(table_name) or "id"
            has_del = any(s["field"] == "_deleted" for s in get_schema(table_name))
            del_cond = "AND (`_deleted` IS NULL OR `_deleted`!=1)" if has_del else ""
            cnt = query_one(f"SELECT COUNT(*) AS c FROM `{table_name}` WHERE `{field}`=%s AND `{pk}`!=%s {del_cond}", (value, row_id))
            if cnt and cnt["c"] > 0:
                return jsonify({"code": 1, "msg": f"关键字段「{field}」值「{value}」已存在，不能重复"})
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
    pp = request.args.get("per_page", 50, type=int)
    show_all = request.args.get("show_all", 0, type=int)
    filters_json = request.args.get("filters", default=None, type=str)
    filters = None
    if filters_json:
        try: filters = json.loads(filters_json)
        except: pass
    total, rows = get_page(table_name, p, pp,
        request.args.get("search", "", type=str),
        request.args.get("order_field", default=None, type=str),
        request.args.get("order_dir", default="asc", type=str), hide_deleted=not show_all, filters=filters)
    comment = get_table_comment(table_name)
    if not show_all:
        s = [c for c in s if c["field"] != "_deleted"]
        rows = [{k:v for k,v in row.items() if k != "_deleted"} for row in rows]
    return jsonify({"code": 0, "data": {"name": table_name, "comment": comment, "schema": s,
        "pk": get_pk_column(table_name), "total": total, "page": p, "per_page": pp, "rows": _serialize_rows(rows)}})


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
                                from db import alter_column_type
                                alter_column_type(tbl, m.group(1), "TEXT")
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
    # 自动识别关键字段：① 目标表存储的关键字段 → ② 源表中的目标表 PK → ③ 第一个匹配字段
    stored_kf = _load_kf().get(tgt, "")
    kf = ""
    if stored_kf and stored_kf in src_fields:
        kf = stored_kf
    elif pk in src_fields:
        kf = pk
    else:
        kf = list(col_map.keys())[0]
    # 如果唯一匹配的字段就是关键字段本身 → 仅更新该字段值（允许用户同步同名字段）
    non_key_cols = {f for f in col_map if f != kf}
    # 读取目标表已有记录的关键值
    has_deleted = any(s["field"] == "_deleted" for s in schema)
    visible_exists = {}   # 可见记录的关键值 → id
    hidden_exists = {}    # 隐藏记录的关键值 → id
    if kf:
        try:
            sel_cols = f"`id`,`{kf}`" + (", `_deleted`" if has_deleted else "")
            for row in query(f"SELECT {sel_cols} FROM `{tgt}` WHERE `{kf}` IS NOT NULL AND TRIM(`{kf}`)!=''"):
                rid = str(row[kf]).strip()
                is_hidden = has_deleted and row.get("_deleted", 0) == 1
                if is_hidden:
                    hidden_exists[rid] = row["id"]
                else:
                    visible_exists[rid] = row["id"]
        except: pass
    updated, inserted, restored = 0, 0, 0
    for crow in _clipboard["rows"]:
        kv = ""
        if kf in src_fields:
            ki = src_fields.index(kf)
            kv = str(crow[ki]).strip() if ki < len(crow) and crow[ki] is not None else ""
        tf_vals = {}
        for tf, ci in col_map.items():
            if ci < len(crow) and crow[ci] is not None and str(crow[ci]).strip():
                tf_vals[tf] = crow[ci]
        if not tf_vals: continue
        if kv and kv in visible_exists:
            # 更新已有可见记录
            sets = ", ".join([f"`{f}`=%s" for f in tf_vals])
            try:
                execute(f"UPDATE `{tgt}` SET {sets} WHERE `{kf}`=%s", list(tf_vals.values()) + [kv])
                updated += 1
            except: pass
        elif kv and kv in hidden_exists:
            # 隐藏记录 → 恢复显示 + 更新数据
            sets = ", ".join([f"`{f}`=%s" for f in list(tf_vals.keys()) + (["_deleted"] if has_deleted else [])])
            vals = list(tf_vals.values()) + ([0] if has_deleted else []) + [kv]
            try:
                execute(f"UPDATE `{tgt}` SET {sets} WHERE `{kf}`=%s", vals)
                restored += 1
            except: pass
        else:
            # 不存在 → 新增
            all_cols = list(tf_vals.keys())
            all_vals = list(tf_vals.values())
            if kv and kf and kf not in all_cols:
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
    parts = []
    if updated: parts.append(f"更新 {updated} 行")
    if inserted: parts.append(f"新增 {inserted} 行")
    if restored: parts.append(f"恢复 {restored} 行（从隐藏状态恢复）")
    msg = "粘贴完成：" + "，".join(parts) if parts else "粘贴完成：无变化"
    return jsonify({"code": 0, "msg": msg, "updated": updated, "inserted": inserted, "restored": restored})

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


# ========== 多表汇总 ==========

@app.route("/api/agg-source/save", methods=["POST"])
def api_save_agg_source():
    """记录汇总来源"""
    d = request.get_json()
    tn = (d or {}).get("table", "").strip()
    src = (d or {}).get("source", "").strip()
    gf = (d or {}).get("group_field", "").strip()
    sfs = (d or {}).get("sum_fields", [])
    if not tn or not src: return jsonify({"code": 1, "msg": "参数不足"})
    agg = _load_agg()
    agg[tn] = {"source": src, "group_field": gf, "sum_fields": sfs}
    _save_agg(agg)
    return jsonify({"code": 0})


@app.route("/api/table/<table_name>/agg-source", methods=["GET"])
def api_get_agg_source(table_name):
    """获取汇总表的来源信息"""
    agg = _load_agg()
    info = agg.get(table_name)
    if info:
        return jsonify({"code": 0, "data": info})
    return jsonify({"code": 1, "msg": "非汇总表"})


@app.route("/api/table/<table_name>/agg-recalc", methods=["POST"])
def api_agg_recalc(table_name):
    """重新计算汇总表数据"""
    agg = _load_agg()
    info = agg.get(table_name)
    if not info:
        return jsonify({"code": 1, "msg": "非汇总表"})
    source = info.get("source")
    gf = info.get("group_field")
    sfs = info.get("sum_fields")
    if not source or not gf or not sfs:
        return jsonify({"code": 1, "msg": "汇总信息不完整"})
    try:
        from db import get_schema, query, execute
        src_schema = get_schema(source)
        if not src_schema: return jsonify({"code": 1, "msg": f"源表 '{source}' 不存在"})
        tgt_schema = get_schema(table_name)
        if not tgt_schema: return jsonify({"code": 1, "msg": f"汇总表 '{table_name}' 不存在"})
        # 执行汇总查询
        sum_cols = ", ".join([f'SUM("{sf}") AS "{sf}"' for sf in sfs])
        sql = f'SELECT "{gf}", {sum_cols} FROM "{source}" GROUP BY "{gf}" ORDER BY "{gf}"'
        rows = query(sql)
        # 清空汇总表数据并重新插入
        execute(f'DELETE FROM "{table_name}" WHERE 1=1')
        for row in rows:
            cols = ", ".join([f'"{c}"' for c in [gf] + sfs])
            ph = ", ".join(["?"] * (len(sfs) + 1))
            vals = [row.get(gf, "")]
            for sf in sfs:
                vals.append(row.get(sf) or 0)
            execute(f'INSERT INTO "{table_name}" ({cols}) VALUES ({ph})', vals)
        return jsonify({"code": 0, "msg": f"已从 '{source}' 重新汇总，共 {len(rows)} 行"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"重新汇总失败: {str(e)}"})


@app.route("/api/table/<table_name>/aggregate-inline", methods=["POST"])
def api_aggregate_inline(table_name):
    """本表汇总：按 group_field 分组，对 sum_fields 求和，返回汇总行"""
    d = request.get_json()
    gf = (d or {}).get("group_field", "").strip()
    sfs = (d or {}).get("sum_fields", [])
    if not gf or not sfs:
        return jsonify({"code": 1, "msg": "请选择分组字段和汇总字段"})
    try:
        from db import get_schema, query
        schema = get_schema(table_name)
        if not schema: return jsonify({"code": 1, "msg": "表不存在"})
        schema_fields = [s["field"] for s in schema]
        if gf not in schema_fields: return jsonify({"code": 1, "msg": f"字段 '{gf}' 不存在"})
        for sf in sfs:
            if sf not in schema_fields: return jsonify({"code": 1, "msg": f"字段 '{sf}' 不存在"})
        sum_cols = ", ".join([f'SUM("{sf}") AS "{sf}"' for sf in sfs])
        sql = f'SELECT "{gf}", {sum_cols} FROM "{table_name}" GROUP BY "{gf}" ORDER BY "{gf}"'
        rows = query(sql)
        total = {sf: 0 for sf in sfs}
        for row in rows:
            for sf in sfs:
                v = row.get(sf) or 0
                total[sf] += float(v)
        return jsonify({"code": 0, "data": {
            "groups": rows,
            "total": total,
            "group_field": gf,
            "sum_fields": sfs
        }})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"汇总失败: {str(e)}"})


@app.route("/api/aggregate/preview", methods=["POST"])
def api_aggregate_preview():
    """预览多表汇总结果"""
    d = request.get_json()
    if not d: return jsonify({"code": 1, "msg": "请求为空"})
    table_names = d.get("tables", [])
    key_field = (d.get("key_field") or "").strip()
    if len(table_names) < 2:
        return jsonify({"code": 1, "msg": "请选择至少 2 张表"})
    if not key_field:
        return jsonify({"code": 1, "msg": "请选择关键字段（汇总依据）"})
    try:
        # 加载已有的字段映射，用于合并同义不同名的字段
        mappings = _load_m()  # [{"st":"A","tt":"B","kf":"项目编号","ps":[{"s":"源字段","t":"目标字段"},...]}]
        all_keys = set()
        table_data = {}
        for tn in table_names:
            schema = get_schema(tn)
            if not schema: return jsonify({"code": 1, "msg": f"表 `{tn}` 不存在"})
            fields = [s["field"] for s in schema if s["field"] not in ("id", "_deleted", key_field)]
            has_del = any(s["field"] == "_deleted" for s in schema)
            rows = query(f"SELECT * FROM `{tn}` ORDER BY `{key_field}`")
            table_data[tn] = {"fields": fields, "records": {}}
            for row in rows:
                if has_del and row.get("_deleted", 0) == 1: continue
                kv = str(row.get(key_field, "")).strip()
                if not kv: continue
                all_keys.add(kv)
                rec = {}
                for f in fields:
                    rec[f] = row.get(f)
                table_data[tn]["records"][kv] = rec
        # 构建映射字典： (table1, table2) → { field1: field2 }
        # 统一用 (table1, table2) 方向存储，table1 的字段映射到 table2 的字段
        merge_map = {}
        for mp in mappings:
            if mp["st"] in table_names and mp["tt"] in table_names:
                key = (mp["st"], mp["tt"])
                if key not in merge_map:
                    merge_map[key] = {}
                for p in mp["ps"]:
                    merge_map[key][p["s"]] = p["t"]
        # 统一字段名：对存在映射的不同名成对字段，只保留第一个表的字段名
        unified_warnings = []
        merged_headers = [key_field]
        field_sources = {}  # header_name → (table_name, field_on_that_table)
        for tn in table_names:
            for f in table_data[tn]["fields"]:
                hdr = f
                # 检查是否已有映射对中的另一方已作为表头存在
                merged = False
                for (t1, t2), pairs in merge_map.items():
                    # 检查当前表是 t1 还是 t2
                    if tn == t1:
                        other_table = t2
                        if other_table not in table_names:
                            continue
                        # f 是 t1 的字段 → 找映射到 t2 的字段
                        if f in pairs:
                            mapped_field = pairs[f]
                        else:
                            continue
                    elif tn == t2:
                        other_table = t1
                        if other_table not in table_names:
                            continue
                        # f 是 t2 的字段 → 找反向映射
                        mapped_field = None
                        for src_f, tgt_f in pairs.items():
                            if tgt_f == f:
                                mapped_field = src_f
                                break
                        if mapped_field is None:
                            continue
                    else:
                        continue
                    if mapped_field and mapped_field in field_sources:
                        # 对方表已用 mapped_field 作为表头 → 共用此列（数据合并到该列）
                        merged = True
                        if mapped_field != f:
                            conflict_pair = {"tables": [tn, other_table], "fields": [f, mapped_field], "default_name": mapped_field}
                            # 去重
                            dup = False
                            for cw in unified_warnings:
                                if cw.get("fields") and set(cw["fields"]) == set(conflict_pair["fields"]):
                                    dup = True; break
                            if not dup:
                                unified_warnings.append(conflict_pair)
                        break
                    elif mapped_field and mapped_field not in field_sources and tn != other_table:
                        # f 有映射但对方字段尚未作为表头 → 用 f 作为表头
                        pass  # 使用当前字段名
                if merged:
                    continue
                if hdr in field_sources:
                    # 真正同名的已有，但非映射关系 → 加表名前缀
                    hdr = f"{tn}.{f}"
                merged_headers.append(hdr)
                field_sources[hdr] = (tn, f)
        # 合并行数据
        merged_rows = []
        for kv in sorted(all_keys):
            row = [kv]
            for hdr in merged_headers[1:]:
                tn, f = field_sources[hdr]
                rec = table_data[tn]["records"].get(kv)
                row.append(rec.get(f) if rec else None)
            merged_rows.append(row)
        # 分离 field_conflicts 和普通 warnings
        field_conflicts = [w for w in unified_warnings if isinstance(w, dict) and "fields" in w]
        text_warnings = [w for w in unified_warnings if not isinstance(w, dict)]
        # orphan_suggestions: 列出每张表独有的字段（不会被映射合并的同名/不同名字段）
        orphan_suggestions = {}
        for tn in table_names:
            unique = []
            for f in table_data[tn]["fields"]:
                if f == key_field: continue
                # 检查是否被映射合并（已在 field_conflicts 中）
                in_conflict = False
                for c in field_conflicts:
                    if f in c["fields"]:
                        in_conflict = True; break
                # 检查其他表是否有同名字段（自动合并）
                same_in_other = False
                for ot in table_names:
                    if ot == tn: continue
                    if f in table_data[ot]["fields"]:
                        same_in_other = True; break
                if not in_conflict and not same_in_other:
                    unique.append(f)
            if unique:
                orphan_suggestions[tn] = unique
        return jsonify({"code": 0, "data": {
            "headers": merged_headers,
            "rows": merged_rows[:100],
            "total": len(merged_rows),
            "warnings": text_warnings,
            "field_conflicts": field_conflicts,
            "orphan_fields": orphan_suggestions  # 每张表独有的字段
        }})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"汇总失败: {str(e)}"})


@app.route("/api/aggregate/create", methods=["POST"])
def api_aggregate_create():
    """创建汇总表，并自动建立汇总表与各源表的映射"""
    d = request.get_json()
    if not d: return jsonify({"code": 1, "msg": "请求为空"})
    new_name = (d.get("new_name") or "").strip()
    if not new_name: return jsonify({"code": 1, "msg": "请填写新表名"})
    headers = d.get("headers", [])
    rows = d.get("rows", [])
    source_tables = d.get("tables", [])
    key_field = (d.get("key_field") or "").strip()
    if not headers or not rows:
        return jsonify({"code": 1, "msg": "无数据"})
    try:
        from db import create_table_from_data, get_schema
        ok, msg = create_table_from_data(headers, rows, new_name)
        if not ok:
            return jsonify({"code": 1, "msg": msg})
        _save_table_manifest()
        # 自动建立汇总表与各源表的同步映射
        mappings = _load_m()
        agg_fields = [s["field"] for s in get_schema(new_name) if s["field"] not in ("id", "_deleted")]
        # 收集源表之间的映射关系，用于处理不同名但映射过的字段
        src_pairs = {}  # { (st, tt) : { st_field: tt_field } }
        for mp in mappings:
            if mp["st"] in source_tables and mp["tt"] in source_tables:
                k = (mp["st"], mp["tt"])
                src_pairs[k] = {p["s"]: p["t"] for p in mp["ps"]}
        for st in source_tables:
            src_schema = get_schema(st)
            if not src_schema: continue
            src_fields = [s["field"] for s in src_schema if s["field"] not in ("id", "_deleted")]
            pairs = []
            # 为 agg_fields 中的每个字段找对应
            for f in agg_fields:
                if f in src_fields:
                    # 同名字段直接映射
                    pairs.append({"s": f, "t": f})
                else:
                    # 不同名：检查是否有源表间的映射关系能关联
                    for (t1, t2), sm in src_pairs.items():
                        # 情况1：st 是 t1（源），f 映射到了 t2 的某个字段
                        if st == t1:
                            for src_f, tgt_f in sm.items():
                                if tgt_f == f and src_f in agg_fields:
                                    pairs.append({"s": src_f, "t": src_f})
                                    break
                        # 情况2：st 是 t2（目标表），t1 的 src_f 映射到 st 的 tgt_f
                        # 汇总表的 f == src_f → B表字段 tgt_f 应映射到汇总表字段 f
                        if st == t2:
                            for src_f, tgt_f in sm.items():
                                if src_f == f:
                                    # tgt_f 是 B 表中的字段名，f 是汇总表中的字段名
                                    pairs.append({"s": tgt_f, "t": f})
                                    break
            if pairs:
                # 去重
                seen = set()
                deduped = []
                for p in pairs:
                    k = p["s"] + ":" + p["t"]
                    if k not in seen:
                        seen.add(k); deduped.append(p)
                mappings.append({"st": st, "tt": new_name, "kf": key_field, "ps": deduped})
        _save_m(mappings)
        # 设置汇总表的关键字段与源表一致
        if key_field:
            km = _load_kf()
            km[new_name] = key_field
            _save_kf(km)
        return jsonify({"code": 0, "msg": msg, "table_name": new_name})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"创建汇总表失败: {str(e)}"})


# ========== 单表分类汇总 ==========

@app.route("/api/table/<table_name>/group-summary", methods=["POST"])
def api_group_summary(table_name):
    """按指定字段分组汇总，结果存为新表
    POST /api/table/<table_name>/group-summary
    参数: {"group_field": "分组字段", "aggregations": [{"field": "字段", "type": "count|sum", "alias": "别名"}], "title": "新表名"}
    """
    d = request.get_json()
    gf = (d.get("group_field") or "").strip()
    aggs = d.get("aggregations") or d.get("aggs") or []  # [{field, type: "count"|"sum", alias}]
    title = (d.get("title") or "").strip()
    if not gf: return jsonify({"code": 1, "msg": "请选择分组字段"})
    if not aggs: return jsonify({"code": 1, "msg": "请添加至少一个汇总项"})
    schema = get_schema(table_name)
    fields = {s["field"]: s["type"] for s in schema}
    if gf not in fields: return jsonify({"code": 1, "msg": f"分组字段 '{gf}' 不在表中"})
    # 构建 SQL
    selects = [f"`{gf}`"]
    col_defs = [{"name": gf, "type": "VARCHAR(255)"}]
    agg_headers = [gf]
    for a in aggs:
        fld = (a.get("field") or "").strip()
        tp = (a.get("type") or "count").strip().lower()
        alias = (a.get("alias") or f"{fld}_{tp}").strip()
        if fld not in fields: return jsonify({"code": 1, "msg": f"汇总字段 '{fld}' 不在表中"})
        if tp == "count":
            selects.append(f"COUNT(`{fld}`) AS `{alias}`")
            col_defs.append({"name": alias, "type": "INT"})
        elif tp == "sum":
            selects.append(f"COALESCE(SUM(`{fld}`),0) AS `{alias}`")
            col_defs.append({"name": alias, "type": "DECIMAL(15,2)"})
        else:
            return jsonify({"code": 1, "msg": f"不支持的汇总类型 '{tp}'，仅支持 count/sum"})
        agg_headers.append(alias)
    sql = f"SELECT {', '.join(selects)} FROM `{table_name}` GROUP BY `{gf}` ORDER BY `{gf}`"
    rows = query(sql)
    if rows is None: return jsonify({"code": 1, "msg": "查询失败"})
    # 建新表
    tn = _safe_tablename(title) if title else f"分类汇总_{uuid.uuid4().hex[:6]}"
    # 先建空表
    ok, msg = create_empty_table(tn, columns=col_defs)
    if not ok: return jsonify({"code": 1, "msg": msg})
    # 插入数据（列名用 _safe_colname 统一处理，避免特殊字符不匹配）
    from db import _safe_colname as _sc
    safe_headers = [_sc(h) for h in agg_headers]
    placeholders = ", ".join(["%s"] * len(safe_headers))
    col_names = ", ".join([f"`{h}`" for h in safe_headers])
    try:
        for row in rows:
            rv = [row.get(h) if isinstance(row, dict) else row[i] for i, h in enumerate(agg_headers)]
            execute(f"INSERT INTO `{tn}` ({col_names}) VALUES ({placeholders})", rv)
    except Exception as e:
        execute(f"DROP TABLE IF EXISTS `{tn}`")
        return jsonify({"code": 1, "msg": f"写入数据失败: {e}"})
    db_execute(f"ALTER TABLE `{tn}` COMMENT = %s", (title or f"按{gf}分类汇总",))
    _save_table_manifest()
    # 记录汇总来源
    agg = _load_agg()
    sfs = [a.get("field","") for a in aggs]
    agg[tn] = {"source": table_name, "group_field": gf, "sum_fields": sfs}
    _save_agg(agg)
    n = len(rows)
    return jsonify({"code": 0, "msg": f"分类汇总表创建成功，共 {n} 条记录", "table_name": tn})


# ========== 上传 ==========

# ========== 备份与恢复 ==========

@app.route("/api/backup/list", methods=["GET"])
def api_backup_list():
    """列出 _backup/ 目录下的所有备份"""
    try:
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        files = []
        for fn in os.listdir(_BACKUP_DIR):
            if fn.endswith(".json") and fn != "_manifest.json":
                path = os.path.join(_BACKUP_DIR, fn)
                try:
                    with open(path, encoding="utf-8") as f:
                        meta = json.load(f)
                    files.append({
                        "filename": fn,
                        "table": meta.get("table", fn),
                        "backup_at": meta.get("backup_at", ""),
                        "rows": len(meta.get("rows", [])),
                        "size": os.path.getsize(path)
                    })
                except:
                    # 跳过损坏的备份文件
                    continue
        files.sort(key=lambda x: x["backup_at"], reverse=True)
        return jsonify({"code": 0, "data": files, "manifest_exists": os.path.exists(os.path.join(_BACKUP_DIR, "_manifest.json"))})
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/backup/restore", methods=["POST"])
def api_backup_restore():
    """从备份文件恢复一张表"""
    d = request.get_json()
    filename = (d or {}).get("filename", "")
    if not filename: return jsonify({"code": 1, "msg": "备份文件名为空"})
    path = os.path.join(_BACKUP_DIR, filename)
    if not os.path.exists(path): return jsonify({"code": 1, "msg": "备份文件不存在"})
    try:
        with open(path, encoding="utf-8") as f:
            bk = json.load(f)
        tn = bk["table"]
        # 如果表已存在，先备份再删
        schema = get_schema(tn)
        if schema:
            _backup_table(tn)
            drop_table(tn)
        # 重建表
        col_defs = []
        for s in bk["schema"]:
            if s["field"] == "id": continue
            col_defs.append(f"`{s['field']}` {s['type']} NULL")
        sql = f"CREATE TABLE `{tn}` (`id` INT NOT NULL AUTO_INCREMENT, {', '.join(col_defs)}, PRIMARY KEY (`id`)) "
        execute(sql)
        # 恢复数据
        fields = [s["field"] for s in bk["schema"] if s["field"] != "id"]
        if bk["rows"]:
            ph = ", ".join(["%s"] * len(fields))
            fl = ", ".join([f"`{f}`" for f in fields])
            for row in bk["rows"]:
                vals = [row.get(f) for f in fields]
                try:
                    execute(f"INSERT INTO `{tn}` ({fl}) VALUES ({ph})", vals)
                except: pass
        _save_table_manifest()
        return jsonify({"code": 0, "msg": f"表 `{tn}` 已恢复，共 {len(bk['rows'])} 条记录"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"恢复失败: {str(e)}"})


@app.route("/api/backup/delete", methods=["POST"])
def api_backup_delete():
    """删除一个或多个备份文件"""
    d = request.get_json()
    filenames = d.get("filenames", [])
    if not filenames: return jsonify({"code": 1, "msg": "请指定要删除的备份文件"})
    deleted = 0
    for fn in filenames:
        path = os.path.join(_BACKUP_DIR, fn)
        try:
            if os.path.exists(path) and fn.endswith(".json"):
                os.unlink(path)
                deleted += 1
        except: pass
    return jsonify({"code": 0, "msg": f"已删除 {deleted} 个备份文件"})


# ========== 数据库整体导出/导入 ==========

@app.route("/api/database/overview", methods=["GET"])
def api_db_overview():
    """返回数据库概览：所有表名、行数、隐藏/删除数、字段数"""
    try:
        from db import get_tables, get_schema, get_pk_column, query
        tables = get_tables()
        result = []
        for t in tables:
            name = t["name"]
            comment = t.get("comment", "")
            schema = get_schema(name)
            pk = get_pk_column(name) or "id"
            # 统计行数
            cnt = query_one(f"SELECT COUNT(*) AS c FROM `{name}`")["c"]
            # 统计隐藏和表删除
            hidden = 0; deleted = 0
            if any(s["field"] == "_deleted" for s in schema):
                deleted = query_one(f"SELECT COUNT(*) AS c FROM `{name}` WHERE `_deleted`=2")["c"]
                hidden = query_one(f"SELECT COUNT(*) AS c FROM `{name}` WHERE `_deleted`=1")["c"]
            result.append({
                "name": name,
                "comment": comment,
                "columns": len([s for s in schema if s["field"] not in ("id", "_deleted")]),
                "total_rows": cnt,
                "hidden_rows": hidden,
                "deleted_rows": deleted,
                "pk": pk,
            })
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})

@app.route("/api/database/export", methods=["GET"])
def api_db_export():
    """导出整个数据库为单一 JSON 文件"""
    try:
        from db import export_all_tables
        data = {
            "version": 2,
            "exported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "database": "data_ledger",
            "tables": export_all_tables(),
            "configs": {
                "key_fields": _load_kf(),
                "mappings": _load_m(),
                "groups": _load_g(),
            }
        }
        from io import BytesIO
        buf = BytesIO()
        buf.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        buf.seek(0)
        filename = f"数据台账系统_备份_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        return send_file(buf, download_name=filename, as_attachment=True,
                        mimetype="application/json")
    except Exception as e:
        return jsonify({"code": 1, "msg": f"导出失败: {str(e)}"})


def _import_db_json(data):
    """从 JSON dict 恢复整个数据库（内部复用）"""
    from db import import_tables
    ok, fail, errors = import_tables(data["tables"], drop_existing=True)
    if "configs" in data:
        cfg = data["configs"]
        if "key_fields" in cfg and isinstance(cfg["key_fields"], dict):
            _save_kf(cfg["key_fields"])
        if "mappings" in cfg and isinstance(cfg["mappings"], list):
            _save_m(cfg["mappings"])
        if "groups" in cfg and isinstance(cfg["groups"], list):
            _save_g(cfg["groups"])
    _save_table_manifest()
    return ok, fail, errors


@app.route("/api/database/import", methods=["POST"])
def api_db_import():
    """从 JSON 文件导入恢复整个数据库"""
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"code": 1, "msg": "请选择文件"})
    if not file.filename.endswith(".json"):
        return jsonify({"code": 1, "msg": "请选择 .json 备份文件"})
    try:
        content = file.read().decode("utf-8")
        data = json.loads(content)
    except Exception as e:
        return jsonify({"code": 1, "msg": f"文件解析失败: {e}"})

    if not isinstance(data, dict) or "tables" not in data:
        return jsonify({"code": 1, "msg": "无效的备份文件格式"})

    ok, fail, errors = _import_db_json(data)
    msg = f"成功恢复 {ok} 张表"
    if fail:
        msg += f"，{fail} 张表失败"
    result = {"code": 0, "msg": msg, "ok": ok, "fail": fail}
    if errors:
        result["errors"] = errors
    return jsonify(result)


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
                "sheets": {"Sheet1": {"raw_rows": raw}}, "current_sheet": "Sheet1",
                "header_row_start": 1, "header_row_end": hr}
            _recalc(sid); s = _upload_cache[sid]["sheets"]["Sheet1"]
            return jsonify({"code": 0, "data": {"session_id": sid, "sheets": ["Sheet1"],
                "filename": file.filename, "detected_title": dt,
                "headers": s["headers"], "total_rows": len(s["rows"]), "preview": s["rows"][:5],
                "header_row_start": 1, "header_row_end": hr}})
        else:
            _upload_cache[sid] = {"path": tmp.name, "type": "excel", "filename": file.filename}
            ns, ra = _parse_excel_raw(tmp.name)
            dt = ""; hr = 1
            if ns and ra and len(ra[0]) > 1:
                ne = [c for c in ra[0][0] if c is not None and str(c).strip()]
                if len(ne) <= 2 and ne and len(str(ne[0])) > 2 and len([c for c in ra[0][1] if c is not None and str(c).strip()]) > 2:
                    dt = str(ne[0]).strip(); hr = 2
            _upload_cache[sid]["sheets"] = {n: {"raw_rows": r} for n, r in zip(ns, ra)}
            _upload_cache[sid]["current_sheet"] = ns[0];
            _upload_cache[sid]["header_row_start"] = 1; _upload_cache[sid]["header_row_end"] = hr
            _recalc(sid); s = _upload_cache[sid]["sheets"][ns[0]]
            return jsonify({"code": 0, "data": {"session_id": sid, "sheets": ns,
                "filename": file.filename, "detected_title": dt,
                "headers": s["headers"], "total_rows": len(s["rows"]), "preview": s["rows"][:5],
                "header_row_start": 1, "header_row_end": hr}})
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
    d = request.get_json(); sid = d.get("session_id")
    if sid not in _upload_cache: return jsonify({"code": 1, "msg": "过期"})
    start = int(d.get("header_row_start", 1))
    end = int(d.get("header_row_end", start))
    _upload_cache[sid]["header_row_start"] = max(1, start)
    _upload_cache[sid]["header_row_end"] = max(start, end)
    _recalc(sid)
    s = _upload_cache[sid]["sheets"][_upload_cache[sid]["current_sheet"]]
    return jsonify({"code": 0, "data": {"headers": s["headers"], "total_rows": len(s["rows"]), "preview": s["rows"][:5]}})


def _recalc(sid):
    c = _upload_cache[sid]; sn = c["current_sheet"]; raw = c["sheets"][sn]["raw_rows"]
    rs = max(1, min(c.get("header_row_start", 1), len(raw)))
    re = max(rs, min(c.get("header_row_end", 1), len(raw)))
    n = re - rs + 1
    hrows = [list(r) for r in raw[rs-1:re]]; drows = raw[re:]
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
    tn = _safe_tablename(title) if title else f"imported_{uuid.uuid4().hex[:6]}"
    if not flt:
        # 无数据行 → 创建空表（只有字段名，没有数据）
        from db import create_empty_table as cet
        columns = [{"name": h, "type": "VARCHAR(255)"} for h in uh]
        ok, msg = cet(tn, columns=columns)
        _cleanup(sid)
        if ok:
            db_execute(f"ALTER TABLE `{tn}` COMMENT = %s", (title or tn,))
            _save_table_manifest()
            kf_map = _load_kf(); kf_map[tn] = kf; _save_kf(kf_map)
            msg += f"（空表，已建 {len(uh)} 个字段）"
        return jsonify({"code": 0 if ok else 1, "msg": msg, "table_name": tn})
    ok, msg = create_table_from_data(uh, flt, tn); _cleanup(sid)
    if ok:
        db_execute(f"ALTER TABLE `{tn}` COMMENT = %s", (title or tn,))
        _save_table_manifest()
        kf_map = _load_kf(); kf_map[tn] = kf; _save_kf(kf_map)
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


def _has_data(rows):
    """检查 sheet 是否有至少一行有效数据"""
    for row in rows:
        for cell in row:
            if cell is not None and str(cell).strip():
                return True
    return False

def _parse_excel_raw(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        import xlrd; wb = xlrd.open_workbook(path); ns = wb.sheet_names()
        ra = [[[ws.cell_value(r,c) for c in range(ws.ncols)] for r in range(ws.nrows)] for ws in [wb.sheet_by_name(n) for n in ns]]
        pairs = [(n, r) for n, r in zip(ns, ra) if _has_data(r)]
        return [p[0] for p in pairs], [p[1] for p in pairs]
    elif ext == ".et":
        try:
            from openpyxl import load_workbook
            wb = load_workbook(filename=path, read_only=True); ns = wb.sheetnames
            ra = [list(ws.iter_rows(values_only=True)) for ws in [wb[n] for n in ns]]
            wb.close()
            ra2 = [list(r) for r in ra]
            pairs = [(n, r) for n, r in zip(ns, ra2) if _has_data(r)]
            return [p[0] for p in pairs], [p[1] for p in pairs]
        except:
            import xlrd
            wb = xlrd.open_workbook(path); ns = wb.sheet_names()
            ra = [[[ws.cell_value(r,c) for c in range(ws.ncols)] for r in range(ws.nrows)] for ws in [wb.sheet_by_name(n) for n in ns]]
            pairs = [(n, r) for n, r in zip(ns, ra) if _has_data(r)]
            return [p[0] for p in pairs], [p[1] for p in pairs]
    else:
        try:
            from openpyxl import load_workbook
            wb = load_workbook(filename=path, read_only=True); ns = wb.sheetnames
            ra = [list(ws.iter_rows(values_only=True)) for ws in [wb[n] for n in ns]]
            wb.close()
            ra2 = [list(r) for r in ra]
            pairs = [(n, r) for n, r in zip(ns, ra2) if _has_data(r)]
            return [p[0] for p in pairs], [p[1] for p in pairs]
        except Exception:
            import xlrd
            wb = xlrd.open_workbook(path); ns = wb.sheet_names()
            ra = [[[ws.cell_value(r,c) for c in range(ws.ncols)] for r in range(ws.nrows)] for ws in [wb.sheet_by_name(n) for n in ns]]
            pairs = [(n, r) for n, r in zip(ns, ra) if _has_data(r)]
            return [p[0] for p in pairs], [p[1] for p in pairs]


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
    print("="*50); print("数据台账系统"); print(f"  地址: http://127.0.0.1:5000"); print("="*50)
    app.run(host="0.0.0.0", port=5000, debug=True)

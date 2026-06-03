"""
鏁版嵁鍙拌处绯荤粺 鈥?Web 琛ㄦ牸娴忚鏈嶅姟
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
_BACKUP_DIR = os.path.join(_DATA_DIR, "_backup")
_DEL_TOKEN = os.urandom(8).hex()  # 姣忔鍚姩闅忔満鐢熸垚锛屽彧鏈夐〉闈㈢煡閬?

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


# 鈹€鈹€ 鑷姩澶囦唤 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
def _to_json_safe(v):
    """灏嗕笉鍙?JSON 搴忓垪鍖栫殑绫诲瀷杞负 float"""
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
    """鍒犺〃鍓嶈嚜鍔ㄥ浠藉埌 _backup/ 鐩綍"""
    try:
        schema = get_schema(table_name)
        if not schema: return
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        pk = get_pk_column(table_name) or "id"
        rows = query(f"SELECT * FROM `{table_name}` ORDER BY `{pk}`")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r'[\\/:*?"<>|]', '_', table_name)
        path = os.path.join(_BACKUP_DIR, f"{safe}_{ts}.json")
        # 澶囦唤鍒颁复鏃舵枃浠跺啀閲嶅懡鍚嶏紝閬垮厤鍐欎竴鍗婂穿婧冪暀娈嬫枃浠?        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({
                "table": table_name,
                "backup_at": ts,
                "schema": schema,
                "rows": [{k: _to_json_safe(v) for k, v in row.items()} for row in rows]
            }, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"[backup] {table_name} 澶囦唤澶辫触: {e}")
        try: os.unlink(tmp_path)
        except: pass


def _save_table_manifest():
    """寤鸿〃/瀵艰〃鍚庤褰曡〃缁撴瀯鍒?manifest"""
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
    """鏂板缓绌鸿〃锛堟墜鍔紝闈炲鍏ワ級"""
    d = request.get_json()
    if not d or not d.get("name"):
        return jsonify({"code": 1, "msg": "琛ㄥ悕涓虹┖"})
    name = d["name"].strip()
    if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', name):
        return jsonify({"code": 1, "msg": "琛ㄥ悕鍙厑璁稿瓧姣嶃€佹暟瀛椼€佷笅鍒掔嚎鍜屼腑鏂?})
    if len(name) > 64:
        return jsonify({"code": 1, "msg": "琛ㄥ悕涓嶈兘瓒呰繃64涓瓧绗?})
    columns = d.get("columns", [])
    for col in columns:
        cn = col.get("name", "").strip()
        if not cn:
            return jsonify({"code": 1, "msg": "瀛楁鍚嶄笉鑳戒负绌?})
        if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', cn):
            return jsonify({"code": 1, "msg": f"瀛楁鍚嶃€寋cn}銆嶅彧鍏佽瀛楁瘝銆佹暟瀛椼€佷笅鍒掔嚎鍜屼腑鏂?})
    key_field = d.get("key_field", "").strip()
    if key_field and not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', key_field):
        return jsonify({"code": 1, "msg": "鍏抽敭瀛楁鍚嶅彧鍏佽瀛楁瘝銆佹暟瀛椼€佷笅鍒掔嚎鍜屼腑鏂?})
    try:
        ok, msg = create_empty_table(name, columns)
        if ok:
            if key_field:
                kf_map = _load_kf()
                kf_map[name] = key_field
                _save_kf(kf_map)
            _save_table_manifest()
            return jsonify({"code": 0, "msg": msg + (f"锛屽叧閿瓧娈? {key_field}" if key_field else "")})
        else:
            return jsonify({"code": 1, "msg": msg})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"寤鸿〃澶辫触: {str(e)}"})

# ========== 琛ㄥ垎缁?==========

@app.route("/api/table-groups", methods=["GET"])
def api_get_groups():
    return jsonify({"code": 0, "data": _load_g()})

@app.route("/api/table-groups", methods=["POST"])
def api_save_groups():
    d = request.get_json()
    if not d or "groups" not in d: return jsonify({"code": 1, "msg": "鍙傛暟涓虹┖"})
    _save_g(d["groups"])
    return jsonify({"code": 0, "msg": f"宸蹭繚瀛?{len(d['groups'])} 涓垎缁?})


# ========== 鍏抽敭瀛楁 ==========

@app.route("/api/table/<table_name>/key-field", methods=["GET"])
def api_get_key_field(table_name):
    kf = _load_kf().get(table_name, "")
    return jsonify({"code": 0, "data": {"key_field": kf}})

@app.route("/api/table/<table_name>/key-field", methods=["PUT"])
def api_set_key_field(table_name):
    d = request.get_json()
    kf = (d or {}).get("key_field", "").strip()
    sch = get_schema(table_name)
    if not sch: return jsonify({"code": 1, "msg": "琛ㄤ笉瀛樺湪"})
    if kf and kf not in [s["field"] for s in sch]:
        return jsonify({"code": 1, "msg": f"瀛楁 `{kf}` 涓嶅瓨鍦ㄤ簬琛ㄤ腑"})
    km = _load_kf()
    if kf:
        km[table_name] = kf
    else:
        km.pop(table_name, None)
    _save_kf(km)
    return jsonify({"code": 0, "msg": f"鍏抽敭瀛楁宸茶缃负 `{kf}`" if kf else "鍏抽敭瀛楁宸叉竻闄?})


@app.route("/api/table/<table_name>", methods=["DELETE"])
def api_delete_table(table_name):
    try:
        # 瀹夊叏闃叉姢锛氭湁鏁版嵁鐨勮〃蹇呴』浼犳纭殑鍒犻櫎浠ょ墝锛堜粠椤甸潰鑾峰彇锛夋墠鑳藉垹闄?        d = request.get_json(silent=True) or {}
        token = d.get("del_token", "") if isinstance(d, dict) else ""
        if token != _DEL_TOKEN:
            return jsonify({"code": 1, "msg": "鎷掔粷鍒犻櫎缂哄皯鏈夋晥鐨勫垹闄や护鐗岋紙浠呴〉闈?UI 鍙墽琛屽垹闄ゆ搷浣滐級"})
        _backup_table(table_name)
        km = _load_kf(); km.pop(table_name, None); _save_kf(km)
        drop_table(table_name)
        _save_table_manifest()
        return jsonify({"code": 0, "msg": "宸插垹闄わ紙宸插浠藉埌 _backup/锛?})
    except Exception as e: return jsonify({"code": 1, "msg": f"鍒犻櫎澶辫触: {str(e)}"})


@app.route("/api/table/<table_name>", methods=["PUT"])
def api_rename_table(table_name):
    d = request.get_json(); nn = (d or {}).get("new_name","")
    if not nn.strip(): return jsonify({"code": 1, "msg": "鏂拌〃鍚嶄负绌?})
    nn = nn.strip()
    if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', nn):
        return jsonify({"code": 1, "msg": "琛ㄥ悕鍙厑璁稿瓧姣嶃€佹暟瀛椼€佷笅鍒掔嚎鍜屼腑鏂?})
    if len(nn) > 64: return jsonify({"code": 1, "msg": "琛ㄥ悕涓嶈兘瓒呰繃64涓瓧绗?})
    if nn == table_name: return jsonify({"code": 0, "msg": "鏈敼鍙?})
    try:
        rename_table(table_name, nn)
        set_table_comment(nn, nn)
        km = _load_kf()
        if table_name in km:
            km[nn] = km.pop(table_name)
            _save_kf(km)
        return jsonify({"code": 0, "msg": f"宸查噸鍛藉悕涓?`{nn}`"})
    except Exception as e: return jsonify({"code": 1, "msg": f"閲嶅懡鍚嶅け璐? {str(e)}"})


@app.route("/api/table/<table_name>/column", methods=["PUT"])
def api_rename_column(table_name):
    d = request.get_json(); old = (d or {}).get("old",""); nn = (d or {}).get("new","")
    if not old or not nn: return jsonify({"code": 1, "msg": "鍙傛暟涓嶅叏"})
    if nn.lower() == "id": return jsonify({"code": 1, "msg": "id 瀛楁涓嶈兘淇敼"})
    try:
        rename_column(table_name, old, nn)
        # 鏇存柊鎵€鏈夋槧灏勪腑鐨勫瓧娈靛悕
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
        return jsonify({"code": 0, "msg": "瀛楁宸查噸鍛藉悕锛岀浉鍏虫槧灏勫凡鏇存柊"})
    except Exception as e: return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/table/<table_name>/dedup", methods=["POST"])
def api_dedup(table_name):
    """瀵瑰叧閿瓧娈垫煡閲?    POST body: {"preview": true}  鈫?棰勮閲嶅璁板綍锛堜笉鍒犻櫎锛?    POST body: {}                 鈫?鎵ц鍒犻櫎锛堜繚鐣欐瘡缁処D鏈€灏忕殑锛?    """
    kf = _load_kf().get(table_name, "")
    if not kf:
        return jsonify({"code": 1, "msg": "璇峰厛璁剧疆鍏抽敭瀛楁"})
    schema = get_schema(table_name)
    all_fields = [s["field"] for s in schema]
    if kf not in all_fields:
        return jsonify({"code": 1, "msg": f"瀛楁 `{kf}` 宸蹭笉瀛樺湪"})
    pk = get_pk_column(table_name) or "id"
    has_del = "_deleted" in all_fields
    del_cond = "AND IFNULL(`_deleted`,0)!=1" if has_del else ""
    d = request.get_json(silent=True) or {}
    preview = d.get("preview", False)
    try:
        if preview:
            # 鈹€鈹€ 棰勮妯″紡锛氭煡鍑洪噸澶嶈褰曪紝涓嶅垹 鈹€鈹€
            rows = query(f"SELECT * FROM `{table_name}` WHERE 1=1 {del_cond} ORDER BY `{kf}`,`{pk}`")
            # 鍒嗙粍鎵惧嚭閲嶅鐨?            groups = []  # [{key_value, records: [{id, fields}], keep_id, del_ids}]
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
                    # 淇濈暀ID鏈€灏忕殑锛屽叾浣欐爣璁颁负鍒犻櫎
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
            # 鈹€鈹€ 鎵ц鍒犻櫎 鈹€鈹€
            deleted = execute(f"DELETE t1 FROM `{table_name}` t1 INNER JOIN `{table_name}` t2 WHERE t1.`{kf}`=t2.`{kf}` AND t1.`{pk}`>t2.`{pk}`")
            return jsonify({"code": 0, "msg": f"宸插垹闄?{deleted} 鏉￠噸澶嶈褰?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鍘婚噸澶辫触: {e}"})

@app.route("/api/table/<table_name>/row", methods=["POST"])
def api_add_row(table_name):
    """鎻掑叆涓€鏉＄┖璁板綍"""
    pk = get_pk_column(table_name)
    schema = get_schema(table_name)
    fields = [s["field"] for s in schema if s["field"] != pk and s["field"] != "_deleted"]
    if not fields: return jsonify({"code": 1, "msg": "鏃犲彲鐢ㄥ瓧娈?})
    cols = ", ".join([f"`{f}`" for f in fields])
    try:
        from db import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"INSERT INTO `{table_name}` ({cols}) VALUES ({', '.join(['NULL']*len(fields))})")
                conn.commit()
                new_id = cur.lastrowid
            return jsonify({"code": 0, "msg": "宸叉坊鍔?, "id": new_id})
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"code": 1, "msg": f"娣诲姞澶辫触: {e}"})

@app.route("/api/table/<table_name>/row/<int:row_id>", methods=["DELETE"])
def api_delete_row(table_name, row_id):
    """鍒犻櫎鎸囧畾琛岋紙绾ц仈鍒犻櫎鍏宠仈琛ㄥ悓鍏抽敭瀛楁鍊肩殑璁板綍锛?""
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
        msg = "宸插垹闄?
        if del_cnt: msg += f"锛堢骇鑱斿垹闄?{del_cnt} 鏉″叧鑱旇褰曪級"
        return jsonify({"code": 0, "msg": msg})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鍒犻櫎澶辫触: {e}"})

@app.route("/api/table/<table_name>/row/<int:row_id>/hide", methods=["POST"])
def api_hide_row(table_name, row_id):
    """闅愯棌琛岋細鍏抽敭瀛楁涓虹┖鍒欑‖鍒犻櫎锛屽惁鍒欒蒋鍒犻櫎"""
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
            return jsonify({"code": 0, "msg": "宸插垹闄わ紙鍏抽敭瀛楁涓虹┖锛?})
        schema = get_schema(table_name)
        if not any(s["field"] == "_deleted" for s in schema):
            execute(f"ALTER TABLE `{table_name}` ADD COLUMN `_deleted` TINYINT DEFAULT 0")
        execute(f"UPDATE `{table_name}` SET `_deleted`=1 WHERE `id`=%s", (row_id,))
        return jsonify({"code": 0, "msg": "宸查殣钘?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"闅愯棌澶辫触: {e}"})


@app.route("/api/table/<table_name>/rows/hide", methods=["POST"])
def api_hide_rows(table_name):
    """鎵归噺闅愯棌澶氳"""
    d = request.get_json()
    ids = d.get("ids", [])
    if not ids: return jsonify({"code": 1, "msg": "璇锋寚瀹氳闅愯棌鐨勮"})
    try:
        schema = get_schema(table_name)
        if not any(s["field"] == "_deleted" for s in schema):
            execute(f"ALTER TABLE `{table_name}` ADD COLUMN `_deleted` TINYINT DEFAULT 0")
        ph = ",".join(["%s"] * len(ids))
        execute(f"UPDATE `{table_name}` SET `_deleted`=1 WHERE `id` IN ({ph})", ids)
        return jsonify({"code": 0, "msg": f"宸查殣钘?{len(ids)} 琛?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鎵归噺闅愯棌澶辫触: {e}"})


@app.route("/api/table/<table_name>/rows/unhide", methods=["POST"])
def api_unhide_rows(table_name):
    """鎭㈠闅愯棌鐨勮"""
    d = request.get_json()
    ids = d.get("ids", [])
    try:
        if ids:
            ph = ",".join(["%s"] * len(ids))
            execute(f"UPDATE `{table_name}` SET `_deleted`=0 WHERE `id` IN ({ph})", ids)
        else:
            execute(f"UPDATE `{table_name}` SET `_deleted`=0 WHERE `_deleted`=1")
        return jsonify({"code": 0, "msg": "宸叉仮澶?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鎭㈠澶辫触: {e}"})


@app.route("/api/table/<table_name>/row/<int:row_id>/table-delete", methods=["POST"])
def api_table_delete_row(table_name, row_id):
    """琛ㄥ垹闄わ細浠庡綋鍓嶈〃瑙嗗浘绉婚櫎锛屼繚鐣?DB 璁板綍锛坃deleted=2锛屼笉鍦ㄩ殣钘忓垪琛ㄦ樉绀猴級"""
    try:
        schema = get_schema(table_name)
        if not any(s["field"] == "_deleted" for s in schema):
            execute(f"ALTER TABLE `{table_name}` ADD COLUMN `_deleted` TINYINT DEFAULT 0")
        execute(f"UPDATE `{table_name}` SET `_deleted`=2 WHERE `id`=%s", (row_id,))
        return jsonify({"code": 0, "msg": "宸蹭粠鏈〃绉婚櫎"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"琛ㄥ垹闄ゅけ璐? {e}"})


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
        # 璁＄畻姣忔潯闅愯棌琛屽湪榛樿 id 鎺掑簭涓嬬殑搴忓彿
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
    """鑾峰彇琛ㄥ垹闄ょ殑璁板綍锛坃deleted=2锛夛紝甯﹀簭鍙?""
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
    """杩斿洖琛ㄥ唴鎵€鏈夎褰曪紙鍚殣钘?琛ㄥ垹闄わ級锛屽甫鐘舵€佹爣璁?""
    try:
        schema = get_schema(table_name)
        has_del = any(s["field"] == "_deleted" for s in schema)
        rows = query(f"SELECT * FROM `{table_name}` ORDER BY `id`")
        for r in rows:
            r["_del_status"] = ""
            if has_del:
                dv = r.get("_deleted")
                if dv == 1: r["_del_status"] = "闅愯棌"
                elif dv == 2: r["_del_status"] = "琛ㄥ垹闄?
        return jsonify({"code": 0, "data": rows, "schema": schema})
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/table/<table_name>/rows/un-table-delete", methods=["POST"])
def api_un_table_delete_rows(table_name):
    """鎭㈠琛ㄥ垹闄ょ殑琛岋紙_deleted=2 鈫?0锛?""
    d = request.get_json()
    ids = d.get("ids", [])
    try:
        if ids:
            ph = ",".join(["%s"] * len(ids))
            execute(f"UPDATE `{table_name}` SET `_deleted`=0 WHERE `id` IN ({ph})", ids)
        else:
            execute(f"UPDATE `{table_name}` SET `_deleted`=0 WHERE `_deleted`=2")
        return jsonify({"code": 0, "msg": "宸叉仮澶?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鎭㈠澶辫触: {e}"})


# 鈹€鈹€ 鍒楅殣钘?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
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
    return jsonify({"code": 0, "msg": f"宸查殣钘?{len(cols)} 鍒?})

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
    return jsonify({"code": 0, "msg": "宸叉仮澶?})

@app.route("/api/table/<table_name>/hidden-cols", methods=["GET"])
def api_hidden_cols(table_name):
    hc = _load_hidden_cols()
    return jsonify({"code": 0, "data": hc.get(table_name, [])})


@app.route("/api/table/<table_name>/column", methods=["POST"])
def api_add_column(table_name):
    """鎻掑叆绌哄垪锛坅fter 鎸囧畾鍦ㄦ煇鍒椾箣鍚庯級"""
    d = request.get_json(); name = (d or {}).get("name","").strip()
    if not name: return jsonify({"code": 1, "msg": "鍒楀悕涓嶈兘涓虹┖"})
    if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', name):
        return jsonify({"code": 1, "msg": "鍒楀悕鍙厑璁稿瓧姣嶃€佹暟瀛椼€佷笅鍒掔嚎鍜屼腑鏂?})
    after = (d or {}).get("after","")
    try:
        sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{name}` VARCHAR(255) NULL"
        if after:
            sql += f" AFTER `{after}`"
        execute(sql)
        return jsonify({"code": 0, "msg": f"鍒?`{name}` 宸叉坊鍔?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"娣诲姞澶辫触: {e}"})

@app.route("/api/table/<table_name>/column/<column_name>/type", methods=["PATCH"])
def api_set_column_type(table_name, column_name):
    """淇敼鍒楁暟鎹被鍨嬶紙鍏堟竻娲楃┖涓诧紝鍐嶈浆鎹級"""
    d = request.get_json(); new_type = (d or {}).get("type","").strip()
    if not new_type: return jsonify({"code": 1, "msg": "绫诲瀷涓嶈兘涓虹┖"})
    if column_name.lower() == "id": return jsonify({"code": 1, "msg": "id 鍒椾笉鍏佽淇敼"})
    try:
        # 濡傛灉鏄暟鍊肩被鍨嬶紝鍏堟竻娲楅潪鏁板瓧鍊硷紝閬垮厤 "Data truncated" 閿欒
        nt_upper = new_type.upper()
        if any(kw in nt_upper for kw in ("DECIMAL", "INT", "DOUBLE", "FLOAT", "NUMERIC", "BIGINT", "SMALLINT", "TINYINT")):
            execute(f"UPDATE `{table_name}` SET `{column_name}`=NULL WHERE `{column_name}`='' OR `{column_name}` IS NULL")
        from db import alter_column_type
        alter_column_type(table_name, column_name, new_type)
        return jsonify({"code": 0, "msg": f"宸蹭慨鏀逛负 {new_type}"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"淇敼澶辫触: {e}"})


@app.route("/api/table/<table_name>/reorder-columns", methods=["PUT"])
def api_reorder_columns(table_name):
    """璋冩暣琛ㄥ瓧娈甸『搴?""
    d = request.get_json()
    new_order = (d or {}).get("columns", [])
    if not new_order:
        return jsonify({"code": 1, "msg": "璇锋彁渚涙柊瀛楁椤哄簭"})
    try:
        schema = get_schema(table_name)
        if not schema: return jsonify({"code": 1, "msg": "琛ㄤ笉瀛樺湪"})
        schema_fields = [s["field"] for s in schema if s["field"] not in ("id", "_deleted")]
        if set(new_order) != set(schema_fields):
            missing = set(schema_fields) - set(new_order)
            extra = set(new_order) - set(schema_fields)
            msg = "瀛楁涓嶅尮閰?
            if missing: msg += f"锛岀己灏? {missing}"
            if extra: msg += f"锛屽浣? {extra}"
            return jsonify({"code": 1, "msg": msg})
        # 閲嶅缓琛ㄥ疄鐜伴噸鎺掑簭锛歋QLite 涓嶆敮鎸?MODIFY COLUMN ... AFTER
        schema_map = {s["field"]: s["type"] for s in get_schema(table_name)}
        col_defs = ['"id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT']
        for fld in new_order:
            col_defs.append(f'"{fld}" {schema_map.get(fld, "VARCHAR(255)")}')
        data_cols = ", ".join(f'"{c}"' for c in new_order)
        tmp = f'"{table_name}_tmp_reorder"'
        safe = f'"{table_name}"'
        conn = _get_conn()
        try:
            conn.execute("BEGIN")
            conn.execute(f"CREATE TABLE {tmp} ({', '.join(col_defs)})")
            if new_order:
                conn.execute(f"INSERT INTO {tmp} ({data_cols}) SELECT {data_cols} FROM {safe}")
            conn.execute(f"DROP TABLE {safe}")
            conn.execute(f"ALTER TABLE {tmp} RENAME TO {safe}")
            conn.commit()
        except Exception:
            conn.rollback()
            try: conn.execute(f"DROP TABLE IF EXISTS {tmp}")
            except: pass
            raise
        finally:
            conn.close()
        return jsonify({"code": 0, "msg": "瀛楁椤哄簭宸茶皟鏁?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"璋冩暣澶辫触: {e}"})


@app.route("/api/table/<table_name>/column/<column_name>", methods=["DELETE"])
def api_delete_column(table_name, column_name):
    """鍒犻櫎鎸囧畾鍒?""
    if column_name.lower() == "id": return jsonify({"code": 1, "msg": "id 鍒椾笉鑳藉垹闄?})
    try:
        execute(f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`")
        return jsonify({"code": 0, "msg": f"鍒?`{column_name}` 宸插垹闄?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鍒犻櫎澶辫触: {e}"})

@app.route("/api/table/<table_name>/column/<column_name>/values")
def api_column_values(table_name, column_name):
    """鑾峰彇鏌愬垪鐨勬墍鏈夊敮涓€鍊硷紙鐢ㄤ簬绛涢€夊櫒锛夛紝鏀寔绾ц仈 filters"""
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
    """鎸夊瓧娈靛€兼煡鎵惧悓琛ㄥ凡鏈夎褰曪紙鐢ㄤ簬鑷姩琛ュ叏锛?""
    field = request.args.get("field"); value = request.args.get("value"); exclude = request.args.get("exclude", 0, type=int)
    if not field or value is None: return jsonify({"code": 1, "msg": "鍙傛暟涓嶅叏"})
    pk = get_pk_column(table_name) or "id"
    rows = query(f"SELECT * FROM `{table_name}` WHERE `{field}`=%s AND `{pk}`!=%s LIMIT 1", (value, exclude))
    if not rows: return jsonify({"code": 1, "msg": "鏈壘鍒板尮閰?})
    row = rows[0]
    if "_deleted" in row and row["_deleted"] == 1: return jsonify({"code": 1, "msg": "鏈壘鍒板尮閰?})
    return jsonify({"code": 0, "data": _serialize_rows([row])[0]})

@app.route("/api/table/<table_name>/record/<int:row_id>")
def api_view_record(table_name, row_id):
    """鏌ョ湅鏁版嵁搴撹褰曪紙鍚叧鑱旇〃淇℃伅锛夛紝鍒嗙粍杩斿洖"""
    pk = get_pk_column(table_name) or "id"
    curr = query_one(f"SELECT * FROM `{table_name}` WHERE `{pk}`=%s", (row_id,))
    if not curr: return jsonify({"code": 1, "msg": "璁板綍涓嶅瓨鍦?})
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
    """鎵归噺鏇存柊瀛楁鍊?""
    d = request.get_json()
    updates = d.get("updates", [])
    if not updates: return jsonify({"code": 1, "msg": "鏃犳洿鏂?})
    ok = 0; fails = []
    for u in updates:
        tbl, rid, fld, val = u.get("table"), u.get("id"), u.get("field"), u.get("value")
        if not tbl or not rid or not fld: fails.append({"msg": "鍙傛暟涓嶅叏", "update": u}); continue
        try:
            execute(f"UPDATE `{tbl}` SET `{fld}`=%s WHERE `id`=%s", (val, rid))
            ok += 1
        except Exception as e:
            fails.append({"msg": str(e), "update": u})
    return jsonify({"code": 0, "msg": f"鎴愬姛 {ok} 鏉? + (f", 澶辫触 {len(fails)} 鏉? if fails else ""), "fails": fails})

@app.route("/api/table/<table_name>/export")
def api_export_table(table_name):
    """瀵煎嚭琛ㄦ暟鎹负 Excel锛堝叕鏂囨牸寮忥細鏍囬+榛戜綋琛ㄥご+浠垮畫姝ｆ枃+鍏ㄦ绾?灞呬腑锛?""
    try:
        import openpyxl; from openpyxl.styles import Font, Alignment, Border, Side; from openpyxl.utils import get_column_letter; from io import BytesIO
        schema = get_schema(table_name)
        if not schema: return jsonify({"code": 1, "msg": "琛ㄤ笉瀛樺湪"})
        pk = get_pk_column(table_name) or "id"
        fields = [s["field"] for s in schema if s["field"] not in (pk, "_deleted")]
        # 鎺掗櫎闅愯棌鍒?        hidden_cols = _load_hidden_cols().get(table_name, [])
        if hidden_cols:
            fields = [f for f in fields if f not in hidden_cols]
        if not fields:
            return jsonify({"code": 1, "msg": "娌℃湁鍙鍑虹殑鍒?})
        # 璇诲彇绛涢€夋潯浠讹紙浠?URL query string锛夛紝浠呭鍑虹瓫閫夊悗鐨勮
        filters_json = request.args.get("filters", "")
        order_field = request.args.get("order_field", default=None, type=str)
        order_dir = request.args.get("order_dir", default="asc", type=str)
        # 鏋勫缓 WHERE
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
        # 鏋勫缓 ORDER BY
        order_sql = f"ORDER BY `{pk}`"
        if order_field and order_field in schema_fields:
            dir_sql = "DESC" if order_dir == "desc" else "ASC"
            order_sql = f"ORDER BY `{order_field}` {dir_sql}, `{pk}`"
        # 鎵ц鏌ヨ
        if has_where:
            where = " AND ".join(where_parts)
            rows = query(f"SELECT * FROM `{table_name}` WHERE {where} {order_sql}", params)
        else:
            rows = query(f"SELECT * FROM `{table_name}` {order_sql}")
        # 鏍囬锛氫娇鐢ㄨ〃娉ㄩ噴锛坈omment锛夛紝娌℃湁鍒欑敤琛ㄥ悕
        tables = get_tables()
        table_comment = {t["name"]: t["comment"] for t in tables}.get(table_name, "")
        title_text = table_comment or table_name
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = (table_name or "sheet")[:31]
        # 鈹€鈹€ 鍏枃鏍煎紡鏍峰紡 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        title_font   = Font(name="榛戜綋", size=16, bold=True)          # 涓夊彿榛戜綋
        hdr_font     = Font(name="榛戜綋", size=10.5, bold=True)         # 浜斿彿榛戜綋鍔犵矖
        body_font    = Font(name="浠垮畫", size=10.5)                     # 浜斿彿浠垮畫
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=False)
        thin_line    = Side(style="thin", color="000000")               # 0.5pt 榛戣壊瀹炵嚎
        thin_border  = Border(left=thin_line, right=thin_line, top=thin_line, bottom=thin_line)
        # 鈹€鈹€ 琛?1锛氭爣棰?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(fields))
        title_cell = ws.cell(1, 1, title_text)
        title_cell.font = title_font
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 36  # 鏍囬琛岄珮
        # 鈹€鈹€ 琛?2锛氳〃澶?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        for ci, f in enumerate(fields, 1):
            cell = ws.cell(2, ci, f)
            cell.font = hdr_font
            cell.alignment = center_align
            cell.border = thin_border
        ws.row_dimensions[2].height = 24
        # 鈹€鈹€ 鍐欐暟鎹?+ 鍒楀璁＄畻 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
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
        # 鈹€鈹€ 搴旂敤鍒楀 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        for ci in col_widths:
            ws.column_dimensions[get_column_letter(ci)].width = min(max(col_widths[ci] / 7 + 2, 8), 80)
        # 鈹€鈹€ 鎵撳嵃璁剧疆 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        last_row = ri - 1
        ws.print_area = f"A1:{get_column_letter(len(fields))}{last_row}"
        ws.page_setup.orientation = "landscape" if len(fields) > 6 else "portrait"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.page_margins.left = 0.5
        ws.page_margins.right = 0.5
        # 鍐荤粨鏍囬+琛ㄥご琛?        ws.freeze_panes = "A3"
        buf = BytesIO(); wb.save(buf); buf.seek(0)
        return send_file(buf, download_name=f"{table_name}.xlsx", as_attachment=True)
    except Exception as e:
        return jsonify({"code": 1, "msg": f"瀵煎嚭澶辫触: {e}"})

@app.route("/api/table/<table_name>", methods=["PATCH"])
def api_update_cell(table_name):
    """鏇存柊鍗曞厓鏍?    PATCH /api/table/<table_name>
    鍙傛暟: {"id": row_id, "field": "鍒楀悕", "value": "鏂板€?}
    鑷姩鍚屾鍒版槧灏勮〃涓悓鍏抽敭瀛楁鍊肩殑璁板綍銆?    """
    d = request.get_json()
    if not d: return jsonify({"code": 1, "msg": "璇锋眰涓虹┖"})
    row_id, field, value = d.get("id"), d.get("field"), d.get("value")
    if row_id is None or not field: return jsonify({"code": 1, "msg": "鍙傛暟涓嶅叏"})
    # 鍏抽敭瀛楁鍞竴鎬ф鏌?    if value is not None and str(value).strip():
        is_key = False
        # 妫€鏌ュ悓姝ユ槧灏勪腑鐨勫叧閿瓧娈?        for mp in _load_m():
            if table_name in (mp["st"], mp["tt"]) and mp["kf"] == field:
                is_key = True; break
        # 妫€鏌ヨ〃鑷韩璁惧畾鐨勫叧閿瓧娈?        if not is_key:
            stored_kf = _load_kf().get(table_name, "")
            if stored_kf == field:
                is_key = True
        if is_key:
            pk = get_pk_column(table_name) or "id"
            has_del = any(s["field"] == "_deleted" for s in get_schema(table_name))
            del_cond = "AND (`_deleted` IS NULL OR `_deleted`!=1)" if has_del else ""
            cnt = query_one(f"SELECT COUNT(*) AS c FROM `{table_name}` WHERE `{field}`=%s AND `{pk}`!=%s {del_cond}", (value, row_id))
            if cnt and cnt["c"] > 0:
                return jsonify({"code": 1, "msg": f"鍏抽敭瀛楁銆寋field}銆嶅€笺€寋value}銆嶅凡瀛樺湪锛屼笉鑳介噸澶?})
    try:
        update_cell(table_name, row_id, field, value)
        msg = "宸叉洿鏂?
        # 妫€鏌ユ槧灏勫悓姝?        for mp in _load_m():
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
                    msg += f"锛堝悓姝ヨ嚦 {other}锛?
        return jsonify({"code": 0, "msg": msg})
    except Exception as e: return jsonify({"code": 1, "msg": f"鏇存柊澶辫触: {str(e)}"})


def db_execute(sql, params=None):
    from db import execute as _e
    try: _e(sql, params); return True
    except: return False


@app.route("/api/table/<table_name>")
def api_table(table_name):
    s = get_schema(table_name)
    if not s: return jsonify({"code": 1, "msg": f"琛?{table_name} 涓嶅瓨鍦?})
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


# ========== 瀛楁鏄犲皠 API ==========

@app.route("/api/sync/mappings", methods=["GET"])
def api_get_mappings():
    return jsonify({"code": 0, "data": _load_m()})

@app.route("/api/sync/mappings", methods=["POST"])
def api_save_mappings():
    d = request.get_json()
    if not d or "mappings" not in d: return jsonify({"code": 1, "msg": "璇锋眰涓虹┖"})
    _save_m(d["mappings"])
    return jsonify({"code": 0, "msg": f"宸蹭繚瀛?{len(d['mappings'])} 鏉℃槧灏?})

@app.route("/api/sync/schema/<table_name>")
def api_sync_schema(table_name):
    """杩斿洖鎸囧畾琛ㄧ殑闈炰富閿瓧娈靛垪琛?""
    s = get_schema(table_name)
    pk = get_pk_column(table_name)
    fields = [{"field": c["field"], "type": c["type"]} for c in s if c["field"] != pk]
    return jsonify({"code": 0, "data": fields})

@app.route("/api/sync/verify", methods=["POST"])
def api_sync_verify():
    """鏍稿疄涓や釜琛ㄦ槧灏勫瓧娈电殑鏁版嵁鏄惁涓€鑷?""
    d = request.get_json()
    st, tt, kf = d.get("source"), d.get("target"), d.get("key_field")
    ps = d.get("pairs", [])
    if not st or not tt or not kf or not ps:
        return jsonify({"code": 1, "msg": "鍙傛暟涓嶅叏"})
    # 鍙煡蹇呰鐨勫瓧娈碉紝閬垮厤鍏ㄨ〃鎵弿
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
        return jsonify({"code": 1, "msg": f"鏌ヨ澶辫触: {e}"})
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
                    "val_src": str(sv) if sv is not None else "(绌?",
                    "val_tgt": str(tv) if tv is not None else "(绌?"})
    tgt_only = sum(1 for k in tgt_map if k not in src_keys)
    return jsonify({"code": 0, "data": {"total_src": len(src_rows), "total_tgt": len(tgt_rows),
        "matched": matched, "src_only": src_only, "tgt_only": tgt_only, "errors": errors}})

@app.route("/api/sync/auto-fill", methods=["POST"])
def api_auto_fill():
    """缂栬緫鍏抽敭瀛楁鍚庯紝浠庡叧鑱旇〃鎷夊彇鏁版嵁琛ュ叏"""
    d = request.get_json(); tbl, kf, kv, rid = d.get("table"), d.get("key_field"), d.get("key_value"), d.get("row_id")
    if not tbl or not kf or kv is None: return jsonify({"code": 1, "msg": "鍙傛暟涓嶅叏"})
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
    if not fills: return jsonify({"code": 1, "msg": "鏈壘鍒板尮閰?})
    return jsonify({"code": 0, "data": fills})

@app.route("/api/sync/backfill", methods=["POST"])
def api_sync_backfill():
    """琛ュ～锛氭壂鎻忚〃涓殑绌烘槧灏勫瓧娈碉紝浠庡叧鑱旇〃鎷夊彇琛ラ綈"""
    d = request.get_json(); tbl = d.get("table", "")
    if not tbl: return jsonify({"code": 1, "msg": "琛ㄥ悕涓虹┖"})
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
                    # Data too long 鈫?鑷姩鎵╁瓧娈典负 TEXT 鍚庨噸璇?                    if "Data too long" in es:
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
    msg = f"琛ュ～瀹屾垚锛氭洿鏂?{filled} 琛?
    if errors:
        details = "; ".join(errors[:5])
        msg += f"锛寋len(errors)} 涓敊璇紙{details}锛?
    return jsonify({"code": 0, "msg": msg, "filled": filled})

# ========== 鍓创鏉?==========
_clipboard = None  # {table, key_field, fields: [...], rows: [[...], ...]}

@app.route("/api/clipboard/copy", methods=["POST"])
def api_clipboard_copy():
    d = request.get_json()
    if not d or "fields" not in d or "rows" not in d:
        return jsonify({"code": 1, "msg": "鍙傛暟涓嶅叏"})
    global _clipboard
    _clipboard = {
        "table": d.get("table", ""),
        "key_field": d.get("key_field", ""),
        "fields": d["fields"],
        "rows": d["rows"]
    }
    return jsonify({"code": 0, "msg": f"宸插鍒?{len(d['rows'])} 琛?{len(d['fields'])} 鍒?})

@app.route("/api/clipboard/paste", methods=["POST"])
def api_clipboard_paste():
    global _clipboard
    if not _clipboard: return jsonify({"code": 1, "msg": "鍓创鏉夸负绌猴紝璇峰厛澶嶅埗"})
    d = request.get_json()
    tgt = d.get("target", "")
    if not tgt: return jsonify({"code": 1, "msg": "鐩爣琛ㄥ悕涓虹┖"})
    schema = get_schema(tgt)
    tgt_all_fields = [s["field"] for s in schema]
    pk = get_pk_column(tgt) or "id"
    src_fields = _clipboard["fields"]
    # 瀛楁鍚嶇О鍖归厤锛堟帓闄?id 鑷涓婚敭锛?    col_map = {}
    for sf in src_fields:
        if sf in tgt_all_fields and sf != pk:
            col_map[sf] = src_fields.index(sf)
    if not col_map: return jsonify({"code": 1, "msg": "婧愬瓧娈典笌鐩爣琛ㄦ棤鍖归厤瀛楁"})
    # 鑷姩璇嗗埆鍏抽敭瀛楁锛氣憼 鐩爣琛ㄥ瓨鍌ㄧ殑鍏抽敭瀛楁 鈫?鈶?婧愯〃涓殑鐩爣琛?PK 鈫?鈶?绗竴涓尮閰嶅瓧娈?    stored_kf = _load_kf().get(tgt, "")
    kf = ""
    if stored_kf and stored_kf in src_fields:
        kf = stored_kf
    elif pk in src_fields:
        kf = pk
    else:
        kf = list(col_map.keys())[0]
    # 濡傛灉鍞竴鍖归厤鐨勫瓧娈靛氨鏄叧閿瓧娈垫湰韬?鈫?浠呮洿鏂拌瀛楁鍊硷紙鍏佽鐢ㄦ埛鍚屾鍚屽悕瀛楁锛?    non_key_cols = {f for f in col_map if f != kf}
    # 璇诲彇鐩爣琛ㄥ凡鏈夎褰曠殑鍏抽敭鍊?    has_deleted = any(s["field"] == "_deleted" for s in schema)
    visible_exists = {}   # 鍙璁板綍鐨勫叧閿€?鈫?id
    hidden_exists = {}    # 闅愯棌璁板綍鐨勫叧閿€?鈫?id
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
            # 鏇存柊宸叉湁鍙璁板綍
            sets = ", ".join([f"`{f}`=%s" for f in tf_vals])
            try:
                execute(f"UPDATE `{tgt}` SET {sets} WHERE `{kf}`=%s", list(tf_vals.values()) + [kv])
                updated += 1
            except: pass
        elif kv and kv in hidden_exists:
            # 闅愯棌璁板綍 鈫?鎭㈠鏄剧ず + 鏇存柊鏁版嵁
            sets = ", ".join([f"`{f}`=%s" for f in list(tf_vals.keys()) + (["_deleted"] if has_deleted else [])])
            vals = list(tf_vals.values()) + ([0] if has_deleted else []) + [kv]
            try:
                execute(f"UPDATE `{tgt}` SET {sets} WHERE `{kf}`=%s", vals)
                restored += 1
            except: pass
        else:
            # 涓嶅瓨鍦?鈫?鏂板
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
        # 绮樿创鍚庤嚜鍔ㄥ～鍏咃細鍒╃敤宸叉湁瀛楁鏄犲皠浠庡叧鑱旇〃鎷夊彇
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
    if updated: parts.append(f"鏇存柊 {updated} 琛?)
    if inserted: parts.append(f"鏂板 {inserted} 琛?)
    if restored: parts.append(f"鎭㈠ {restored} 琛岋紙浠庨殣钘忕姸鎬佹仮澶嶏級")
    msg = "绮樿创瀹屾垚锛? + "锛?.join(parts) if parts else "绮樿创瀹屾垚锛氭棤鍙樺寲"
    return jsonify({"code": 0, "msg": msg, "updated": updated, "inserted": inserted, "restored": restored})

@app.route("/api/clipboard/clear", methods=["POST"])
def api_clipboard_clear():
    global _clipboard
    _clipboard = None
    return jsonify({"code": 0, "msg": "鍓创鏉垮凡娓呯┖"})

@app.route("/api/clipboard", methods=["GET"])
def api_clipboard_status():
    global _clipboard
    if not _clipboard:
        return jsonify({"code": 1, "msg": "绌?})
    return jsonify({"code": 0, "data": {
        "table": _clipboard["table"],
        "rows": len(_clipboard["rows"]),
        "cols": len(_clipboard["fields"])
    }})


# ========== 澶氳〃姹囨€?==========

@app.route("/api/aggregate/preview", methods=["POST"])
def api_aggregate_preview():
    """棰勮澶氳〃姹囨€荤粨鏋?""
    d = request.get_json()
    if not d: return jsonify({"code": 1, "msg": "璇锋眰涓虹┖"})
    table_names = d.get("tables", [])
    key_field = (d.get("key_field") or "").strip()
    if len(table_names) < 2:
        return jsonify({"code": 1, "msg": "璇烽€夋嫨鑷冲皯 2 寮犺〃"})
    if not key_field:
        return jsonify({"code": 1, "msg": "璇烽€夋嫨鍏抽敭瀛楁锛堟眹鎬讳緷鎹級"})
    try:
        # 鍔犺浇宸叉湁鐨勫瓧娈垫槧灏勶紝鐢ㄤ簬鍚堝苟鍚屼箟涓嶅悓鍚嶇殑瀛楁
        mappings = _load_m()  # [{"st":"A","tt":"B","kf":"椤圭洰缂栧彿","ps":[{"s":"婧愬瓧娈?,"t":"鐩爣瀛楁"},...]}]
        all_keys = set()
        table_data = {}
        for tn in table_names:
            schema = get_schema(tn)
            if not schema: return jsonify({"code": 1, "msg": f"琛?`{tn}` 涓嶅瓨鍦?})
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
        # 鏋勫缓鏄犲皠瀛楀吀锛?(table1, table2) 鈫?{ field1: field2 }
        # 缁熶竴鐢?(table1, table2) 鏂瑰悜瀛樺偍锛宼able1 鐨勫瓧娈垫槧灏勫埌 table2 鐨勫瓧娈?        merge_map = {}
        for mp in mappings:
            if mp["st"] in table_names and mp["tt"] in table_names:
                key = (mp["st"], mp["tt"])
                if key not in merge_map:
                    merge_map[key] = {}
                for p in mp["ps"]:
                    merge_map[key][p["s"]] = p["t"]
        # 缁熶竴瀛楁鍚嶏細瀵瑰瓨鍦ㄦ槧灏勭殑涓嶅悓鍚嶆垚瀵瑰瓧娈碉紝鍙繚鐣欑涓€涓〃鐨勫瓧娈靛悕
        unified_warnings = []
        merged_headers = [key_field]
        field_sources = {}  # header_name 鈫?(table_name, field_on_that_table)
        for tn in table_names:
            for f in table_data[tn]["fields"]:
                hdr = f
                # 妫€鏌ユ槸鍚﹀凡鏈夋槧灏勫涓殑鍙︿竴鏂瑰凡浣滀负琛ㄥご瀛樺湪
                merged = False
                for (t1, t2), pairs in merge_map.items():
                    # 妫€鏌ュ綋鍓嶈〃鏄?t1 杩樻槸 t2
                    if tn == t1:
                        other_table = t2
                        if other_table not in table_names:
                            continue
                        # f 鏄?t1 鐨勫瓧娈?鈫?鎵炬槧灏勫埌 t2 鐨勫瓧娈?                        if f in pairs:
                            mapped_field = pairs[f]
                        else:
                            continue
                    elif tn == t2:
                        other_table = t1
                        if other_table not in table_names:
                            continue
                        # f 鏄?t2 鐨勫瓧娈?鈫?鎵惧弽鍚戞槧灏?                        mapped_field = None
                        for src_f, tgt_f in pairs.items():
                            if tgt_f == f:
                                mapped_field = src_f
                                break
                        if mapped_field is None:
                            continue
                    else:
                        continue
                    if mapped_field and mapped_field in field_sources:
                        # 瀵规柟琛ㄥ凡鐢?mapped_field 浣滀负琛ㄥご 鈫?鍏辩敤姝ゅ垪锛堟暟鎹悎骞跺埌璇ュ垪锛?                        merged = True
                        if mapped_field != f:
                            conflict_pair = {"tables": [tn, other_table], "fields": [f, mapped_field], "default_name": mapped_field}
                            # 鍘婚噸
                            dup = False
                            for cw in unified_warnings:
                                if cw.get("fields") and set(cw["fields"]) == set(conflict_pair["fields"]):
                                    dup = True; break
                            if not dup:
                                unified_warnings.append(conflict_pair)
                        break
                    elif mapped_field and mapped_field not in field_sources and tn != other_table:
                        # f 鏈夋槧灏勪絾瀵规柟瀛楁灏氭湭浣滀负琛ㄥご 鈫?鐢?f 浣滀负琛ㄥご
                        pass  # 浣跨敤褰撳墠瀛楁鍚?                if merged:
                    continue
                if hdr in field_sources:
                    # 鐪熸鍚屽悕鐨勫凡鏈夛紝浣嗛潪鏄犲皠鍏崇郴 鈫?鍔犺〃鍚嶅墠缂€
                    hdr = f"{tn}.{f}"
                merged_headers.append(hdr)
                field_sources[hdr] = (tn, f)
        # 鍚堝苟琛屾暟鎹?        merged_rows = []
        for kv in sorted(all_keys):
            row = [kv]
            for hdr in merged_headers[1:]:
                tn, f = field_sources[hdr]
                rec = table_data[tn]["records"].get(kv)
                row.append(rec.get(f) if rec else None)
            merged_rows.append(row)
        # 鍒嗙 field_conflicts 鍜屾櫘閫?warnings
        field_conflicts = [w for w in unified_warnings if isinstance(w, dict) and "fields" in w]
        text_warnings = [w for w in unified_warnings if not isinstance(w, dict)]
        # orphan_suggestions: 鍒楀嚭姣忓紶琛ㄧ嫭鏈夌殑瀛楁锛堜笉浼氳鏄犲皠鍚堝苟鐨勫悓鍚?涓嶅悓鍚嶅瓧娈碉級
        orphan_suggestions = {}
        for tn in table_names:
            unique = []
            for f in table_data[tn]["fields"]:
                if f == key_field: continue
                # 妫€鏌ユ槸鍚﹁鏄犲皠鍚堝苟锛堝凡鍦?field_conflicts 涓級
                in_conflict = False
                for c in field_conflicts:
                    if f in c["fields"]:
                        in_conflict = True; break
                # 妫€鏌ュ叾浠栬〃鏄惁鏈夊悓鍚嶅瓧娈碉紙鑷姩鍚堝苟锛?                same_in_other = False
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
            "orphan_fields": orphan_suggestions  # 姣忓紶琛ㄧ嫭鏈夌殑瀛楁
        }})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"姹囨€诲け璐? {str(e)}"})


@app.route("/api/aggregate/create", methods=["POST"])
def api_aggregate_create():
    """鍒涘缓姹囨€昏〃锛屽苟鑷姩寤虹珛姹囨€昏〃涓庡悇婧愯〃鐨勬槧灏?""
    d = request.get_json()
    if not d: return jsonify({"code": 1, "msg": "璇锋眰涓虹┖"})
    new_name = (d.get("new_name") or "").strip()
    if not new_name: return jsonify({"code": 1, "msg": "璇峰～鍐欐柊琛ㄥ悕"})
    headers = d.get("headers", [])
    rows = d.get("rows", [])
    source_tables = d.get("tables", [])
    key_field = (d.get("key_field") or "").strip()
    if not headers or not rows:
        return jsonify({"code": 1, "msg": "鏃犳暟鎹?})
    try:
        from db import create_table_from_data, get_schema
        ok, msg = create_table_from_data(headers, rows, new_name)
        if not ok:
            return jsonify({"code": 1, "msg": msg})
        _save_table_manifest()
        # 鑷姩寤虹珛姹囨€昏〃涓庡悇婧愯〃鐨勫悓姝ユ槧灏?        mappings = _load_m()
        agg_fields = [s["field"] for s in get_schema(new_name) if s["field"] not in ("id", "_deleted")]
        # 鏀堕泦婧愯〃涔嬮棿鐨勬槧灏勫叧绯伙紝鐢ㄤ簬澶勭悊涓嶅悓鍚嶄絾鏄犲皠杩囩殑瀛楁
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
            # 涓?agg_fields 涓殑姣忎釜瀛楁鎵惧搴?            for f in agg_fields:
                if f in src_fields:
                    # 鍚屽悕瀛楁鐩存帴鏄犲皠
                    pairs.append({"s": f, "t": f})
                else:
                    # 涓嶅悓鍚嶏細妫€鏌ユ槸鍚︽湁婧愯〃闂寸殑鏄犲皠鍏崇郴鑳藉叧鑱?                    for (t1, t2), sm in src_pairs.items():
                        # 鎯呭喌1锛歴t 鏄?t1锛堟簮锛夛紝f 鏄犲皠鍒颁簡 t2 鐨勬煇涓瓧娈?                        if st == t1:
                            for src_f, tgt_f in sm.items():
                                if tgt_f == f and src_f in agg_fields:
                                    pairs.append({"s": src_f, "t": src_f})
                                    break
                        # 鎯呭喌2锛歴t 鏄?t2锛堢洰鏍囪〃锛夛紝t1 鐨?src_f 鏄犲皠鍒?st 鐨?tgt_f
                        # 姹囨€昏〃鐨?f == src_f 鈫?B琛ㄥ瓧娈?tgt_f 搴旀槧灏勫埌姹囨€昏〃瀛楁 f
                        if st == t2:
                            for src_f, tgt_f in sm.items():
                                if src_f == f:
                                    # tgt_f 鏄?B 琛ㄤ腑鐨勫瓧娈靛悕锛宖 鏄眹鎬昏〃涓殑瀛楁鍚?                                    pairs.append({"s": tgt_f, "t": f})
                                    break
            if pairs:
                # 鍘婚噸
                seen = set()
                deduped = []
                for p in pairs:
                    k = p["s"] + ":" + p["t"]
                    if k not in seen:
                        seen.add(k); deduped.append(p)
                mappings.append({"st": st, "tt": new_name, "kf": key_field, "ps": deduped})
        _save_m(mappings)
        # 璁剧疆姹囨€昏〃鐨勫叧閿瓧娈典笌婧愯〃涓€鑷?        if key_field:
            km = _load_kf()
            km[new_name] = key_field
            _save_kf(km)
        return jsonify({"code": 0, "msg": msg, "table_name": new_name})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鍒涘缓姹囨€昏〃澶辫触: {str(e)}"})


# ========== 鍗曡〃鍒嗙被姹囨€?==========

@app.route("/api/table/<table_name>/group-summary", methods=["POST"])
def api_group_summary(table_name):
    """鎸夋寚瀹氬瓧娈靛垎缁勬眹鎬伙紝缁撴灉瀛樹负鏂拌〃
    POST /api/table/<table_name>/group-summary
    鍙傛暟: {"group_field": "鍒嗙粍瀛楁", "aggregations": [{"field": "瀛楁", "type": "count|sum", "alias": "鍒悕"}], "title": "鏂拌〃鍚?}
    """
    d = request.get_json()
    gf = (d.get("group_field") or "").strip()
    aggs = d.get("aggregations") or d.get("aggs") or []  # [{field, type: "count"|"sum", alias}]
    title = (d.get("title") or "").strip()
    if not gf: return jsonify({"code": 1, "msg": "璇烽€夋嫨鍒嗙粍瀛楁"})
    if not aggs: return jsonify({"code": 1, "msg": "璇锋坊鍔犺嚦灏戜竴涓眹鎬婚」"})
    schema = get_schema(table_name)
    fields = {s["field"]: s["type"] for s in schema}
    if gf not in fields: return jsonify({"code": 1, "msg": f"鍒嗙粍瀛楁 '{gf}' 涓嶅湪琛ㄤ腑"})
    # 鏋勫缓 SQL
    selects = [f"`{gf}`"]
    col_defs = [{"name": gf, "type": "VARCHAR(255)"}]
    agg_headers = [gf]
    for a in aggs:
        fld = (a.get("field") or "").strip()
        tp = (a.get("type") or "count").strip().lower()
        alias = (a.get("alias") or f"{fld}_{tp}").strip()
        if fld not in fields: return jsonify({"code": 1, "msg": f"姹囨€诲瓧娈?'{fld}' 涓嶅湪琛ㄤ腑"})
        if tp == "count":
            selects.append(f"COUNT(`{fld}`) AS `{alias}`")
            col_defs.append({"name": alias, "type": "INT"})
        elif tp == "sum":
            selects.append(f"COALESCE(SUM(`{fld}`),0) AS `{alias}`")
            col_defs.append({"name": alias, "type": "DECIMAL(15,2)"})
        else:
            return jsonify({"code": 1, "msg": f"涓嶆敮鎸佺殑姹囨€荤被鍨?'{tp}'锛屼粎鏀寔 count/sum"})
        agg_headers.append(alias)
    sql = f"SELECT {', '.join(selects)} FROM `{table_name}` GROUP BY `{gf}` ORDER BY `{gf}`"
    rows = query(sql)
    if rows is None: return jsonify({"code": 1, "msg": "鏌ヨ澶辫触"})
    # 寤烘柊琛?    tn = _safe_tablename(title) if title else f"鍒嗙被姹囨€籣{uuid.uuid4().hex[:6]}"
    # 鍏堝缓绌鸿〃
    ok, msg = create_empty_table(tn, columns=col_defs)
    if not ok: return jsonify({"code": 1, "msg": msg})
    # 鎻掑叆鏁版嵁
    placeholders = ", ".join(["%s"] * len(agg_headers))
    col_names = ", ".join([f"`{h}`" for h in agg_headers])
    try:
        for row in rows:
            rv = [row.get(h) if isinstance(row, dict) else row[i] for i, h in enumerate(agg_headers)]
            execute(f"INSERT INTO `{tn}` ({col_names}) VALUES ({placeholders})", rv)
    except Exception as e:
        execute(f"DROP TABLE IF EXISTS `{tn}`")
        return jsonify({"code": 1, "msg": f"鍐欏叆鏁版嵁澶辫触: {e}"})
    db_execute(f"ALTER TABLE `{tn}` COMMENT = %s", (title or f"鎸墈gf}鍒嗙被姹囨€?,))
    _save_table_manifest()
    n = len(rows)
    return jsonify({"code": 0, "msg": f"鍒嗙被姹囨€昏〃鍒涘缓鎴愬姛锛屽叡 {n} 鏉¤褰?, "table_name": tn})


# ========== 涓婁紶 ==========

# ========== 澶囦唤涓庢仮澶?==========

@app.route("/api/backup/list", methods=["GET"])
def api_backup_list():
    """鍒楀嚭 _backup/ 鐩綍涓嬬殑鎵€鏈夊浠?""
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
                    # 璺宠繃鎹熷潖鐨勫浠芥枃浠?                    continue
        files.sort(key=lambda x: x["backup_at"], reverse=True)
        return jsonify({"code": 0, "data": files, "manifest_exists": os.path.exists(os.path.join(_BACKUP_DIR, "_manifest.json"))})
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e)})


@app.route("/api/backup/restore", methods=["POST"])
def api_backup_restore():
    """浠庡浠芥枃浠舵仮澶嶄竴寮犺〃"""
    d = request.get_json()
    filename = (d or {}).get("filename", "")
    if not filename: return jsonify({"code": 1, "msg": "澶囦唤鏂囦欢鍚嶄负绌?})
    path = os.path.join(_BACKUP_DIR, filename)
    if not os.path.exists(path): return jsonify({"code": 1, "msg": "澶囦唤鏂囦欢涓嶅瓨鍦?})
    try:
        with open(path, encoding="utf-8") as f:
            bk = json.load(f)
        tn = bk["table"]
        # 濡傛灉琛ㄥ凡瀛樺湪锛屽厛澶囦唤鍐嶅垹
        schema = get_schema(tn)
        if schema:
            _backup_table(tn)
            drop_table(tn)
        # 閲嶅缓琛?        col_defs = []
        for s in bk["schema"]:
            if s["field"] == "id": continue
            col_defs.append(f"`{s['field']}` {s['type']} NULL")
        sql = f"CREATE TABLE `{tn}` (`id` INT NOT NULL AUTO_INCREMENT, {', '.join(col_defs)}, PRIMARY KEY (`id`)) "
        execute(sql)
        # 鎭㈠鏁版嵁
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
        return jsonify({"code": 0, "msg": f"琛?`{tn}` 宸叉仮澶嶏紝鍏?{len(bk['rows'])} 鏉¤褰?})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鎭㈠澶辫触: {str(e)}"})


@app.route("/api/backup/delete", methods=["POST"])
def api_backup_delete():
    """鍒犻櫎涓€涓垨澶氫釜澶囦唤鏂囦欢"""
    d = request.get_json()
    filenames = d.get("filenames", [])
    if not filenames: return jsonify({"code": 1, "msg": "璇锋寚瀹氳鍒犻櫎鐨勫浠芥枃浠?})
    deleted = 0
    for fn in filenames:
        path = os.path.join(_BACKUP_DIR, fn)
        try:
            if os.path.exists(path) and fn.endswith(".json"):
                os.unlink(path)
                deleted += 1
        except: pass
    return jsonify({"code": 0, "msg": f"宸插垹闄?{deleted} 涓浠芥枃浠?})


# ========== 鏁版嵁搴撴暣浣撳鍑?瀵煎叆 ==========

@app.route("/api/database/overview", methods=["GET"])
def api_db_overview():
    """杩斿洖鏁版嵁搴撴瑙堬細鎵€鏈夎〃鍚嶃€佽鏁般€侀殣钘?鍒犻櫎鏁般€佸瓧娈垫暟"""
    try:
        from db import get_tables, get_schema, get_pk_column, query
        tables = get_tables()
        result = []
        for t in tables:
            name = t["name"]
            comment = t.get("comment", "")
            schema = get_schema(name)
            pk = get_pk_column(name) or "id"
            # 缁熻琛屾暟
            cnt = query_one(f"SELECT COUNT(*) AS c FROM `{name}`")["c"]
            # 缁熻闅愯棌鍜岃〃鍒犻櫎
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
    """瀵煎嚭鏁翠釜鏁版嵁搴撲负鍗曚竴 JSON 鏂囦欢"""
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
        filename = f"鏁版嵁鍙拌处绯荤粺_澶囦唤_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        return send_file(buf, download_name=filename, as_attachment=True,
                        mimetype="application/json")
    except Exception as e:
        return jsonify({"code": 1, "msg": f"瀵煎嚭澶辫触: {str(e)}"})


def _import_db_json(data):
    """浠?JSON dict 鎭㈠鏁翠釜鏁版嵁搴擄紙鍐呴儴澶嶇敤锛?""
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
    """浠?JSON 鏂囦欢瀵煎叆鎭㈠鏁翠釜鏁版嵁搴?""
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"code": 1, "msg": "璇烽€夋嫨鏂囦欢"})
    if not file.filename.endswith(".json"):
        return jsonify({"code": 1, "msg": "璇烽€夋嫨 .json 澶囦唤鏂囦欢"})
    try:
        content = file.read().decode("utf-8")
        data = json.loads(content)
    except Exception as e:
        return jsonify({"code": 1, "msg": f"鏂囦欢瑙ｆ瀽澶辫触: {e}"})

    if not isinstance(data, dict) or "tables" not in data:
        return jsonify({"code": 1, "msg": "鏃犳晥鐨勫浠芥枃浠舵牸寮?})

    ok, fail, errors = _import_db_json(data)
    msg = f"鎴愬姛鎭㈠ {ok} 寮犺〃"
    if fail:
        msg += f"锛寋fail} 寮犺〃澶辫触"
    result = {"code": 0, "msg": msg, "ok": ok, "fail": fail}
    if errors:
        result["errors"] = errors
    return jsonify(result)


@app.route("/api/upload/parse", methods=["POST"])
def api_upload_parse():
    file = request.files.get("file")
    if not file or file.filename == "": return jsonify({"code": 1, "msg": "璇烽€夋嫨鏂囦欢"})
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".csv", ".xls", ".xlsx", ".et"): return jsonify({"code": 1, "msg": "浠呮敮鎸?.csv/.xls/.xlsx/.et"})
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
        return jsonify({"code": 1, "msg": f"瑙ｆ瀽澶辫触: {str(e)}"})


@app.route("/api/upload/select_sheet", methods=["POST"])
def api_upload_select_sheet():
    d = request.get_json(); sid, sn = d.get("session_id"), d.get("sheet","")
    if sid not in _upload_cache: return jsonify({"code": 1, "msg": "杩囨湡"})
    if sn not in _upload_cache[sid]["sheets"]: return jsonify({"code": 1, "msg": "Sheet涓嶅瓨鍦?})
    _upload_cache[sid]["current_sheet"] = sn; _recalc(sid)
    s = _upload_cache[sid]["sheets"][sn]
    return jsonify({"code": 0, "data": {"headers": s["headers"], "total_rows": len(s["rows"]), "preview": s["rows"][:5]}})


@app.route("/api/upload/set_header_rows", methods=["POST"])
def api_upload_set_header_rows():
    d = request.get_json(); sid = d.get("session_id")
    if sid not in _upload_cache: return jsonify({"code": 1, "msg": "杩囨湡"})
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
    if sid not in _upload_cache: return jsonify({"code": 1, "msg": "杩囨湡"})
    c = _upload_cache[sid]; s = c["sheets"].get(c["current_sheet"])
    if not s: return jsonify({"code": 1, "msg": "鏃犳暟鎹?})
    ah, rows = s["headers"], s["rows"]
    if not kf: _cleanup(sid); return jsonify({"code": 0, "msg": "宸插彇娑?})
    if kf not in ah: return jsonify({"code": 1, "msg": f"瀛楁 '{kf}' 涓嶅瓨鍦?})
    uh = [h for h in ah if h in sf] if sf and isinstance(sf,list) else list(ah)
    if kf not in uh: return jsonify({"code": 1, "msg": "鍏抽敭瀛楁鏈嬀閫?})
    ui = [ah.index(h) for h in uh]; ki_ah = ah.index(kf)
    flt = []; before = len(rows)
    for row in rows:
        v = row[ki_ah] if ki_ah < len(row) else None
        if v is not None and str(v).strip()!="": flt.append([row[i] for i in ui])
    tn = _safe_tablename(title) if title else f"imported_{uuid.uuid4().hex[:6]}"
    if not flt:
        # 鏃犳暟鎹 鈫?鍒涘缓绌鸿〃锛堝彧鏈夊瓧娈靛悕锛屾病鏈夋暟鎹級
        from db import create_empty_table as cet
        columns = [{"name": h, "type": "VARCHAR(255)"} for h in uh]
        ok, msg = cet(tn, columns=columns)
        _cleanup(sid)
        if ok:
            db_execute(f"ALTER TABLE `{tn}` COMMENT = %s", (title or tn,))
            _save_table_manifest()
            msg += f"锛堢┖琛紝宸插缓 {len(uh)} 涓瓧娈碉級"
        return jsonify({"code": 0 if ok else 1, "msg": msg, "table_name": tn})
    ok, msg = create_table_from_data(uh, flt, tn); _cleanup(sid)
    if ok:
        db_execute(f"ALTER TABLE `{tn}` COMMENT = %s", (title or tn,))
        _save_table_manifest()
    if ok: msg += f"锛堢渷鐣?{len(ah)-len(uh)} 鍒楋紝杩囨护 {before-len(flt)} 琛岋級"
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
    """妫€鏌?sheet 鏄惁鏈夎嚦灏戜竴琛屾湁鏁堟暟鎹?""
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
    """灏?rows 涓殑 date/datetime 杞负 ISO 瀛楃涓?""
    for row in rows:
        for k, v in list(row.items()):
            if isinstance(v, (datetime.date, datetime.datetime)):
                row[k] = v.isoformat()
    return rows

def _safe_tablename(name):
    """灏嗘爣棰樿浆涓哄畨鍏ㄧ殑 MySQL 琛ㄥ悕锛岃嚜鍔ㄥ鐞嗛噸鍚?""
    s = str(name).strip()
    safe = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\s]', '_', s)
    safe = re.sub(r'\s+', '_', safe).strip('_')
    if not safe or safe[0].isdigit():
        safe = 't_' + safe
    if not safe:
        return f"imported_{uuid.uuid4().hex[:6]}"
    if len(safe) > 60:
        safe = safe[:60]
    # 閲嶅悕鑷姩鍔犲悗缂€
    base = safe; idx = 1
    existing = {t["name"] for t in get_tables()}
    while safe in existing:
        suffix = f"_{idx}"
        safe = base[:60-len(suffix)] + suffix
        idx += 1
    return safe


if __name__ == "__main__":
    print("="*50); print("鏁版嵁鍙拌处绯荤粺"); print(f"  鍦板潃: http://127.0.0.1:5000"); print("="*50)
    app.run(host="0.0.0.0", port=5000, debug=True)


import routes_column


import routes_column

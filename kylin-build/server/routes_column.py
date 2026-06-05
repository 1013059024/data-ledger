"""
麒麟版列操作接口 — 从 app.py 拆出，单独上传避免大文件问题
"""
import app
from flask import jsonify, request
from db import get_schema, _get_conn, alter_column_type, execute


@app.app.route("/api/table/<table_name>/column/<column_name>/type", methods=["PATCH"])
def api_set_column_type(table_name, column_name):
    """修改列数据类型（先清洗空串，再转换）"""
    d = request.get_json(); new_type = (d or {}).get("type","").strip()
    if not new_type: return jsonify({"code": 1, "msg": "类型不能为空"})
    if column_name.lower() == "id": return jsonify({"code": 1, "msg": "id 列不允许修改"})
    try:
        nt_upper = new_type.upper()
        if any(kw in nt_upper for kw in ("DECIMAL", "INT", "DOUBLE", "FLOAT", "NUMERIC", "BIGINT", "SMALLINT", "TINYINT")):
            execute(f"UPDATE `{table_name}` SET `{column_name}`=NULL WHERE `{column_name}`='' OR `{column_name}` IS NULL")
        alter_column_type(table_name, column_name, new_type)
        return jsonify({"code": 0, "msg": f"已修改为 {new_type}"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"修改失败: {e}"})


@app.app.route("/api/table/<table_name>/reorder-columns", methods=["PUT"])
def api_reorder_columns(table_name):
    """调整表字段顺序 — SQLite 重建表策略"""
    d = request.get_json()
    new_order = (d or {}).get("columns", [])
    if not new_order:
        return jsonify({"code": 1, "msg": "请提供新字段顺序"})
    try:
        schema = get_schema(table_name)
        if not schema: return jsonify({"code": 1, "msg": "表不存在"})
        schema_fields = [s["field"] for s in schema if s["field"] not in ("id", "_deleted")]
        if set(new_order) != set(schema_fields):
            missing = set(schema_fields) - set(new_order)
            extra = set(new_order) - set(schema_fields)
            msg = "字段不匹配"
            if missing: msg += f"，缺少: {missing}"
            if extra: msg += f"，多余: {extra}"
            return jsonify({"code": 1, "msg": msg})
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
        return jsonify({"code": 0, "msg": "字段顺序已调整"})
    except Exception as e:
        return jsonify({"code": 1, "msg": f"调整失败: {e}"})

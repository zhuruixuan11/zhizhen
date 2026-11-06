"""知识图谱 GraphRAG 检索与知识库浏览。"""
import logging
from typing import Any, Optional
from neo4j.time import Date, DateTime, Duration, Time

from app.core import milvus_client, neo4j_client
from app.core.metrics import GRAPH_SEARCH_HITS
from app.schemas.schemas import GraphRef, KnowledgeNode, Neighbor, NodeDetail

logger = logging.getLogger("app.knowledge")

_LABEL_CN = {"Herb": "中药", "Formula": "方剂", "Syndrome": "证型", "Symptom": "症状"}


def _json_properties(value: Any) -> Any:
    """Convert graph temporal values, including nested properties, to ISO strings."""
    if isinstance(value, (Date, DateTime, Time, Duration)):
        return value.iso_format()
    if isinstance(value, dict):
        return {key: _json_properties(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_properties(item) for item in value]
    return value


def _graph_available() -> bool:
    return neo4j_client.available()


def _vector_available() -> bool:
    return milvus_client.available()


# ---------------- 知识库浏览 ----------------
def search(db_type: str, q: str, page: int, page_size: int) -> tuple[list[dict], int]:
    """按类型/关键词检索图谱，返回 items 与 total。type: all/formula/herb/syndrome/symptom"""
    label_map = {"formula": "Formula", "herb": "Herb", "syndrome": "Syndrome", "symptom": "Symptom"}
    q = (q or "").strip()

    if not _graph_available():
        return [], 0

    clauses = []
    params: dict[str, Any] = {}
    for t, lab in label_map.items():
        if db_type in ("all", t):
            node_var = lab.lower()
            if q:
                clauses.append(
                    f"MATCH ({node_var}:{lab}) WHERE {node_var}.name CONTAINS $q "
                    f"RETURN '{lab}' AS label, {node_var}.name AS name, "
                    f"coalesce({node_var}.source,'') AS source"
                )
            else:
                clauses.append(
                    f"MATCH ({node_var}:{lab}) "
                    f"RETURN '{lab}' AS label, {node_var}.name AS name, "
                    f"coalesce({node_var}.source,'') AS source"
                )
    if not clauses:
        return [], 0
    params["q"] = q
    cypher = " UNION ".join(clauses)
    try:
        rows = neo4j_client.run_query(cypher, params)
    except Exception as e:  # noqa: BLE001
        logger.warning("knowledge search failed: %s", e)
        return [], 0

    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]
    items = []
    for r in page_rows:
        label = r["label"]
        name = r["name"]
        items.append({
            "type": label.lower(),
            "name": name,
            "title": f"{_LABEL_CN.get(label, label)} · {name}",
            "description": _describe(label, name),
            "source": r.get("source") or "",
        })
    return items, total


def symptom_names_contained(text: str) -> list[str]:
    """返回出现在文本中的图谱症状名（含别名，用于无 LLM 时的实体抽取降级）。"""
    if not text or not _graph_available():
        return []
    try:
        rows = neo4j_client.run_query(
            "MATCH (s:Symptom) RETURN s.name AS name, s.aliases AS aliases"
        )
        # 按名称长度降序，优先匹配更长（更具体）的症状
        rows = sorted(rows, key=lambda r: len(r.get("name") or ""), reverse=True)
        hit = []
        for r in rows:
            name = r.get("name")
            aliases = r.get("aliases") or []
            if name and (name in text or any(a and a in text for a in aliases)):
                hit.append(name)
        return hit
    except Exception as e:  # noqa: BLE001
        logger.warning("symptom_names_contained failed: %s", e)
        return []


def _describe(label: str, name: str) -> str:
    prop = {
        "Formula": "effects", "Herb": "effects", "Syndrome": "definition", "Symptom": "nature",
    }.get(label, "name")
    try:
        rows = neo4j_client.run_query(
            f"MATCH (n:{label} {{name: $name}}) RETURN coalesce(n.{prop}, toString(n.name)) AS v LIMIT 1",
            {"name": name},
        )
        if rows:
            v = rows[0]["v"]
            if isinstance(v, list):
                v = "、".join(v)
            return str(v)[:160]
    except Exception:  # noqa: BLE001
        pass
    return ""


def get_node_detail(label: str, name: str) -> Optional[NodeDetail]:
    if not _graph_available():
        return None
    label = label.capitalize()
    allowed = {"Formula", "Herb", "Syndrome", "Symptom"}
    if label not in allowed:
        return None
    try:
        node_rows = neo4j_client.run_query(
            f"MATCH (n:{label} {{name: $name}}) RETURN properties(n) AS props", {"name": name}
        )
        if not node_rows:
            return None
        props = _json_properties(node_rows[0]["props"])
        rels = [
            ("CONTAINS", "Herb", "CONTAINS"),
            ("TREATS", "Syndrome", "TREATS"),
            ("MANIFESTS", "Symptom", "MANIFESTS"),
            ("HAS_EFFECT", "Effect", "HAS_EFFECT"),
            ("ENTERS", "Meridian", "ENTERS"),
        ]
        neighbors: list[Neighbor] = []
        for rel, target_label, _rel_name in rels:
            try:
                rows = neo4j_client.run_query(
                    f"MATCH (n:{label} {{name: $name}})-[r:{rel}]->(m:{target_label}) "
                    f"RETURN r AS rel, properties(m) AS props, labels(m) AS labels LIMIT 20",
                    {"name": name},
                )
                for r in rows:
                    neighbors.append(Neighbor(
                        relation=rel,
                        related=KnowledgeNode(
                            name=r["props"].get("name", ""),
                            label=r["labels"][0],
                            properties=_json_properties(r["props"]),
                        ),
                    ))
            except Exception:  # noqa: BLE001
                continue
        # 反向关系（如 Formula <- TREATS）
        reverse_rels = [
            ("Herb", "Formula", "CONTAINS", "CONTAINS"),
            ("Syndrome", "Formula", "TREATS", "TREATS"),
            ("Symptom", "Syndrome", "MANIFESTS", "MANIFESTS"),
        ]
        for target_label, from_label, rel, rel_name in reverse_rels:
            if target_label != label:
                continue
            try:
                rows = neo4j_client.run_query(
                    f"MATCH (n:{target_label} {{name: $name}})<-[r:{rel}]-(m:{from_label}) "
                    f"RETURN properties(m) AS props, labels(m) AS labels LIMIT 20",
                    {"name": name},
                )
                for r in rows:
                    neighbors.append(Neighbor(
                        relation=rel + "(反向)",
                        related=KnowledgeNode(
                            name=r["props"].get("name", ""),
                            label=r["labels"][0],
                            properties=_json_properties(r["props"]),
                        ),
                    ))
            except Exception:  # noqa: BLE001
                continue
        return NodeDetail(node=KnowledgeNode(name=name, label=label, properties=props), neighbors=neighbors)
    except Exception as e:  # noqa: BLE001
        logger.warning("get_node_detail failed %s/%s: %s", label, name, e)
        return None


def stats() -> dict:
    out = {"herbs": 0, "formulas": 0, "syndromes": 0, "symptoms": 0}
    if not _graph_available():
        return out
    try:
        for k, lab in [("herbs", "Herb"), ("formulas", "Formula"), ("syndromes", "Syndrome"), ("symptoms", "Symptom")]:
            rows = neo4j_client.run_query(f"MATCH (n:{lab}) RETURN count(n) AS c")
            out[k] = rows[0]["c"] if rows else 0
    except Exception as e:  # noqa: BLE001
        logger.warning("graph stats failed: %s", e)
    return out


# ---------------- GraphRAG 检索 ----------------
def _vector_query(embedding: list[float], label: Optional[str], top_k: int) -> list[dict]:
    if not _vector_available():
        return []
    try:
        return milvus_client.search(embedding, top_k=top_k, label=label)
    except Exception as e:  # noqa: BLE001
        logger.warning("vector search failed: %s", e)
        return []


def _rrf(rank_list: list[int], k: int = 60) -> float:
    """Reciprocal Rank Fusion：多通道独立 rank → 加权求和。

    k=60 是 TREC 标准，避免第一名分数过高；两边证据平等贡献，
    不硬编码"图谱优先"bias。
    """
    return sum(1.0 / (k + r) for r in rank_list)


def graphrag_retrieve(symptoms: list[str], syndrome_hint: Optional[str], embedding: Optional[list[float]] = None) -> dict:
    """Neo4j 图谱 + Milvus 向量独立 rank → RRF 融合，返回证型/方剂/中药/症状及可解释 graph_refs。"""
    result: dict[str, Any] = {
        "syndromes": [], "formulas": [], "herbs": [], "symptoms": list(symptoms),
        "symptom_matches": [],
        "graph_refs": [], "knowledge_text": "", "available": False,
    }
    if not _graph_available() and not _vector_available():
        return result

    # ── 通道 1：图谱检索（沿 MANIFESTS 按命中数排序，rank=hit 位置）
    graph_syndromes: list[tuple[str, dict, int]] = []  # (name, props, hit)
    if symptoms and _graph_available():
        try:
            cypher = (
                "MATCH (sy:Syndrome)-[r:MANIFESTS]->(s:Symptom) "
                "WHERE s.name IN $symptoms "
                "WITH sy, count(s) AS hit "
                "RETURN sy.name AS name, properties(sy) AS props, hit "
                "ORDER BY hit DESC LIMIT 10"
            )
            graph_syndromes = [
                (r["name"], r["props"], r["hit"])
                for r in neo4j_client.run_query(cypher, {"symptoms": symptoms})
                if r.get("name")
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("graph retrieve syndromes failed: %s", e)

    # 若指定证型名，直接命中（rank=1）
    if syndrome_hint and _graph_available():
        try:
            direct = neo4j_client.run_query(
                "MATCH (sy:Syndrome) WHERE sy.name CONTAINS $h RETURN properties(sy) AS props LIMIT 3",
                {"h": syndrome_hint},
            )
            for r in direct:
                name = r["props"].get("name", "")
                if name and not any(g[0] == name for g in graph_syndromes):
                    graph_syndromes.append((name, r["props"], 999))
        except Exception as e:  # noqa: BLE001
            logger.warning("graph direct syndrome failed: %s", e)

    # ── 通道 2：向量检索（按 cosine 排序，rank=位置）
    vector_syndromes: list[str] = []
    if embedding is not None and _vector_available():
        try:
            vector_syndromes = [
                h["node_id"] for h in _vector_query(embedding, label="Syndrome", top_k=10)
                if h.get("node_id")
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("vector retrieve syndromes failed: %s", e)

    # ── RRF 融合
    rrf_scores: dict[str, float] = {}
    # 图谱通道：按 hit 降序排 → rank=位置
    graph_sorted = sorted(graph_syndromes, key=lambda x: -x[2])
    for rank, (name, _props, _hit) in enumerate(graph_sorted, start=1):
        rrf_scores[name] = rrf_scores.get(name, 0.0) + _rrf([rank])
    # 向量通道：按返回顺序 → rank=位置
    for rank, name in enumerate(vector_syndromes, start=1):
        rrf_scores[name] = rrf_scores.get(name, 0.0) + _rrf([rank])

    # 取 top3
    top_names = sorted(rrf_scores.keys(), key=lambda n: -rrf_scores[n])[:3]

    for name in top_names:
        props = next((g[1] for g in graph_sorted if g[0] == name), {})
        result["syndromes"].append({"name": name, "props": props})
        result["graph_refs"].append(GraphRef(
            label="Syndrome", name=name,
            source=props.get("source", ""),
            description=props.get("definition", ""),
        ).model_dump())
        # 沿 TREATS 反向取代表方，再沿 CONTAINS 取药（只走图谱，不影响 RRF）
        if _graph_available() and props:
            try:
                formula_rows = neo4j_client.run_query(
                    "MATCH (f:Formula)-[:TREATS]->(sy:Syndrome {name:$n}) "
                    "RETURN properties(f) AS props", {"n": name},
                )
                for fr in formula_rows[:3]:
                    fp = fr["props"]
                    result["formulas"].append({"name": fp.get("name", ""), "props": fp})
                    result["graph_refs"].append(GraphRef(
                        label="Formula", name=fp.get("name", ""),
                        source=fp.get("source", ""),
                        description="、".join(fp.get("effects", [])),
                    ).model_dump())
                    herb_rows = neo4j_client.run_query(
                        "MATCH (f:Formula {name:$n})-[:CONTAINS]->(h:Herb) "
                        "RETURN h.name AS name, properties(h) AS props LIMIT 12",
                        {"n": fp.get("name", "")},
                    )
                    for hr in herb_rows:
                        hp = hr["props"]
                        result["herbs"].append({"name": hr["name"], "props": hp})
            except Exception as e:  # noqa: BLE001
                logger.warning("graph formula expand failed: %s", e)

    # 向量检索补充方剂/中药/症状（RRF 主要用于证型排序，其他类型继续补位）
    if embedding is not None and _vector_available():
        for lab, key in [("Formula", "formulas"), ("Herb", "herbs"), ("Symptom", "symptom_matches")]:
            hits = _vector_query(embedding, label=lab, top_k=3)
            for h in hits:
                existing_names = {x["name"] for x in result[key] if "name" in x}
                if h.get("node_id") and h["node_id"] not in existing_names:
                    result[key].append({"name": h["node_id"], "props": {}, "_vector": True})

    # 去重 herbs
    seen = set()
    herbs = []
    for h in result["herbs"]:
        if h.get("name") and h["name"] not in seen:
            seen.add(h["name"])
            herbs.append(h)
    result["herbs"] = herbs

    result["available"] = bool(result["syndromes"] or result["formulas"])
    result["knowledge_text"] = _build_knowledge_text(result)
    return _json_properties(result)


def _build_knowledge_text(result: dict) -> str:
    parts = []
    if result["syndromes"]:
        parts.append("证型：" + "、".join(x["name"] for x in result["syndromes"][:3]))
    if result["formulas"]:
        parts.append("方剂：" + "、".join(x["name"] for x in result["formulas"][:5]))
    if result["herbs"]:
        parts.append("中药：" + "、".join(x["name"] for x in result["herbs"][:12]))
    return "\n".join(parts)

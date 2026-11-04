# ============================================
# 法规知识图谱
# 功能：构建证券法规的结构化知识图谱
# 节点类型：法规、条款、违规案例、处罚结果、监管机构
# 关系类型：包含、引用、处罚、关联
#
# 图结构示例：
#   《证券法》──包含──→ 第39条──引用──→ 违规案例A
#                                    └──处罚──→ 罚款50万
# ============================================

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json  # JSON 序列化
from typing import List, Dict, Optional, Tuple  # 类型注解
from dataclasses import dataclass, field  # 数据类
from datetime import datetime  # 时间戳

# NetworkX 用于构建和查询图结构
import networkx as nx


# ============================================
# 第 1 步：定义图谱节点和关系类型
# ============================================

class NodeType:
    """节点类型常量"""
    REGULATION = "法规"          # 法规（如《证券法》）
    ARTICLE = "条款"             # 具体条款（如第39条）
    CASE = "违规案例"            # 历史违规案例
    PENALTY = "处罚结果"         # 处罚结果
    AGENCY = "监管机构"          # 监管机构（如证监会）
    RULE = "交易规则"            # 交易规则（与 week7 风控规则对应）
    STOCK = "标的"               # 涉及的股票/ETF


class RelationType:
    """关系类型常量"""
    CONTAINS = "包含"            # 法规 → 条款
    CITES = "引用"               # 条款 → 案例
    PENALIZES = "处罚"           # 案例 → 处罚结果
    ENFORCES = "执法"            # 监管机构 → 法规
    RELATES_TO = "关联"          # 条款 → 交易规则
    INVOLVES = "涉及"            # 案例 → 标的


# ============================================
# 第 2 步：定义图谱节点数据类
# ============================================

@dataclass
class GraphNode:
    """
    知识图谱节点

    属性：
    - node_id: 唯一标识（如"REG-001"）
    - node_type: 节点类型（法规/条款/案例/处罚）
    - name: 节点名称
    - content: 节点内容（法规全文、案例描述等）
    - metadata: 附加元数据
    """
    node_id: str                    # 唯一标识
    node_type: str                  # 节点类型
    name: str                       # 节点名称
    content: str = ""               # 节点内容
    metadata: Dict = field(default_factory=dict)  # 附加元数据

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "name": self.name,
            "content": self.content[:200],
            "metadata": self.metadata
        }


# ============================================
# 第 3 步：构建法规知识图谱
# ============================================

class LegalKnowledgeGraph:
    """
    证券法规知识图谱

    使用 NetworkX 有向图存储节点和关系
    支持：
    - 按法规查询所有条款
    - 按条款查询相关案例
    - 按案例查询处罚结果
    - 按交易规则反查法律依据
    """

    def __init__(self):
        """初始化图谱并加载预设的法规数据"""
        # 创建有向图
        self.graph = nx.DiGraph()

        # 加载预设法规数据
        self._load_preset_data()

        print(f"✅ 法规知识图谱已初始化")
        print(f"   节点数：{self.graph.number_of_nodes()}")
        print(f"   关系数：{self.graph.number_of_edges()}")

    # ============================================
    # 添加节点和关系的方法
    # ============================================

    def add_node(self, node: GraphNode) -> None:
        """
        添加一个节点到图谱

        参数：
            node: GraphNode 对象
        """
        self.graph.add_node(
            node.node_id,
            node_type=node.node_type,
            name=node.name,
            content=node.content,
            metadata=node.metadata
        )

    def add_relation(self, from_id: str, to_id: str, relation_type: str, description: str = "") -> None:
        """
        添加两个节点之间的关系

        参数：
            from_id: 起始节点 ID
            to_id: 目标节点 ID
            relation_type: 关系类型（包含/引用/处罚/执法/关联）
            description: 关系描述
        """
        self.graph.add_edge(
            from_id, to_id,
            relation_type=relation_type,
            description=description
        )

    # ============================================
    # 查询方法
    # ============================================

    def get_articles_by_regulation(self, regulation_id: str) -> List[Dict]:
        """
        查询某法规下的所有条款

        参数：
            regulation_id: 法规节点 ID

        返回：
            条款节点列表
        """
        articles = []
        # 遍历该节点的所有后继节点
        for neighbor in self.graph.successors(regulation_id):
            edge_data = self.graph.get_edge_data(regulation_id, neighbor)
            if edge_data and edge_data.get("relation_type") == RelationType.CONTAINS:
                node_data = self.graph.nodes[neighbor]
                articles.append({
                    "node_id": neighbor,
                    "name": node_data["name"],
                    "content": node_data["content"]
                })
        return articles

    def get_cases_by_article(self, article_id: str) -> List[Dict]:
        """
        查询某条款相关的违规案例

        参数：
            article_id: 条款节点 ID

        返回：
            案例节点列表
        """
        cases = []
        for neighbor in self.graph.successors(article_id):
            edge_data = self.graph.get_edge_data(article_id, neighbor)
            if edge_data and edge_data.get("relation_type") == RelationType.CITES:
                node_data = self.graph.nodes[neighbor]
                cases.append({
                    "node_id": neighbor,
                    "name": node_data["name"],
                    "content": node_data["content"]
                })
        return cases

    def get_penalty_by_case(self, case_id: str) -> Optional[Dict]:
        """
        查询某案例的处罚结果

        参数：
            case_id: 案例节点 ID

        返回：
            处罚节点字典，如果没有则返回 None
        """
        for neighbor in self.graph.successors(case_id):
            edge_data = self.graph.get_edge_data(case_id, neighbor)
            if edge_data and edge_data.get("relation_type") == RelationType.PENALIZES:
                node_data = self.graph.nodes[neighbor]
                return {
                    "node_id": neighbor,
                    "name": node_data["name"],
                    "content": node_data["content"]
                }
        return None

    def get_legal_basis_for_rule(self, rule_name: str) -> List[Dict]:
        """
        根据交易规则名称反查法律依据

        参数：
            rule_name: 规则名称（如"涨跌停限制"）

        返回：
            相关法规条款列表
        """
        results = []
        # 遍历所有节点，查找与规则关联的条款
        for node_id in self.graph.nodes:
            node_data = self.graph.nodes[node_id]
            if node_data.get("node_type") == NodeType.ARTICLE:
                metadata = node_data.get("metadata", {})
                related_rules = metadata.get("related_rules", [])
                if rule_name in related_rules:
                    # 找到该条款所属的法规
                    for predecessor in self.graph.predecessors(node_id):
                        pred_data = self.graph.nodes[predecessor]
                        if pred_data.get("node_type") == NodeType.REGULATION:
                            results.append({
                                "regulation": pred_data["name"],
                                "article": node_data["name"],
                                "content": node_data["content"]
                            })
        return results

    def search_by_keyword(self, keyword: str) -> List[Dict]:
        """
        按关键词搜索图谱

        参数：
            keyword: 搜索关键词

        返回：
            匹配的节点列表
        """
        results = []
        for node_id in self.graph.nodes:
            node_data = self.graph.nodes[node_id]
            # 在名称和内容中搜索关键词
            name = node_data.get("name", "")
            content = node_data.get("content", "")
            if keyword in name or keyword in content:
                results.append({
                    "node_id": node_id,
                    "node_type": node_data.get("node_type", ""),
                    "name": name,
                    "content": content[:200]
                })
        return results

    def query_trace(self, start_node_id: str) -> List[str]:
        """
        从某个节点出发，追溯完整的关联链

        参数：
            start_node_id: 起始节点 ID

        返回：
            关联链的文本描述列表
        """
        trace = []
        visited = set()

        def dfs(node_id, depth=0):
            if node_id in visited or depth > 5:
                return
            visited.add(node_id)
            node_data = self.graph.nodes[node_id]
            trace.append(f"{'  ' * depth}{node_data.get('name', node_id)}")

            for neighbor in self.graph.successors(node_id):
                dfs(neighbor, depth + 1)

        dfs(start_node_id)
        return trace

    # ============================================
    # 导出方法
    # ============================================

    def to_dict(self) -> Dict:
        """将图谱导出为字典（方便 JSON 序列化）"""
        nodes = []
        for node_id in self.graph.nodes:
            data = self.graph.nodes[node_id]
            nodes.append({
                "node_id": node_id,
                "node_type": data.get("node_type", ""),
                "name": data.get("name", ""),
                "content": data.get("content", "")[:200]
            })

        edges = []
        for from_id, to_id in self.graph.edges:
            data = self.graph.get_edge_data(from_id, to_id)
            edges.append({
                "from": from_id,
                "to": to_id,
                "relation_type": data.get("relation_type", ""),
                "description": data.get("description", "")
            })

        return {"nodes": nodes, "edges": edges}

    def print_summary(self):
        """打印图谱摘要"""
        print("\n" + "=" * 50)
        print("📊 法规知识图谱摘要")
        print("=" * 50)

        # 统计各类型节点数量
        type_counts = {}
        for node_id in self.graph.nodes:
            node_type = self.graph.nodes[node_id].get("node_type", "未知")
            type_counts[node_type] = type_counts.get(node_type, 0) + 1

        for node_type, count in type_counts.items():
            print(f"  {node_type}：{count} 个")

        print(f"  总关系数：{self.graph.number_of_edges()}")

    # ============================================
    # 加载预设法规数据
    # ============================================

    def _load_preset_data(self):
        """加载预设的中国证券法规数据"""

        # ---- 法规节点 ----
        self.add_node(GraphNode(
            "REG-001", NodeType.REGULATION, "《中华人民共和国证券法》",
            "2019年修订，共14章226条",
            {"version": "2019", "chapters": 14, "articles": 226}
        ))
        self.add_node(GraphNode(
            "REG-002", NodeType.REGULATION, "《上海证券交易所交易规则》",
            "2023年修订",
            {"version": "2023"}
        ))
        self.add_node(GraphNode(
            "REG-003", NodeType.REGULATION, "《上市公司信息披露管理办法》",
            "2021年修订",
            {"version": "2021"}
        ))

        # ---- 条款节点 ----
        self.add_node(GraphNode(
            "ART-001", NodeType.ARTICLE, "证券法第39条（T+1交割）",
            "依法公开发行的证券，应当在依法设立的证券交易所上市交易或者在国务院批准的其他全国性证券交易场所交易。当日买入的证券，当日不得卖出。",
            {"related_rules": ["T+1 交割制度检查"]}
        ))
        self.add_node(GraphNode(
            "ART-002", NodeType.ARTICLE, "证券法第55条（内幕交易）",
            "禁止证券交易内幕信息的知情人和非法获取内幕信息的人利用内幕信息从事证券交易活动。",
            {"related_rules": ["内幕交易检查"]}
        ))
        self.add_node(GraphNode(
            "ART-003", NodeType.ARTICLE, "交易规则第3.3.1条（涨跌停）",
            "股票交易实行价格涨跌幅限制，主板涨跌幅限制比例为10%，创业板和科创板为20%。",
            {"related_rules": ["涨跌停限制检查"]}
        ))
        self.add_node(GraphNode(
            "ART-004", NodeType.ARTICLE, "信息披露第12条（关联交易）",
            "上市公司与关联方发生的交易金额超过公司最近一期经审计净资产绝对值5%的，应当及时披露。",
            {"related_rules": ["关联交易合规检查"]}
        ))

        # ---- 违规案例节点 ----
        self.add_node(GraphNode(
            "CASE-001", NodeType.CASE, "某私募基金T+0交易案",
            "2024年，某私募基金利用融券变相实施T+0交易，当日买入后当日卖出，被证监会查获。",
            {"year": 2024, "involved_asset": "多只A股"}
        ))
        self.add_node(GraphNode(
            "CASE-002", NodeType.CASE, "某上市公司高管内幕交易案",
            "2023年，某上市公司高管在重大资产重组信息公布前买入本公司股票，获利1200万元。",
            {"year": 2023, "involved_asset": "该公司股票"}
        ))
        self.add_node(GraphNode(
            "CASE-003", NodeType.CASE, "某游资操纵市场案",
            "2024年，某游资利用多个账户对倒拉抬股价，触发多次涨跌停后被交易所重点监控。",
            {"year": 2024, "involved_asset": "多只小盘股"}
        ))

        # ---- 处罚结果节点 ----
        self.add_node(GraphNode(
            "PEN-001", NodeType.PENALTY, "没收违法所得 + 罚款500万",
            "没收违法所得，并处交易金额1倍罚款，暂停交易权限6个月。"
        ))
        self.add_node(GraphNode(
            "PEN-002", NodeType.PENALTY, "罚款1200万 + 市场禁入",
            "没收违法所得1200万元，罚款2400万元，终身证券市场禁入。"
        ))
        self.add_node(GraphNode(
            "PEN-003", NodeType.PENALTY, "限制交易 + 罚款200万",
            "限制交易3个月，罚款200万元，纳入诚信档案。"
        ))

        # ---- 监管机构节点 ----
        self.add_node(GraphNode(
            "AGY-001", NodeType.AGENCY, "中国证监会",
            "国务院直属正部级事业单位，依法对全国证券期货市场实行集中统一监督管理。"
        ))
        self.add_node(GraphNode(
            "AGY-002", NodeType.AGENCY, "上海证券交易所",
            "依法对证券交易活动实行自律管理。"
        ))

        # ---- 关系 ----
        # 法规包含条款
        self.add_relation("REG-001", "ART-001", RelationType.CONTAINS, "证券法第39条")
        self.add_relation("REG-001", "ART-002", RelationType.CONTAINS, "证券法第55条")
        self.add_relation("REG-002", "ART-003", RelationType.CONTAINS, "交易规则第3.3.1条")
        self.add_relation("REG-003", "ART-004", RelationType.CONTAINS, "信息披露第12条")

        # 条款引用案例
        self.add_relation("ART-001", "CASE-001", RelationType.CITES, "T+1违规案例")
        self.add_relation("ART-002", "CASE-002", RelationType.CITES, "内幕交易案例")
        self.add_relation("ART-003", "CASE-003", RelationType.CITES, "涨跌停操纵案例")

        # 案例对应处罚
        self.add_relation("CASE-001", "PEN-001", RelationType.PENALIZES, "T+0交易处罚")
        self.add_relation("CASE-002", "PEN-002", RelationType.PENALIZES, "内幕交易处罚")
        self.add_relation("CASE-003", "PEN-003", RelationType.PENALIZES, "操纵市场处罚")

        # 监管机构执法
        self.add_relation("AGY-001", "REG-001", RelationType.ENFORCES, "证监会执行证券法")


# ============================================
# 第 4 步：知识图谱查询接口
# ============================================

class LegalQueryService:
    """
    法规查询服务

    提供面向智能体的高级查询接口
    """

    def __init__(self):
        self.kg = LegalKnowledgeGraph()

    def check_compliance(self, rule_name: str, intent_summary: str) -> str:
        """
        检查某交易意图的合规性，返回法规依据和案例参考

        参数：
            rule_name: 触发的规则名称
            intent_summary: 交易意图摘要

        返回：
            合规检查报告文本
        """
        # 查找法律依据
        legal_basis = self.kg.get_legal_basis_for_rule(rule_name)

        if not legal_basis:
            return f"未找到与「{rule_name}」相关的法规依据"

        lines = []
        lines.append(f"📋 合规检查：{rule_name}")
        lines.append(f"   交易意图：{intent_summary}")
        lines.append("")

        for item in legal_basis:
            lines.append(f"📜 法律依据：{item['regulation']} - {item['article']}")
            lines.append(f"   条文内容：{item['content'][:150]}...")
            lines.append("")

            # 查找相关案例
            # 从 article 名称中提取条款编号
            article_name = item["article"]
            for node_id in self.kg.graph.nodes:
                node_data = self.kg.graph.nodes[node_id]
                if node_data.get("name") == article_name:
                    cases = self.kg.get_cases_by_article(node_id)
                    for case in cases:
                        lines.append(f"   ⚠️ 相关案例：{case['name']}")
                        lines.append(f"      案例详情：{case['content'][:150]}...")

                        # 查找处罚结果
                        penalty = self.kg.get_penalty_by_case(case["node_id"])
                        if penalty:
                            lines.append(f"   🚫 处罚结果：{penalty['name']}")
                        lines.append("")

        return "\n".join(lines)

    def search_by_behavior(self, behavior: str) -> str:
        """
        根据交易行为搜索相关法规

        参数：
            behavior: 交易行为描述（如"当日买入后卖出"）

        返回：
            相关法规和案例
        """
        results = self.kg.search_by_keyword(behavior)
        if not results:
            return f"未找到与「{behavior}」相关的法规"

        lines = [f"🔍 搜索「{behavior}」相关法规："]
        for r in results[:5]:
            lines.append(f"  [{r['node_type']}] {r['name']}")
            lines.append(f"    {r['content'][:100]}...")
        return "\n".join(lines)

    def get_penalty_risk(self, rule_name: str) -> str:
        """
        评估违反某规则的处罚风险

        参数：
            rule_name: 规则名称

        返回：
            风险评估文本
        """
        legal_basis = self.kg.get_legal_basis_for_rule(rule_name)
        if not legal_basis:
            return "无法评估处罚风险"

        lines = [f"⚠️ 处罚风险评估：{rule_name}"]
        for item in legal_basis:
            article_name = item["article"]
            for node_id in self.kg.graph.nodes:
                node_data = self.kg.graph.nodes[node_id]
                if node_data.get("name") == article_name:
                    cases = self.kg.get_cases_by_article(node_id)
                    for case in cases:
                        penalty = self.kg.get_penalty_by_case(case["node_id"])
                        if penalty:
                            lines.append(f"   参考案例：{case['name']}")
                            lines.append(f"   处罚结果：{penalty['name']}")
        return "\n".join(lines)


# ============================================
# 第 5 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 法规知识图谱测试")
    print("=" * 60)

    # 创建查询服务
    service = LegalQueryService()
    service.kg.print_summary()

    # 测试 1：查询法规下的条款
    print("\n" + "=" * 60)
    print("测试 1：查询《证券法》下的所有条款")
    print("=" * 60)
    articles = service.kg.get_articles_by_regulation("REG-001")
    for a in articles:
        print(f"  📜 {a['name']}")
        print(f"     {a['content'][:100]}...")

    # 测试 2：合规检查
    print("\n" + "=" * 60)
    print("测试 2：合规检查——T+1 制度")
    print("=" * 60)
    report = service.check_compliance(
        "T+1 交割制度检查",
        "某账户今日买入茅台 1000 股后立即卖出"
    )
    print(report)

    # 测试 3：处罚风险评估
    print("\n" + "=" * 60)
    print("测试 3：处罚风险评估——涨跌停操纵")
    print("=" * 60)
    risk = service.get_penalty_risk("涨跌停限制检查")
    print(risk)

    # 测试 4：行为搜索
    print("\n" + "=" * 60)
    print("测试 4：行为搜索——内幕交易")
    print("=" * 60)
    result = service.search_by_behavior("内幕交易")
    print(result)

    # 测试 5：追溯关联链
    print("\n" + "=" * 60)
    print("测试 5：追溯《证券法》的完整关联链")
    print("=" * 60)
    trace = service.kg.query_trace("REG-001")
    for t in trace:
        print(f"  {t}")

    print("\n" + "=" * 60)
    print("✅ 法规知识图谱测试完成")
    print("=" * 60)
# ============================================
# 风控告警模块
# 功能：当风控触发拦截或警告时，自动发送飞书消息
# 告警内容包括：
#   - 被拦截的交易意图详情
#   - 触发拦截的具体规则和原因
#   - 阈值 vs 实际值对比
#   - 处理建议
# ============================================

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import json  # JSON 序列化
import requests  # HTTP 请求（调用飞书 API）
from datetime import datetime  # 时间戳
from typing import List  # 类型注解

# 导入风控模型
from risk_models import RiskEngineResult, RiskCheckResult, RiskLevel

# 导入交易意图模型
from trade_intent import TradeIntent


# ============================================
# 第 1 步：告警消息格式化
# ============================================

def format_alert_message(result: RiskEngineResult, intent: TradeIntent) -> str:
    """
    将风控检查结果格式化为飞书可读的告警消息
    
    参数：
        result: 风控引擎的检查结果
        intent: 被检查的交易意图
    
    返回：
        格式化的告警文本（纯文本，飞书消息格式）
    """
    # 根据风险等级选择标题和图标
    if result.risk_level == RiskLevel.BLOCK:
        title = "🚨 风控拦截警报"
        description = "以下交易意图被风控系统拦截，请人工复核"
    elif result.risk_level == RiskLevel.WARNING:
        title = "⚠️ 风控警告通知"
        description = "以下交易意图触发风控警告，已放行但需关注"
    else:
        title = "✅ 风控检查通过"
        description = "以下交易意图已通过全部风控检查"
    
    # 构建消息文本
    lines = []
    lines.append(title)
    lines.append("")
    lines.append(description)
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    
    # 交易意图摘要
    dir_icon = {"买入": "🔴", "卖出": "🟢", "持有": "⚪"}
    icon = dir_icon.get(intent.direction.value, "❓")
    
    lines.append(f"📊 交易意图：{icon} {intent.direction.value} {intent.name}（{intent.symbol}）")
    lines.append(f"   数量：{intent.quantity} 股")
    lines.append(f"   单价：{intent.price:.2f} 元")
    lines.append(f"   总金额：{intent.total_amount:,.2f} 元")
    lines.append(f"   来源：{intent.source.value}")
    lines.append(f"   置信度：{intent.confidence:.0%}")
    lines.append(f"   理由：{intent.reason}")
    lines.append("")
    
    # 检查结果汇总
    lines.append(f"📋 检查结果：{result.total_rules} 条规则，{result.passed_rules} 通过，{result.blocked_rules} 拦截，{result.warning_rules} 警告")
    lines.append("")
    
    # 详细列出每条未通过的规则
    failed_rules = [r for r in result.results if not r.passed]
    if failed_rules:
        lines.append("❌ 未通过的规则：")
        lines.append("")
        for i, rule_result in enumerate(failed_rules, 1):
            # 等级图标
            level_icon = "🚫" if rule_result.level == RiskLevel.BLOCK else "⚠️"
            lines.append(f"  {i}. {level_icon} {rule_result.rule_name}")
            lines.append(f"     {rule_result.message}")
            
            # 如果有详细信息，展示阈值 vs 实际值
            if rule_result.details:
                for key, value in rule_result.details.items():
                    # 跳过过长的值
                    if isinstance(value, float):
                        lines.append(f"     - {key}: {value:,.2f}")
                    else:
                        lines.append(f"     - {key}: {value}")
            lines.append("")
    
    # 处理建议
    lines.append("💡 处理建议：")
    if result.risk_level == RiskLevel.BLOCK:
        lines.append("   1. 检查交易参数是否合理")
        lines.append("   2. 如需执行，请调整交易金额或置信度后重试")
        lines.append("   3. 或联系管理员申请临时额度提升")
    elif result.risk_level == RiskLevel.WARNING:
        lines.append("   1. 该交易已自动放行")
        lines.append("   2. 建议后续关注相关风险指标")
        lines.append("   3. 如频繁触发警告，需调整风控阈值")
    lines.append("")
    
    # 时间戳
    lines.append(f"⏰ 检查时间：{result.checked_at}")
    lines.append(f"🔗 意图 ID：{result.intent_id}")
    
    return "\n".join(lines)


# ============================================
# 第 2 步：飞书消息发送
# ============================================

def get_feishu_token() -> str:
    """
    获取飞书 tenant_access_token
    
    返回：
        token 字符串，失败返回空
    """
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    
    if not app_id or not app_secret:
        print("⚠️ 飞书凭证未配置，跳过告警发送")
        return ""
    
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": app_id, "app_secret": app_secret}
    headers = {"Content-Type": "application/json"}
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            return data["tenant_access_token"]
        else:
            print(f"❌ 获取飞书 Token 失败：{data}")
            return ""
    except Exception as e:
        print(f"❌ 获取飞书 Token 异常：{e}")
        return ""


def send_feishu_alert(message: str) -> bool:
    """
    通过飞书机器人发送告警消息
    
    参数：
        message: 告警消息文本
    
    返回：
        True 发送成功，False 发送失败
    """
    # 获取飞书群聊 ID
    chat_id = os.getenv("FEISHU_CHAT_ID", "")
    
    if not chat_id:
        print("⚠️ FEISHU_CHAT_ID 未配置，告警消息仅打印到控制台")
        print(f"\n{'=' * 40}")
        print("📢 告警消息预览：")
        print(message)
        print(f"{'=' * 40}\n")
        return False
    
    # 获取 Token
    token = get_feishu_token()
    if not token:
        # Token 获取失败，降级为控制台打印
        print(f"\n{'=' * 40}")
        print("📢 告警消息（飞书发送失败，降级为控制台打印）：")
        print(message)
        print(f"{'=' * 40}\n")
        return False
    
    # 调用飞书 API 发送消息
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": message})
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            print(f"✅ 飞书告警发送成功，消息 ID：{data['data']['message_id']}")
            return True
        else:
            print(f"❌ 飞书告警发送失败：{data.get('msg', '')}")
            # 降级打印
            print(f"\n{'=' * 40}")
            print("📢 告警消息（降级打印）：")
            print(message[:500])
            print(f"{'=' * 40}\n")
            return False
    except Exception as e:
        print(f"❌ 飞书告警异常：{e}")
        return False


# ============================================
# 第 3 步：带告警的风控引擎包装器
# ============================================

class AlertingRiskEngine:
    """
    带告警功能的风控引擎包装器
    
    在原有 RiskEngine 基础上增加：
    1. 拦截时自动发送飞书告警
    2. 警告时发送提醒通知
    3. 所有检查记录日志
    
    用法：
        engine = AlertingRiskEngine(base_engine)
        result = engine.check_with_alert(intent, context)
    """
    
    def __init__(self, base_engine):
        """
        初始化
        
        参数：
            base_engine: 原始的 RiskEngine 实例
        """
        self.base_engine = base_engine
        self.alert_history: List[dict] = []  # 告警历史记录
    
    def check_with_alert(
        self,
        intent: TradeIntent,
        context: dict = None,
        send_block_alert: bool = True,
        send_warning_alert: bool = True
    ) -> RiskEngineResult:
        """
        执行风控检查并在必要时发送告警
        
        参数：
            intent: 交易意图
            context: 上下文信息
            send_block_alert: 拦截时是否发送告警（默认 True）
            send_warning_alert: 警告时是否发送通知（默认 True）
        
        返回：
            风控检查结果
        """
        # 第一步：执行原始风控检查
        result = self.base_engine.check(intent, context)
        
        # 第二步：判断是否需要告警
        should_alert = False
        
        if result.risk_level == RiskLevel.BLOCK and send_block_alert:
            should_alert = True
        elif result.risk_level == RiskLevel.WARNING and send_warning_alert:
            should_alert = True
        
        # 第三步：发送告警
        if should_alert:
            print(f"\n🚨 风控触发，正在发送告警...")
            
            # 格式化告警消息
            alert_msg = format_alert_message(result, intent)
            
            # 发送飞书消息
            send_feishu_alert(alert_msg)
            
            # 记录告警历史
            alert_record = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "intent_id": intent.intent_id,
                "risk_level": result.risk_level.value,
                "blocked_rules": result.blocked_rules,
                "warning_rules": result.warning_rules
            }
            self.alert_history.append(alert_record)
        
        return result
    
    def get_alert_summary(self) -> str:
        """
        获取告警历史摘要
        
        返回：
            告警统计文本
        """
        if not self.alert_history:
            return "暂无告警记录"
        
        total = len(self.alert_history)
        blocks = sum(1 for a in self.alert_history if a["risk_level"] == "拦截")
        warnings = sum(1 for a in self.alert_history if a["risk_level"] == "警告")
        
        return (
            f"📊 告警统计：共 {total} 次\n"
            f"   拦截：{blocks} 次\n"
            f"   警告：{warnings} 次"
        )


# ============================================
# 第 4 步：批量模拟交易测试
# ============================================

def run_simulation(engine: AlertingRiskEngine, num_trades: int = 5) -> None:
    """
    运行模拟交易流——批量生成交易意图并过风控
    
    参数：
        engine: 带告警的风控引擎
        num_trades: 模拟交易数量
    """
    print("=" * 60)
    print(f"🧪 批量模拟交易测试（{num_trades} 笔）")
    print("=" * 60)
    
    # 导入交易意图构建器
    from trade_intent import TradeIntentBuilder
    import random  # 用于生成随机参数
    
    # 模拟账户上下文
    context = {
        "total_assets": 1_000_000,
        "current_holdings": 350_000,
        "symbol_holdings": {
            "600519.SH": 100_000,
            "000858.SZ": 80_000,
            "300750.SZ": 70_000
        },
        "daily_trade_count": 2
    }
    
    # 模拟交易参数池
    symbols = [
        ("600519.SH", "贵州茅台", 1500.0),
        ("000858.SZ", "五粮液", 120.0),
        ("300750.SZ", "宁德时代", 180.0),
        ("601318.SH", "中国平安", 45.0),
    ]
    
    # 逐笔生成并检查
    for i in range(1, num_trades + 1):
        print(f"\n{'─' * 40}")
        print(f"模拟交易 {i}/{num_trades}")
        print(f"{'─' * 40}")
        
        # 随机选择交易参数
        symbol, name, base_price = random.choice(symbols)
        direction = random.choice(["buy", "sell"])
        
        # 随机生成数量（有些正常，有些超大额）
        if random.random() < 0.3:
            # 30% 概率生成超大额交易（触发风控）
            quantity = random.randint(5000, 10000)
        else:
            # 正常交易
            quantity = random.randint(10, 500)
        
        price = base_price * random.uniform(0.9, 1.1)
        confidence = random.uniform(0.3, 0.95)
        
        # 构建交易意图
        if direction == "buy":
            intent = (TradeIntentBuilder()
                      .set_symbol(symbol)
                      .set_name(name)
                      .buy(quantity, price)
                      .from_factor(f"模拟因子{i}", confidence)
                      .with_reason(f"模拟交易理由 #{i}")
                      .build())
        else:
            intent = (TradeIntentBuilder()
                      .set_symbol(symbol)
                      .set_name(name)
                      .sell(quantity, price)
                      .from_factor(f"模拟因子{i}", confidence)
                      .with_reason(f"模拟交易理由 #{i}")
                      .build())
        
        print(intent)
        
        # 执行风控检查（带告警）
        result = engine.check_with_alert(intent, context)
        print(f"   结果：{result.summary}")
        
        # 更新上下文（模拟交易执行后的状态变化）
        if result.passed and direction == "buy":
            context["current_holdings"] += intent.total_amount
            context["daily_trade_count"] += 1
            if symbol in context["symbol_holdings"]:
                context["symbol_holdings"][symbol] += intent.total_amount
            else:
                context["symbol_holdings"][symbol] = intent.total_amount
    
    # 打印告警统计
    print(f"\n{'─' * 40}")
    print(engine.get_alert_summary())


# ============================================
# 第 5 步：测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚨 风控告警模块测试")
    print("=" * 60)
    
    # 导入风控引擎和规则
    from risk_models import RiskEngine
    from risk_rules import (
        SingleTradeLimitRule,
        TotalExposureRule,
        ConcentrationRiskRule,
        ConfidenceThresholdRule,
        DailyTradeFrequencyRule
    )
    
    # 创建风控引擎并注册规则
    print("\n初始化风控引擎...")
    base_engine = RiskEngine()
    base_engine.add_rule(SingleTradeLimitRule(max_amount=500000))
    base_engine.add_rule(ConfidenceThresholdRule(min_confidence=0.6))
    base_engine.add_rule(DailyTradeFrequencyRule(max_daily_trades=10))
    base_engine.add_rule(TotalExposureRule(max_exposure_pct=0.6))
    base_engine.add_rule(ConcentrationRiskRule(max_single_pct=0.3))
    
    # 包装为带告警的引擎
    alert_engine = AlertingRiskEngine(base_engine)
    
    print(f"\n已注册 {len(base_engine.list_rules())} 条规则")
    print(f"飞书告警：{'已配置' if os.getenv('FEISHU_CHAT_ID') else '未配置（降级为控制台打印）'}")
    
    # 运行模拟交易测试
    run_simulation(alert_engine, num_trades=8)
    
    print("\n" + "=" * 60)
    print("✅ 风控告警模块测试完成")
    print("=" * 60)
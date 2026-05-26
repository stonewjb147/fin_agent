# 定义简单移动平均（SMA）函数，接收价格列表和窗口大小两个参数
def sma(prices, window):
    # 如果窗口大小无效（<=0）或价格数据少于窗口所需数量，直接返回空列表
    if window <= 0 or len(prices) < window:
        return []
    
    # 初始化一个空列表，用于存储计算出的移动平均值
    result = []
    
    # 遍历价格列表，确保最后一次窗口起始索引不超出列表范围
    for i in range(len(prices) - window + 1):
        # 计算从索引 i 开始、长度为 window 的切片的总和，再除以 window 得到平均值
        avg = sum(prices[i:i+window]) / window
        # 将计算出的平均值添加到结果列表中
        result.append(avg)
    
    # 循环结束后，返回包含所有移动平均值的列表
    return result

# 计算 RSI 指标的函数，输入价格列表和周期（默认14），返回最新 RSI 值（0-100）,RSI指标是一种技术分析工具，用于衡量价格变动的速度和幅度，通常用于判断市场是否超买或超卖。RSI值在70以上表示超买，在30以下表示超卖。
# 定义相对强弱指数（RSI）函数，接收价格列表和周期（默认14）两个参数
def rsi(prices, period=14):
    # 如果价格数据不足一个完整周期+1（至少需要 period+1 个数据点才能计算变化），返回 None 表示无法计算
    if len(prices) < period + 1:
        return None
    
    # 初始化总涨幅变量（记录周期内所有上涨幅度的总和）
    gains = 0
    # 初始化总跌幅变量（记录周期内所有下跌幅度的总和，存储为正数）
    losses = 0
    
    # 遍历周期内的每一天（从第1天到第 period 天）
    for i in range(1, period + 1):
        # 计算当前价格与前一天的差值（当天变化量）
        delta = prices[i] - prices[i-1]
        
        # 如果差值为正（价格上涨）
        if delta > 0:
            # 将上涨幅度累加到 gains 中
            gains += delta
        else:
            # 如果差值为负（价格下跌），取绝对值后累加到 losses 中
            losses -= delta   # 因为 delta 为负数，减去负数等于加上正数
    
    # 计算周期内的平均涨幅（总涨幅 / 周期长度）
    avg_gain = gains / period
    # 计算周期内的平均跌幅（总跌幅 / 周期长度）
    avg_loss = losses / period
    
    # 如果平均跌幅为0（即周期内没有下跌），RSI 直接返回 100（表示极端超买）
    if avg_loss == 0:
        return 100.0
    
    # 计算相对强弱比率 RS（平均涨幅 / 平均跌幅）
    rs = avg_gain / avg_loss
    
    # 使用 RSI 标准公式计算：RSI = 100 - (100 / (1 + RS))
    rsi_val = 100 - (100 / (1 + rs))
    
    # 返回 RSI 值，并四舍五入保留两位小数
    return round(rsi_val, 2)

# 判断当前脚本是否作为主程序直接运行（而不是被其他模块导入）
if __name__ == '__main__':
    # 创建一个测试用的价格列表，包含10个价格数据
    test_prices = [10, 12, 14, 13, 15, 16, 18, 17, 19, 20]
    
    # 调用 sma 函数计算3日简单移动平均，并打印结果
    # sma(test_prices, 3) 会返回 [12.0, 13.0, 14.0, 14.67, 16.33, 17.0, 18.0, 18.67]
    print("SMA(3):", sma(test_prices, 3))
    
    # 调用 rsi 函数计算5日相对强弱指数，并打印结果
    # rsi(test_prices, 5) 会返回一个0-100之间的RSI值（例如 85.71 表示超买）
    print("RSI(5):", rsi(test_prices, 5))
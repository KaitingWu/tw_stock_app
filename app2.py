import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="股票潛力分析與買賣點工具", layout="wide")

st.title("📈 智慧選股與策略買賣點分析系統")

# 使用者輸入 10 檔股票代號（範例以截圖中的台股格式）
default_tickers = "6505.TW, 3706.TW, 2382.TW, 2408.TW, 8926.TW, 3481.TW, 2308.TW, 2379.TW, 8996.TW, 2352.TW"
tickers_input = st.text_input("請輸入 10 檔股票代號（以逗號分隔）：", default_tickers)

tickers = [t.strip() for t in tickers_input.split(",") if t.strip()]

# 用原生 pandas 計算 RSI，完全免裝額外套件
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="6mo")
        if df.empty or len(df) < 60:
            return None
        
        # 純 pandas 計算技術指標（取代 pandas_ta）
        df["MA20"] = df["Close"].rolling(window=20).mean()
        df["MA60"] = df["Close"].rolling(window=60).mean()
        df["RSI"] = compute_rsi(df["Close"], period=14)
        df["VOL_MA20"] = df["Volume"].rolling(window=20).mean()
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 評分系統（滿分 100）
        score = 0
        reasons = []
        
        # 1. 均線趨勢 (40 分)
        if latest["Close"] > latest["MA20"] > latest["MA60"]:
            score += 40
            reasons.append("短中期均線多頭排列")
        elif latest["Close"] > latest["MA20"]:
            score += 20
            reasons.append("站上月線")
            
        # 2. 動能評估 (30 分)
        rsi_val = latest["RSI"] if not pd.isna(latest["RSI"]) else 50
        if 50 <= rsi_val <= 70:
            score += 30
            reasons.append("動能偏多且未過熱 (RSI 50-70)")
        elif rsi_val > 70:
            score += 10
            reasons.append("超買警戒區 (RSI > 70)")
            
        # 3. 量能表現 (30 分)
        vol_ma = latest["VOL_MA20"] if latest["VOL_MA20"] > 0 else 1
        if latest["Volume"] > vol_ma * 1.2:
            score += 30
            reasons.append("量能增溫突破均量")
        else:
            score += 10
            
        # 買賣點訊號
        signal = "觀望 / 整理中"
        buy_price = round(latest["MA20"], 2)
        stop_loss = round(latest["MA60"] if latest["MA60"] < latest["Close"] else latest["Close"] * 0.93, 2)
        target_price = round(latest["Close"] * 1.15, 2)
        
        # 突破買點判斷
        if prev["Close"] <= prev["MA20"] and latest["Close"] > latest["MA20"] and latest["Volume"] > vol_ma:
            signal = "🟢 強烈買進 (放量站上月線)"
        elif latest["Close"] > latest["MA20"] and abs(latest["Close"] - latest["MA20"]) / latest["MA20"] < 0.02:
            signal = "🟡 回檔尋求支撐買點 (回測月線)"
        elif rsi_val > 80 or latest["Close"] < latest["MA20"]:
            signal = "🔴 賣出 / 停損訊號 (跌破月線或極度超買)"
            
        return {
            "代號": ticker,
            "收盤價": round(latest["Close"], 2),
            "綜合評分": score,
            "訊號判定": signal,
            "建議進場區間": f"{buy_price * 0.99:.1f} ~ {buy_price * 1.02:.1f}",
            "停損價位": stop_loss,
            "目標停利": target_price,
            "特徵分析": "、".join(reasons),
            "df": df
        }
    except Exception as e:
        return None

if st.button("開始掃描分析"):
    with st.spinner("資料抓取與模型評估中..."):
        results = []
        stock_dfs = {}
        for t in tickers[:10]:
            res = analyze_stock(t)
            if res:
                df_temp = res.pop("df")
                results.append(res)
                stock_dfs[res["代號"]] = df_temp
                
        if results:
            res_df = pd.DataFrame(results).sort_values(by="綜合評分", ascending=False)
            
            st.subheader("🏆 綜合潛力排名結果")
            st.dataframe(res_df.drop(columns=["特徵分析"]), use_container_width=True)
            
            top_stock = res_df.iloc[0]["代號"]
            st.markdown(f"### 🌟 目前最具發展性個股：**{top_stock}**（評分：{res_df.iloc[0]['綜合評分']} 分）")
            st.info(f"**核心理由：** {res_df.iloc[0]['特徵分析']}｜**訊號：** {res_df.iloc[0]['訊號判定']}")
            
            # 繪製 K 線圖與指標
            chart_stock = st.selectbox("選擇要查看 K 線的個股：", [r["代號"] for r in results])
            df_chart = stock_dfs[chart_stock]
            
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'],
                                         low=df_chart['Low'], close=df_chart['Close'], name='K線'))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA20'], line=dict(color='orange', width=1.5), name='月線 (20MA)'))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA60'], line=dict(color='blue', width=1.5), name='季線 (60MA)'))
            fig.update_layout(title=f"{chart_stock} 價量走勢與均線支撐", xaxis_rangeslider_visible=False, height=500)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("未能成功取得資料，請確認股票代號格式。")
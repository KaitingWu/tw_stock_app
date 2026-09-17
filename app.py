import streamlit as st
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from datetime import datetime, timedelta
import plotly.express as px

# 頁面基本配置
st.set_page_config(
    page_title="台股族群輪動監控儀表板",
    page_icon="📈",
    layout="wide"
)

# 預設觀察清單
DEFAULT_SECTOR_BASKETS = {
    "半導體/先進製程": ["2330", "2454", "3443", "3661", "2303"],
    "AI伺服器/組裝代工": ["2382", "2317", "3231", "6669", "2356"],
    "重電/綠能儲能": ["1519", "1503", "1513", "1514"],
    "散熱/水冷模組": ["3017", "3324", "2421", "8996"],
    "航運/貨櫃航空": ["2603", "2609", "2615", "2618", "2610"],
    "金融/金控": ["2881", "2882", "2886", "2891"],
    "生技醫療": ["1795", "4743", "6472", "6446"]
}

# ----------------- 資料快取取得函式 -----------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_finmind_institutional(stock_id: str, start_date: str, token: str) -> pd.DataFrame:
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": stock_id,
        "start_date": start_date,
        "token": token
    }
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if data.get("msg") == "success" and data.get("data"):
            df = pd.DataFrame(data["data"])
            df["buy"] = pd.to_numeric(df["buy"], errors="coerce")
            df["sell"] = pd.to_numeric(df["sell"], errors="coerce")
            df["net_buy"] = df["buy"] - df["sell"]
            daily_net = df.groupby("date")["net_buy"].sum().reset_index()
            daily_net["stock_id"] = stock_id
            return daily_net
    except Exception:
        pass
    return pd.DataFrame()

@st.cache_data(ttl=1800, show_spinner=False)
def get_market_price_data(stocks: list, benchmark="^TWII", days=40):
    end = datetime.today()
    start = end - timedelta(days=days)
    tickers = [f"{s}.TW" for s in stocks] + [benchmark]
    data = yf.download(tickers, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), progress=False)
    
    close = data["Close"] if "Close" in data else data["Adj Close"]
    volume = data["Volume"]
    return close.dropna(how="all"), volume.dropna(how="all")

# ----------------- 側邊欄配置 -----------------
st.sidebar.title("⚙️ 控制台")
finmind_token = st.sidebar.text_input("FinMind API Token (留空使用免費額度)", type="password")

st.sidebar.subheader("動態評分權重")
w_relative = st.sidebar.slider("超額大盤權重 (%)", 0, 100, 35) / 100
w_volume = st.sidebar.slider("爆量倍數權重 (%)", 0, 100, 35) / 100
w_mom = 1.0 - (w_relative + w_volume)
st.sidebar.caption(f"自動剩餘 5 日動能權重: {round(w_mom * 100, 1)}%")

reload_btn = st.sidebar.button("🔄 強制刷新行情資料")
if reload_btn:
    st.cache_data.clear()

# ----------------- 主體分析計算 -----------------
st.title("📊 台股短線強勢族群輪動監控系統")
st.caption("結合 5 日動能、大盤超額表現 (Alpha)、爆量比率與法人籌碼。")

with st.spinner("正在下載行情與籌碼數據計算中..."):
    all_stocks = list(set([stk for basket in DEFAULT_SECTOR_BASKETS.values() for stk in basket]))
    start_date = (datetime.today() - timedelta(days=20)).strftime("%Y-%m-%d")
    
    close_df, vol_df = get_market_price_data(all_stocks, benchmark="^TWII")
    
    # 法人籌碼批次下載
    inst_records = []
    for s in all_stocks:
        df_inst = fetch_finmind_institutional(s, start_date, finmind_token)
        if not df_inst.empty:
            inst_records.append(df_inst)
    inst_df = pd.concat(inst_records, ignore_index=True) if inst_records else pd.DataFrame()

    bench_close = close_df["^TWII"] if "^TWII" in close_df.columns else None

    sector_scores = []
    for sector_name, tickers in DEFAULT_SECTOR_BASKETS.items():
        sub_closes, sub_vols, sub_nets = [], [], []
        for t in tickers:
            tw_col = f"{t}.TW"
            if tw_col in close_df.columns:
                sub_closes.append(close_df[tw_col])
                sub_vols.append(vol_df[tw_col])
                
            if not inst_df.empty:
                s_inst = inst_df[inst_df["stock_id"] == t]
                if len(s_inst) >= 5:
                    sub_nets.append(s_inst["net_buy"].iloc[-5:].sum())
                    
        if not sub_closes:
            continue
            
        sector_idx = pd.concat(sub_closes, axis=1).mean(axis=1).dropna()
        sector_vol = pd.concat(sub_vols, axis=1).sum(axis=1).dropna()
        
        # 因子計算
        ret_5d = (sector_idx.iloc[-1] / sector_idx.iloc[-5] - 1) * 100 if len(sector_idx) >= 5 else 0
        
        bench_ret_5d = 0
        if bench_close is not None and len(bench_close) >= 5:
            bench_ret_5d = (bench_close.iloc[-1] / bench_close.iloc[-5] - 1) * 100
        relative_strength = ret_5d - bench_ret_5d
        
        vol_3d_avg = sector_vol.iloc[-3:].mean() if len(sector_vol) >= 3 else 1
        vol_10d_avg = sector_vol.iloc[-10:].mean() if len(sector_vol) >= 10 else 1
        vol_surge_ratio = vol_3d_avg / vol_10d_avg if vol_10d_avg > 0 else 1
        
        net_inst_sum = sum(sub_nets) if sub_nets else 0
        vol_factor = (vol_surge_ratio - 1.0) * 50
        
        # 綜合評分
        short_score = (relative_strength * w_relative) + (vol_factor * w_volume) + (ret_5d * w_mom)
        
        sector_scores.append({
            "族群": sector_name,
            "短線爆發評分": round(short_score, 2),
            "5日報酬(%)": round(ret_5d, 2),
            "領先大盤(%)": round(relative_strength, 2),
            "量能放大倍數": round(vol_surge_ratio, 2),
            "5日法人買超(張)": int(net_inst_sum / 1000)
        })

df_res = pd.DataFrame(sector_scores).sort_values(by="短線爆發評分", ascending=False).reset_index(drop=True)
df_res.index += 1

df_res["短線訊號"] = df_res.apply(
    lambda row: "🔥 資金攻擊（主升）" if row["短線爆發評分"] > 5 and row["量能放大倍數"] > 1.2
    else ("⚡ 轉強補漲" if row["領先大盤(%)"] > 0 and row["量能放大倍數"] > 1.0
    else "💤 整理觀望"), axis=1
)

# ----------------- UI 呈現 -----------------
# 頂部關鍵指標卡片 (前三名)
col1, col2, col3 = st.columns(3)
if len(df_res) >= 3:
    col1.metric("🥇 榜首族群", df_res.iloc[0]["族群"], f"{df_res.iloc[0]['短線爆發評分']} 分")
    col2.metric("🥈 第二名", df_res.iloc[1]["族群"], f"{df_res.iloc[1]['短線爆發評分']} 分")
    col3.metric("🥉 第三名", df_res.iloc[2]["族群"], f"{df_res.iloc[2]['短線爆發評分']} 分")

st.write("---")

# 圖表呈現：評分與量能分佈
col_chart1, col_chart2 = st.columns([6, 4])
with col_chart1:
    fig_bar = px.bar(
        df_res, 
        x="族群", 
        y="短線爆發評分", 
        color="短線訊號", 
        text="短線爆發評分",
        title="各族群爆發力綜合評分",
        color_discrete_map={
            "🔥 資金攻擊（主升）": "#ff4b4b",
            "⚡ 轉強補漲": "#ffa421",
            "💤 整理觀望": "#7f7f7f"
        }
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col_chart2:
    fig_scatter = px.scatter(
        df_res,
        x="領先大盤(%)",
        y="量能放大倍數",
        text="族群",
        size=df_res["5日報酬(%)"].apply(lambda x: max(abs(x), 2)),
        color="短線訊號",
        title="四象限分佈 (X: 超額報酬 vs Y: 爆量比率)"
    )
    fig_scatter.add_hline(y=1.0, line_dash="dash", line_color="gray")
    fig_scatter.add_vline(x=0.0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_scatter, use_container_width=True)

# 完整資料表格
st.subheader("📋 族群詳細量化評分表")
st.dataframe(
    df_res[["短線訊號", "族群", "短線爆發評分", "5日報酬(%)", "領先大盤(%)", "量能放大倍數", "5日法人買超(張)"]],
    use_container_width=True
)
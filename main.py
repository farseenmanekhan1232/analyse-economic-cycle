import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from kiteconnect import KiteConnect
import pandas_datareader.data as pdr
import os
from datetime import datetime, timedelta
import pandas.tseries.offsets as offsets
import time
import logging
from tabulate import tabulate
from colorama import init, Fore, Style
import seaborn as sns

# Initialize colorama for cross-platform colored output
init()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_access_token():
    try:
        response = requests.get("http://127.0.0.1:5000/get_token")
        if response.status_code == 200:
            return response.json()["access_token"]
        else:
            logging.error(f"Error fetching access token. Status code: {response.status_code}, Content: {response.text}")
            print(f"{Fore.RED}❌ Error fetching access token: Status {response.status_code}{Style.RESET_ALL}")
            exit(1)
    except requests.exceptions.ConnectionError:
        logging.error("Web app is not running. Please start it with 'python app.py' and visit http://localhost:5000/login.")
        print(f"{Fore.RED}❌ Web app is not running. Start it with 'python app.py' and visit http://localhost:5000/login.{Style.RESET_ALL}")
        exit(1)
    except requests.exceptions.JSONDecodeError:
        logging.error(f"Failed to parse response as JSON. Content: {response.text}")
        print(f"{Fore.RED}❌ Failed to parse response as JSON: {response.text}{Style.RESET_ALL}")
        exit(1)

# Helper function to generate date ranges within 2000-day limit
def generate_date_ranges(start_date, end_date, chunk_days=2000):
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    ranges = []
    
    while start < end:
        chunk_end = start + timedelta(days=chunk_days - 1)
        if chunk_end > end:
            chunk_end = end
        ranges.append((start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')))
        start = chunk_end + timedelta(days=1)
    
    return ranges

# Initialize Kite Connect


API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_KEY")
kite = KiteConnect(api_key=API_KEY)
access_token = get_access_token()
kite.set_access_token(access_token)

# Define sectors and their trading symbols
sectors = {
    'Bank': 'NIFTY BANK',
    'IT': 'NIFTY IT',
    'Pharma': 'NIFTY PHARMA',
    'FMCG': 'NIFTY FMCG',
    'Auto': 'NIFTY AUTO'
}

# Fetch instrument tokens for sector indices
print(f"{Fore.BLUE}=== Fetching Instrument Tokens ==={Style.RESET_ALL}")
try:
    instruments = kite.instruments("NSE")
    sector_tokens = {}
    for sector, symbol in sectors.items():
        token = next((item['instrument_token'] for item in instruments if item['tradingsymbol'] == symbol and item['segment'] == 'INDICES'), None)
        if token:
            sector_tokens[sector] = token
            print(f"{Fore.GREEN}✅ Token found for {sector} ({symbol}){Style.RESET_ALL}")
        else:
            logging.warning(f"Instrument token for {symbol} not found.")
            print(f"{Fore.RED}❌ Token not found for {symbol}{Style.RESET_ALL}")
except Exception as e:
    logging.error(f"Error fetching instruments: {e}")
    print(f"{Fore.RED}❌ Error fetching instruments: {e}{Style.RESET_ALL}")
    exit(1)

# Fetch economic data (GDP growth)
def fetch_economic_data():
    if not os.path.exists('gdp_data.csv'):
        try:
            print(f"{Fore.YELLOW}📊 Fetching GDP data from FRED...{Style.RESET_ALL}")
            gdp_data = pdr.get_data_fred('NGDPRNSAXDCINQ', start='2005-01-01', end='2025-05-27')
            if gdp_data.empty:
                logging.error("No GDP data returned from FRED.")
                print(f"{Fore.RED}❌ No GDP data returned from FRED.{Style.RESET_ALL}")
                return None
            gdp_data['growth_rate'] = gdp_data['NGDPRNSAXDCINQ'].pct_change() * 100
            gdp_data.to_csv('gdp_data.csv')
            print(f"{Fore.GREEN}✅ GDP data fetched and saved.{Style.RESET_ALL}")
        except Exception as e:
            logging.error(f"Error fetching GDP data: {e}")
            print(f"{Fore.RED}❌ Error fetching GDP data: {e}{Style.RESET_ALL}")
            return None
    return pd.read_csv('gdp_data.csv', index_col=0, parse_dates=True)

# Fetch sector data from Kite Connect
def fetch_sector_data(sector_tokens):
    sector_data = {}
    start_date = '2005-01-01'
    end_date = datetime.now().strftime('%Y-%m-%d')
    date_ranges = generate_date_ranges(start_date, end_date)
    
    for sector, token in sector_tokens.items():
        if not os.path.exists(f'{sector}_data.csv'):
            df_list = []
            print(f"{Fore.YELLOW}📊 Fetching data for {sector}...{Style.RESET_ALL}")
            for from_date, to_date in date_ranges:
                try:
                    data = kite.historical_data(token, from_date=from_date, to_date=to_date, interval='day')
                    if data:
                        df = pd.DataFrame(data)
                        df['date'] = pd.to_datetime(df['date'], utc=True).dt.tz_localize(None)
                        df.set_index('date', inplace=True)
                        df_list.append(df)
                    time.sleep(1)
                except Exception as e:
                    logging.error(f"Error fetching data for {sector} from {from_date} to {to_date}: {e}")
                    print(f"{Fore.RED}❌ Error fetching {sector} data for {from_date} to {to_date}: {e}{Style.RESET_ALL}")
            
            if df_list:
                sector_df = pd.concat(df_list)
                sector_df.to_csv(f'{sector}_data.csv')
                sector_data[sector] = sector_df
                print(f"{Fore.GREEN}✅ {sector} data fetched and saved.{Style.RESET_ALL}")
            else:
                logging.warning(f"No data fetched for {sector}.")
                print(f"{Fore.RED}❌ No data fetched for {sector}.{Style.RESET_ALL}")
        else:
            df = pd.read_csv(f'{sector}_data.csv', index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index).tz_localize(None)
            sector_data[sector] = df
            print(f"{Fore.GREEN}✅ Loaded cached data for {sector}.{Style.RESET_ALL}")
    
    return sector_data

# Identify economic phases
def identify_phases(gdp_data):
    gdp_data['phase'] = 'expansion'
    for i in range(1, len(gdp_data)):
        if pd.notna(gdp_data.iloc[i-1]['growth_rate']) and pd.notna(gdp_data.iloc[i]['growth_rate']):
            if gdp_data.iloc[i-1]['growth_rate'] < 0 and gdp_data.iloc[i]['growth_rate'] < 0:
                gdp_data.iloc[i, gdp_data.columns.get_loc('phase')] = 'recession'
    return gdp_data

# Calculate quarterly returns
def calculate_quarterly_returns(sector_data):
    quarterly_returns = {}
    for sector, df in sector_data.items():
        try:
            df = df.copy()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            quarterly_data = df.resample('QE').last()['close']  # Fixed FutureWarning
            returns = quarterly_data.pct_change().dropna()
            quarterly_returns[sector] = returns
            logging.info(f"Quarterly returns for {sector}: {returns.head().to_dict()}")
        except Exception as e:
            logging.error(f"Error calculating returns for {sector}: {e}")
            print(f"{Fore.RED}❌ Error calculating returns for {sector}: {e}{Style.RESET_ALL}")
    return quarterly_returns

# Analyze performance by phase
def analyze_performance(quarterly_returns, gdp_data):
    performance = {}
    for sector, returns in quarterly_returns.items():
        try:
            gdp_data.index = pd.to_datetime(gdp_data.index).to_period('Q').to_timestamp('Q')
            merged = pd.merge(
                returns.to_frame('returns'),
                gdp_data['phase'],
                left_index=True,
                right_index=True,
                how='left'
            )
            if merged.empty:
                logging.warning(f"No overlapping data for {sector}. Check date ranges.")
                performance[sector] = pd.Series(dtype=float)
            else:
                avg_returns = merged.groupby('phase')['returns'].mean()
                performance[sector] = avg_returns
                logging.info(f"Average returns for {sector}: {avg_returns.to_dict()}")
        except Exception as e:
            logging.error(f"Error analyzing performance for {sector}: {e}")
            print(f"{Fore.RED}❌ Error analyzing performance for {sector}: {e}{Style.RESET_ALL}")
    return performance

# Visualize data with interactive charts
def visualize_data(sector_data, gdp_data, performance, sector_returns_df):
    # Enable interactive mode
    plt.ion()

    # Chart 1: Sector Indices with Recession Periods
    fig1, ax1 = plt.subplots(figsize=(12, 6))
    for sector, df in sector_data.items():
        ax1.plot(df.index, df['close'], label=sector)
    recession_periods = pd.to_datetime(gdp_data[gdp_data['phase'] == 'recession'].index)
    for period in recession_periods:
        ax1.axvspan(period, period + offsets.QuarterEnd(0), color='gray', alpha=0.3)
    ax1.set_title('Sector Indices with Recession Periods')
    ax1.legend()
    plt.show()

    # Chart 2: Average Quarterly Returns by Sector and Phase
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    phases = ['expansion', 'recession']
    bar_width = 0.15
    x = np.arange(len(phases))
    for i, (sector, avg_returns) in enumerate(performance.items()):
        ax2.bar(x + i * bar_width, [avg_returns.get(phase, 0) for phase in phases], 
                bar_width, label=sector)
    ax2.set_xticks(x + bar_width * (len(performance) - 1) / 2)
    ax2.set_xticklabels(phases)
    ax2.set_title('Average Quarterly Returns by Sector and Phase')
    ax2.set_ylabel('Returns')
    ax2.legend()
    plt.show()

    # Chart 3: GDP Growth Rate Over Time
    fig3, ax3 = plt.subplots(figsize=(10, 6))
    ax3.plot(gdp_data.index, gdp_data['growth_rate'], color='blue')
    ax3.set_title('GDP Growth Rate Over Time')
    ax3.set_xlabel('Date')
    ax3.set_ylabel('Growth Rate (%)')
    plt.show()

    # Chart 4: Sector Correlation Heatmap
    fig4, ax4 = plt.subplots(figsize=(8, 6))
    correlation_matrix = sector_returns_df.corr()
    sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', ax=ax4)
    ax4.set_title('Sector Returns Correlation Heatmap')
    plt.show()

    print(f"{Fore.GREEN}✅ All charts displayed in separate windows. Close them to continue.{Style.RESET_ALL}")

# Make investment recommendations
def make_recommendations(performance, sector_data, gdp_data, sector_returns_df):
    try:
        latest_gdp = gdp_data['growth_rate'].iloc[-2:]
        current_phase = 'recession' if all(latest_gdp < 0) else 'expansion'
        recent_returns = {}
        for sector, df in sector_data.items():
            try:
                returns = df['close'].pct_change(periods=90).iloc[-1]
                recent_returns[sector] = returns if not pd.isna(returns) else 0
                logging.info(f"Recent 90-day return for {sector}: {returns}")
            except Exception as e:
                logging.error(f"Error calculating recent returns for {sector}: {e}")
                recent_returns[sector] = 0

        recommendations = []
        table_data = []
        for sector, avg_returns in performance.items():
            avg_return_exp = avg_returns.get('expansion', 0)
            avg_return_rec = avg_returns.get('recession', 0)
            recent_return = recent_returns.get(sector, 0)
            if avg_return_exp >= 0 and recent_return > 0:
                recommendations.append(sector)
            table_data.append([sector, f"{avg_return_exp:.4f}", f"{avg_return_rec:.4f}", f"{recent_return:.4f}"])
            logging.info(f"{sector} - Avg return in expansion: {avg_return_exp}, recession: {avg_return_rec}, Recent return: {recent_return}")
        
        print(f"\n{Fore.BLUE}=== Sector Performance Summary ==={Style.RESET_ALL}")
        print(tabulate(
            table_data,
            headers=["Sector", "Avg Return (Expansion)", "Avg Return (Recession)", "Recent 90-Day Return"],
            tablefmt="fancy_grid",
            floatfmt=".4f"
        ))
        print(f"\n{Fore.BLUE}=== Current Investment Recommendations ==={Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Economic Phase: {current_phase.capitalize()}{Style.RESET_ALL}")
        if recommendations:
            print(f"Recommended sectors: {', '.join(recommendations)}")
        else:
            print(f"{Fore.YELLOW}No sectors meet the criteria for recommendation.{Style.RESET_ALL}")
        return current_phase, recommendations
    except Exception as e:
        logging.error(f"Error making recommendations: {e}")
        print(f"{Fore.RED}❌ Error making recommendations: {e}{Style.RESET_ALL}")
        return None, []

# Predict sectors likely to grow and fetch top mutual funds
def predict_sectors_and_mfs():
    top_sectors = {
        "IT": [
            "Tata Digital India Regular Growth Fund",
            "ICICI Prudential Technology Regular Growth Fund",
            "SBI Technology Opportunities Regular Growth Fund"
        ],
        "Healthcare": [
            "SBI Healthcare Opportunities Fund Direct Plan - Growth",
            "ICICI Prudential Pharma Healthcare and Diagnostics (P.H.D) Fund Direct - Growth",
            "DSP Healthcare Fund Direct - Growth"
        ],
        "Infrastructure": [
            "HDFC Infrastructure Fund",
            "Nippon India Power & Infra Fund",
            "Bank of India Manufacturing & Infrastructure Fund"
        ],
        "Renewable Energy": [
            "DSP Natural Resources and New Energy Fund",
            "SBI Energy Opportunities Fund",
            "ICICI Prudential Energy Opportunities Fund"
        ]
    }
    table_data = []
    for sector, funds in top_sectors.items():
        for fund in funds:
            table_data.append([sector, fund])
    
    print(f"\n{Fore.BLUE}=== Predicted Sectors for 2025 and Top Mutual Funds ==={Style.RESET_ALL}")
    print(tabulate(
        table_data,
        headers=["Sector", "Mutual Fund"],
        tablefmt="fancy_grid",
        stralign="left"
    ))
    return top_sectors

# Main execution
print(f"{Fore.BLUE}=== Economic Cycle Analysis ==={Style.RESET_ALL}")
print(f"Today's date and time: {datetime.now().strftime('%I:%M %p IST, %A, %B %d, %Y')}")
logging.info("Starting script execution")

print(f"\n{Fore.BLUE}=== Fetching Economic Data ==={Style.RESET_ALL}")
gdp_data = fetch_economic_data()
if gdp_data is None or gdp_data.empty:
    logging.error("Failed to fetch GDP data. Exiting.")
    print(f"{Fore.RED}❌ Failed to fetch GDP data. Exiting.{Style.RESET_ALL}")
    exit(1)

print(f"\n{Fore.BLUE}=== Fetching Sector Data ==={Style.RESET_ALL}")
sector_data = fetch_sector_data(sector_tokens)
if not sector_data:
    logging.error("No sector data fetched. Exiting.")
    print(f"{Fore.RED}❌ No sector data fetched. Exiting.{Style.RESET_ALL}")
    exit(1)

print(f"\n{Fore.BLUE}=== Identifying Economic Phases ==={Style.RESET_ALL}")
gdp_data = identify_phases(gdp_data)
print(f"{Fore.GREEN}✅ Economic phases identified.{Style.RESET_ALL}")

print(f"\n{Fore.BLUE}=== Calculating Quarterly Returns ==={Style.RESET_ALL}")
quarterly_returns = calculate_quarterly_returns(sector_data)
if not quarterly_returns:
    logging.error("No quarterly returns calculated. Exiting.")
    print(f"{Fore.RED}❌ No quarterly returns calculated. Exiting.{Style.RESET_ALL}")
    exit(1)

print(f"\n{Fore.BLUE}=== Analyzing Performance ==={Style.RESET_ALL}")
performance = analyze_performance(quarterly_returns, gdp_data)
if not performance:
    logging.error("No performance data analyzed. Exiting.")
    print(f"{Fore.RED}❌ No performance data analyzed. Exiting.{Style.RESET_ALL}")
    exit(1)

# Prepare sector returns DataFrame for correlation heatmap
sector_returns_df = pd.DataFrame({sector: data['close'].pct_change() for sector, data in sector_data.items()}).dropna()

print(f"\n{Fore.BLUE}=== Generating Visualizations ==={Style.RESET_ALL}")
visualize_data(sector_data, gdp_data, performance, sector_returns_df)

print(f"\n{Fore.BLUE}=== Generating Investment Recommendations ==={Style.RESET_ALL}")
current_phase, recommendations = make_recommendations(performance, sector_data, gdp_data, sector_returns_df)

predict_sectors_and_mfs()
logging.info(f"Script completed. Phase: {current_phase}, Recommendations: {recommendations}")
print(f"\n{Fore.BLUE}=== Analysis Complete ==={Style.RESET_ALL}")
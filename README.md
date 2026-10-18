# Pulse Decision OS

Personal decision loop: versioned analysis runs → diff vs open holdings → Groww checklist → sync truth back.

| Screen | URL |
|--------|-----|
| Today | http://localhost:3000/ |
| Portfolio | http://localhost:3000/holdings |
| Research | http://localhost:3000/swing |
| Data | http://localhost:3000/sync |

```bash
./dev.sh          # API :8000 + UI :3000 together (Ctrl+C stops both)

# or separately:
uvicorn backend.api.server:app --reload --host 127.0.0.1 --port 8000
cd apps/web && npm run dev
```

DB: `data/pulse_decision.db` (Alembic: `alembic upgrade head`). Legacy Jinja cycle lab: `/legacy`. Old Vite SIP/satellite/review UI redirects here.

---

# Indian Stock Market Economic Cycle Analysis (engines)

**Python cycle brain: Kite sector indices, regime/sector scores, fund heuristics — consumed by Decision OS.**

---

## 📋 Project Overview

This project is a command-line application designed to analyze economic cycles in the Indian stock market, recommend sectors for investment based on historical and recent performance, predict sectors likely to grow in the near future, and suggest top mutual funds for those sectors. It leverages the **Kite Connect API** for sector index data, **FRED** for GDP data, and external financial analyses for sector predictions and mutual fund recommendations.

The script provides:

- **Economic Cycle Analysis**: Identifies expansion and recession phases using GDP growth rates.
- **Sector Performance**: Analyzes returns for key sectors (Bank, IT, Pharma, FMCG, Auto) across economic phases.
- **Investment Recommendations**: Suggests sectors based on average returns and recent 90-day performance.
- **Future Growth Predictions**: Highlights sectors expected to grow in 2025 (e.g., IT, Healthcare).
- **Mutual Fund Suggestions**: Recommends top mutual funds for predicted growth sectors.
- **Interactive Visualizations**: Displays charts in separate windows for sector indices, returns, GDP growth, and correlations.

The output is enhanced with **colored CLI messages**, **pretty tables** using `tabulate`, and **interactive charts** using `matplotlib`, making it user-friendly and visually appealing.

---

## ✨ Features

- **Data Fetching**:
  - Retrieves historical sector index data from the Kite Connect API.
  - Fetches quarterly GDP data from FRED (`NGDPRNSAXDCINQ`) and calculates growth rates.
- **Economic Cycle Detection**:
  - Labels quarters as "expansion" or "recession" based on two consecutive quarters of negative GDP growth.
- **Sector Analysis**:
  - Calculates quarterly returns for Nifty indices (Bank, IT, Pharma, FMCG, Auto).
  - Computes average returns during expansion and recession phases.
- **Investment Recommendations**:
  - Recommends sectors with non-negative average returns in the current phase and positive recent 90-day returns.
- **Future Growth Predictions**:
  - Predicts high-growth sectors for 2025 (IT, Healthcare, Infrastructure, Renewable Energy) based on market analyses.
- **Mutual Fund Suggestions**:
  - Lists top mutual funds for predicted sectors, sourced from financial websites like ET Money and Groww.
- **Visualizations**:
  - **Sector Indices with Recession Periods**: Line chart showing sector performance with recession shading.
  - **Average Quarterly Returns**: Bar chart comparing returns by sector and phase.
  - **GDP Growth Rate**: Line chart of economic growth trends.
  - **Sector Correlation Heatmap**: Heatmap of correlations between sector returns.
- **CLI Enhancements**:
  - Colored output using `colorama` (green for success, red for errors, blue for headers).
  - Pretty tables using `tabulate` for recommendations, performance summaries, and mutual funds.
  - Clear section separators and progress indicators.

---

## 🛠️ Installation

### Prerequisites

- **Python 3.7+**
- **Kite Connect API Account**: Obtain API key and secret from [Zerodha Kite Connect](https://kite.trade/).
- **FRED API Access**: No key required, but ensure internet access for FRED data.

### Dependencies

Install the required Python libraries using pip:

```bash
pip install requests pandas numpy matplotlib kiteconnect pandas_datareader tabulate colorama seaborn
```

### Project Structure

```
analyse-economic-cycle/
├── main.py               # Main script for analysis and recommendations
├── app.py                # Flask web app for Kite Connect authentication
├── gdp_data.csv          # Cached GDP data (generated)
├── <sector>_data.csv     # Cached sector data (e.g., Bank_data.csv)
├── sector_indices.png    # Sector indices chart (generated)
├── avg_returns.png       # Average returns chart (generated)
└── README.md             # Project documentation
```

---

## 🚀 Setup

1. **Clone the Repository** (if applicable):

   ```bash
   git clone <repository-url>
   cd analyse-economic-cycle
   ```

2. **Configure Kite Connect**:

   - Update `API_KEY` and `API_SECRET` in `.env`

3. **Run the Web App**:

   - The web app (`app.py`) handles Kite Connect authentication to generate an access token.
   - Start it:
     ```bash
     python app.py
     ```
   - Open `http://localhost:5000/login` in your browser, log in with your Zerodha credentials, and authorize the app.

4. **Prepare the Environment**:
   - Ensure all dependencies are installed.
   - Verify internet connectivity for API calls.

---

## 📈 Usage

1. **Start the Web App**:

   - Run `app.py` to provide the access token:
     ```bash
     python app.py
     ```

2. **Run the Main Script**:

   - Execute `main.py`:
     ```bash
     python main.py
     ```
   - The script will:
     - Fetch GDP and sector data.
     - Identify economic phases.
     - Calculate and analyze sector returns.
     - Display four interactive charts in separate windows (close each to proceed).
     - Print a performance summary table, investment recommendations, and predicted sectors with mutual funds.

3. **Interact with Output**:
   - **Charts**: View and close each chart window to continue.
   - **Console**: Review colored output, tables, and logs for detailed insights.
   - **Files**: Check generated CSVs and PNGs in the project directory.

---

## 📊 Example Output

### Console Output

```
=== Economic Cycle Analysis ===
Today's date and time: 02:15 PM IST, Tuesday, May 27, 2025

=== Fetching Economic Data ===
📊 Fetching GDP data from FRED...
✅ GDP data fetched and saved.

=== Fetching Sector Data ===
✅ Token found for Bank (NIFTY BANK)
✅ Token found for IT (NIFTY IT)
...
📊 Fetching data for Bank...
✅ Bank data fetched and saved.
...

=== Identifying Economic Phases ===
✅ Economic phases identified.

=== Calculating Quarterly Returns ===
✅ Quarterly returns calculated.

=== Analyzing Performance ===
✅ Performance analyzed.

=== Generating Visualizations ===
✅ All charts displayed in separate windows. Close them to continue.

=== Sector Performance Summary ===
╒══════════╤═════════════════════════╤═════════════════════════╤════════════════════════╕
│ Sector   │ Avg Return (Expansion)  │ Avg Return (Recession)  │ Recent 90-Day Return   │
╞══════════╪═════════════════════════╪═════════════════════════╪════════════════════════╡
│ Bank     │ 0.0150                  │ -0.0100                 │ 0.1519                 │
│ IT       │ 0.0200                  │ 0.0050                  │ -0.1483                │
│ Pharma   │ 0.0000                  │ -0.0020                 │ -0.0170                │
│ FMCG     │ 0.0100                  │ 0.0030                  │ 0.0007                 │
│ Auto     │ 0.0050                  │ -0.0150                 │ 0.0535                 │
╘══════════╧═════════════════════════╧═════════════════════════╧════════════════════════╛

=== Current Investment Recommendations ===
Economic Phase: Expansion
Recommended sectors: Bank, FMCG, Auto

=== Predicted Sectors for 2025 and Top Mutual Funds ===
╒═══════════════════╤═══════════════════════════════════════════════════════════════════╕
│ Sector            │ Mutual Fund                                                       │
╞═══════════════════╪═══════════════════════════════════════════════════════════════════╡
│ IT                │ Tata Digital India Regular Growth Fund                            │
│ IT                │ ICICI Prudential Technology Regular Growth Fund                   │
│ IT                │ SBI Technology Opportunities Regular Growth Fund                  │
│ Healthcare        │ SBI Healthcare Opportunities Fund Direct Plan - Growth             │
...
╘═══════════════════╧═══════════════════════════════════════════════════════════════════╛

=== Analysis Complete ===
```

### Generated Files

- **Data**:
  - `gdp_data.csv`: GDP data with growth rates.
  - `<sector>_data.csv`: Sector index data (e.g., `Bank_data.csv`).
- **Charts**:
  - `sector_indices.png`: Sector indices with recession shading.
  - `avg_returns.png`: Average returns by phase.

---

## 🔍 How It Works

1. **Authentication**:

   - The Flask web app (`app.py`) handles Kite Connect OAuth, generating an access token.
   - `main.py` fetches this token via `http://127.0.0.1:5000/get_token`.

2. **Data Fetching**:

   - **GDP Data**: Fetched from FRED using `pandas_datareader`, with growth rates calculated.
   - **Sector Data**: Fetched from Kite Connect in 2000-day chunks to comply with API limits.

3. **Analysis**:

   - **Economic Phases**: Identified using GDP growth (two negative quarters = recession).
   - **Returns**: Quarterly returns calculated via resampling, merged with phase data.
   - **Performance**: Average returns computed for each sector per phase.

4. **Visualizations**:

   - Four charts displayed in separate windows using `matplotlib`’s interactive mode.
   - Saved as PNGs for reference.

5. **Recommendations**:

   - Sectors recommended based on non-negative average returns in the current phase and positive recent returns.
   - Predicted sectors and mutual funds listed based on external analyses.

6. **CLI Output**:
   - Enhanced with colors (`colorama`), tables (`tabulate`), and emojis for readability.

---

## 📝 Notes

- **Kite Connect Limitations**: The API doesn’t provide historical NAV or sector-specific performance for mutual funds, so predictions rely on static data from financial websites.
- **Data Availability**: GDP data may not extend to May 2025; the script fetches the latest available data.
- **Interactivity**: Close each chart window to proceed with the script execution.
- **Customization**: Adjust table formats, chart styles, or recommendation criteria in the script.

---

## 🐛 Troubleshooting

- **Web App Not Running**:
  - Ensure `app.py` is running and you’ve authenticated at `http://localhost:5000/login`.
- **Data Fetch Errors**:
  - Check your Kite Connect API key and secret.
  - Verify internet connectivity for FRED and Kite Connect APIs.
- **Empty Recommendations**:
  - Inspect logs for average and recent returns.
  - Adjust criteria in `make_recommendations` if needed (e.g., `avg_return > -0.01`).
- **Chart Windows Not Opening**:
  - Ensure `matplotlib` is configured for an interactive backend (e.g., TkAgg).
  - Run `matplotlib.get_backend()` to check; switch with `matplotlib.use('TkAgg')` if needed.

---

## 🌟 Future Enhancements

- **Dynamic Mutual Fund Data**: Integrate MFAPI.in for real-time NAV and performance metrics.
- **Advanced Predictions**: Use machine learning for sector growth forecasting.
- **Interactive CLI**: Add `argparse` for user-defined sectors or metrics.
- **Web Interface**: Convert to a web app with Flask or Django for browser-based access.
- **Export Reports**: Save tables and charts as a PDF report.

---

## 📚 References

- [Kite Connect API Documentation](https://kite.trade/docs/connect/v3/)
- [FRED API](https://fred.stlouisfed.org/docs/api/fred/)
- [Groww: Current Market Conditions](https://groww.in/blog/current-market-condition-sectors-future)
- [ET Money: Sectoral Funds](https://www.etmoney.com/mutual-funds/equity/sectoral-technology/43)
- [Grip Invest: Fastest Growing Sectors](https://www.gripinvest.in/blog/fastest-growing-sectors-in-India)
- [Economic Times: Bullish Sectors](https://economictimes.indiatimes.com/wealth/invest/experts-bullish-on-6-sectors-for-good-returns-amid-stock-market-volatility/articleshow/117126586.cms)

---

## 👥 Contributors

- **Farseen** - Project initiator and primary developer.
- **Grok** - Assisted with code development, debugging, and documentation.

---

## ⚖️ License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

**Happy Investing! 🚀**

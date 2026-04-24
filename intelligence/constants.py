"""
CryptoStream AI — Market Constants
Centralized registry for Macro assets, NASDAQ 100 constituents, and S&P 500.
"""
NASDAQ_100_TICKERS = ['NVDA', 'GOOGL', 'GOOG', 'AAPL', 'MSFT', 'AMZN', 'AVGO', 'META', 'TSLA', 'WMT', 'ASML', 'COST', 'NFLX', 'AMD', 'LRCX', 'MU', 'CSCO', 'AMAT', 'INTC', 'PLTR', 'LIN', 'KLAC', 'TMUS', 'PEP', 'TXN', 'AMGN', 'GILD', 'ADI', 'ISRG', 'ARM', 'HON', 'SHOP', 'PDD', 'BKNG', 'QCOM', 'APP', 'PANW', 'WDC', 'STX', 'MRVL', 'VRTX', 'SBUX', 'CEG', 'CMCSA', 'INTU', 'CRWD', 'MAR', 'ADBE', 'MELI', 'CSX', 'ORLY', 'ABNB', 'REGN', 'ADP', 'MDLZ', 'SNPS', 'MNST', 'AEP', 'CDNS', 'ROST', 'CTAS', 'WBD', 'PCAR', 'MPWR', 'DASH', 'BKR', 'FTNT', 'FAST', 'FANG', 'NXPI', 'FER', 'XEL', 'EA', 'EXC', 'ADSK', 'IDXX', 'MSTR', 'CCEP', 'ODFL', 'ALNY', 'PYPL', 'MCHP', 'DDOG', 'TRI', 'TTWO', 'KDP', 'ROP', 'INSM', 'GEHC', 'CPRT', 'CHTR', 'PAYX', 'WDAY', 'AXON', 'CTSH', 'KHC', 'DXCM', 'VRSK', 'ZS', 'CSGP', 'TEAM']

SP500_TICKERS = ['MMM', 'AOS', 'ABT', 'ABBV', 'ACN', 'ADBE', 'AMD', 'AES', 'AFL', 'A', 'APD', 'ABNB', 'AKAM', 'ALB', 'ARE', 'ALGN', 'ALLE', 'LNT', 'ALL', 'GOOGL', 'GOOG', 'MO', 'AMZN', 'AMCR', 'AEE', 'AEP', 'AXP', 'AIG', 'AMT', 'AWK', 'AMP', 'AME', 'AMGN', 'APH', 'ADI', 'AON', 'APA', 'APO', 'AAPL', 'AMAT', 'APP', 'APTV', 'ACGL', 'ADM', 'ARES', 'ANET', 'AJG', 'AIZ', 'T', 'ATO', 'ADSK', 'ADP', 'AZO', 'AVB', 'AVY', 'AXON', 'BKR', 'BALL', 'BAC', 'BAX', 'BDX', 'BRK.B', 'BBY', 'TECH', 'BIIB', 'BLK', 'BX', 'XYZ', 'BK', 'BA', 'BKNG', 'BSX', 'BMY', 'AVGO', 'BR', 'BRO', 'BF.B', 'BLDR', 'BG', 'BXP', 'CHRW', 'CDNS', 'CPT', 'CPB', 'COF', 'CAH', 'CCL', 'CARR', 'CVNA', 'CASY', 'CAT', 'CBOE', 'CBRE', 'CDW', 'COR', 'CNC', 'CNP', 'CF', 'CRL', 'SCHW', 'CHTR', 'CVX', 'CMG', 'CB', 'CHD', 'CIEN', 'CI', 'CINF', 'CTAS', 'CSCO', 'C', 'CFG', 'CLX', 'CME', 'CMS', 'KO', 'CTSH', 'COHR', 'COIN', 'CL', 'CMCSA', 'FIX', 'CAG', 'COP', 'ED', 'STZ', 'CEG', 'COO', 'CPRT', 'GLW', 'CPAY', 'CTVA', 'CSGP', 'COST', 'CTRA', 'CRH', 'CRWD', 'CCI', 'CSX', 'CMI', 'CVS', 'DHR', 'DRI', 'DDOG', 'DVA', 'DECK', 'DE', 'DELL', 'DAL', 'DVN', 'DXCM', 'FANG', 'DLR', 'DG', 'DLTR', 'D', 'DPZ', 'DASH', 'DOV', 'DOW', 'DHI', 'DTE', 'DUK', 'DD', 'ETN', 'EBAY', 'SATS', 'ECL', 'EIX', 'EW', 'EA', 'ELV', 'EME', 'EMR', 'ETR', 'EOG', 'EPAM', 'EQT', 'EFX', 'EQIX', 'EQR', 'ERIE', 'ESS', 'EL', 'EG', 'EVRG', 'ES', 'EXC', 'EXE', 'EXPE', 'EXPD', 'EXR', 'XOM', 'FFIV', 'FDS', 'FICO', 'FAST', 'FRT', 'FDX', 'FIS', 'FITB', 'FSLR', 'FE', 'FISV', 'F', 'FTNT', 'FTV', 'FOXA', 'FOX', 'BEN', 'FCX', 'GRMN', 'IT', 'GE', 'GEHC', 'GEV', 'GEN', 'GNRC', 'GD', 'GIS', 'GM', 'GPC', 'GILD', 'GPN', 'GL', 'GDDY', 'GS', 'HAL', 'HIG', 'HAS', 'HCA', 'DOC', 'HSIC', 'HSY', 'HPE', 'HLT', 'HD', 'HON', 'HRL', 'HST', 'HWM', 'HPQ', 'HUBB', 'HUM', 'HBAN', 'HII', 'IBM', 'IEX', 'IDXX', 'ITW', 'INCY', 'IR', 'PODD', 'INTC', 'IBKR', 'ICE', 'IFF', 'IP', 'INTU', 'ISRG', 'IVZ', 'INVH', 'IQV', 'IRM', 'JBHT', 'JBL', 'JKHY', 'J', 'JNJ', 'JCI', 'JPM', 'KVUE', 'KDP', 'KEY', 'KEYS', 'KMB', 'KIM', 'KMI', 'KKR', 'KLAC', 'KHC', 'KR', 'LHX', 'LH', 'LRCX', 'LVS', 'LDOS', 'LEN', 'LII', 'LLY', 'LIN', 'LYV', 'LMT', 'L', 'LOW', 'LULU', 'LITE', 'LYB', 'MTB', 'MPC', 'MAR', 'MRSH', 'MLM', 'MAS', 'MA', 'MKC', 'MCD', 'MCK', 'MDT', 'MRK', 'META', 'MET', 'MTD', 'MGM', 'MCHP', 'MU', 'MSFT', 'MAA', 'MRNA', 'TAP', 'MDLZ', 'MPWR', 'MNST', 'MCO', 'MS', 'MOS', 'MSI', 'MSCI', 'NDAQ', 'NTAP', 'NFLX', 'NEM', 'NWSA', 'NWS', 'NEE', 'NKE', 'NI', 'NDSN', 'NSC', 'NTRS', 'NOC', 'NCLH', 'NRG', 'NUE', 'NVDA', 'NVR', 'NXPI', 'ORLY', 'OXY', 'ODFL', 'OMC', 'ON', 'OKE', 'ORCL', 'OTIS', 'PCAR', 'PKG', 'PLTR', 'PANW', 'PSKY', 'PH', 'PAYX', 'PYPL', 'PNR', 'PEP', 'PFE', 'PCG', 'PM', 'PSX', 'PNW', 'PNC', 'POOL', 'PPG', 'PPL', 'PFG', 'PG', 'PGR', 'PLD', 'PRU', 'PEG', 'PTC', 'PSA', 'PHM', 'PWR', 'QCOM', 'DGX', 'Q', 'RL', 'RJF', 'RTX', 'O', 'REG', 'REGN', 'RF', 'RSG', 'RMD', 'RVTY', 'HOOD', 'ROK', 'ROL', 'ROP', 'ROST', 'RCL', 'SPGI', 'CRM', 'SNDK', 'SBAC', 'SLB', 'STX', 'SRE', 'NOW', 'SHW', 'SPG', 'SWKS', 'SJM', 'SW', 'SNA', 'SOLV', 'SO', 'LUV', 'SWK', 'SBUX', 'STT', 'STLD', 'STE', 'SYK', 'SMCI', 'SYF', 'SNPS', 'SYY', 'TMUS', 'TROW', 'TTWO', 'TPR', 'TRGP', 'TGT', 'TEL', 'TDY', 'TER', 'TSLA', 'TXN', 'TPL', 'TXT', 'TMO', 'TJX', 'TKO', 'TTD', 'TSCO', 'TT', 'TDG', 'TRV', 'TRMB', 'TFC', 'TYL', 'TSN', 'USB', 'UBER', 'UDR', 'ULTA', 'UNP', 'UAL', 'UPS', 'URI', 'UNH', 'UHS', 'VLO', 'VTR', 'VLTO', 'VRSN', 'VRSK', 'VZ', 'VRTX', 'VRT', 'VTRS', 'VICI', 'V', 'VST', 'VMC', 'WRB', 'GWW', 'WAB', 'WMT', 'DIS', 'WBD', 'WM', 'WAT', 'WEC', 'WFC', 'WELL', 'WST', 'WDC', 'WY', 'WSM', 'WMB', 'WTW', 'WDAY', 'WYNN', 'XEL', 'XYL', 'YUM', 'ZBRA', 'ZBH', 'ZTS']

# Popular small/mid-cap stocks not in NASDAQ100 or S&P500
SMALL_CAP_TICKERS = [
    # Clean Energy / EV
    'EOSE','PLUG','FCEL','BLNK','CHPT','RIVN','LCID','FSR','GOEV','SOLO',
    'NKLA','WKHS','RIDE','HYLN','REE','ARVL','ZEV','IDEX','CLSK','MARA',
    'WPRT','HYZN','KNDI','AYRO','XPEV','LI','NIO','FFIE','MULN','EVGO',
    # Space / Defense Tech
    'RKLB','ASTR','SPCE','MNTS','ASTS','BKSY','SATL','PL','KTOS','AJRD',
    'LUNR','ACHR','JOBY','LILM','ARCHER','EVTOL','RDW','VORB','NKLA','HOL',
    # Biotech / Pharma Small
    'SAVA','PRAX','ARQT','RXRX','SEER','BEAM','EDIT','NTLA','CRSP','PACB',
    'VERV','GRPH','BLUE','FATE','AGEN','SRPT','RCKT','TARS','AKRO','KYMR',
    'IMVT','NUVL','RVNC','ACAD','SAGE','ANNX','AGIO','ARWR','PRLD','BOLD',
    'REPL','YMAB','TWST','FLXN','XNCR','IMGO','TGTX','ALDX','CGEM','HRMY',
    # Fintech / Crypto
    'HOOD','SOFI','OPFI','DAVE','MQ','UPST','AFRM','LC','LPRO','OPEN',
    'FLYW','TREE','EZCORP','CURO','OMF','PRAA','WRLD','ENVA','QFIN',
    'COIN','MSTR','RIOT','MARA','HUT','BITF','CLSK','CIFR','BTBT','WULF',
    'IREN','CORZ','DMGI','BTDR','SATO',
    # AI / Semiconductor Small
    'IONQ','QUBT','RGTI','QMCO','ARQQ','DFNS','BBAI','GFAI','SOUN','AITX',
    'ZVRA','MIND','AIXI','ONDS','GENI','RBOT','VERB','VIAV','SMTC','WOLF',
    'AIOT','BSFC','INPX','SSYS','DDD','XONE','MKFG','NNDM','VELO','LAZR',
    # Meme / Retail Favorites
    'GME','AMC','BBBY','BB','NOK','EXPR','KOSS','CLOV','WISH','SKLZ',
    'ATER','SPRT','SDC','BGFV','PRTY','NKLA','TTCF','HYZN','TLRY','SNDL',
    # Gaming / Esports / Metaverse
    'DKNG','PENN','GNOG','RSI','MGAM','GMBL','GAMETK','AGAE','GLNG','NCBJ',
    'RBLX','U','MTTR','MVIS','HOLO','MAPS','VR','IMMR','NERD','ESPO',
    # Cannabis
    'TLRY','SNDL','CGC','ACB','CRON','OGI','APHA','CURLF','CCHWF','GTBIF',
    'TCNNF','VRSSF','GRWG','IIPR','KERN',
    # Shipping / Freight
    'ZIM','DAC','SBLK','GOGL','EGLE','GNK','TOPS','FREE','SHIP','CTRM',
    'GLBS','EDRY','GASS','STNG','TNK',
    # Mining / Resources / Uranium
    'MP','LTBR','UEC','NXE','DNN','URG','UUUU','HURA','BWXT','CCJ',
    'SWN','RRC','CNX','AR','CDEV','SM','NOG','MTDR','BATL','VTLE',
    # REITs / Finance Small
    'PSEC','MAIN','GAIN','GLAD','SLRC','TPVG','FDUS','TCPC','CGBD','GSBD',
    # Social Media / Media Small
    'SNAP','PINS','BMBL','MTCH','ANGI','YELP','IAC','ZG','OPEN','RDFN',
    # Health / Medtech Small
    'TELA','NVCR','AXNX','NVRO','PROS','INVA','ATRC','SWAV','INSP','MASI',
    # SPACs / Special Situations
    'PSTH','AJAX','RLAY','GNPX','BRPM','COVA','DUNE','FTIV',
]

# Popular ETFs (broad market, sector, thematic, leveraged)
ETF_TICKERS = [
    # Broad Market
    'SPY','IVV','VOO','VTI','QQQ','IWM','DIA','RSP','SCHB','ITOT',
    'VEA','EFA','VWO','EEM','IEMG','VT','ACWI','URTH',
    # Sector ETFs
    'XLK','XLF','XLV','XLE','XLI','XLY','XLP','XLB','XLU','XLRE','XLC',
    'VGT','VFH','VHT','VDE','VIS','VCR','VDC','VAW','VPU','VOX',
    'SOXX','SMH','HACK','IGV','CIBR','SKYY','CLOU','WCLD',
    'ARKK','ARKG','ARKW','ARKF','ARKQ','ARKX',
    # Thematic
    'BOTZ','ROBO','IRBO','AIQ','THNQ','DTEC',
    'ICLN','TAN','FAN','QCLN','ACES','CNRG',
    'LIT','BATT','DRIV','KARS','IDRV',
    'MOON','UFO','ROKT','SRET',
    # Fixed Income
    'AGG','BND','TLT','IEF','SHY','HYG','LQD','JNK','VCIT','BNDX',
    # Commodities
    'GLD','IAU','SLV','USO','UNG','DBA','PDBC','COMT','FTGC',
    'GDX','GDXJ','SIL','XME','COPX','URA',
    # Leveraged / Inverse
    'TQQQ','SQQQ','SPXL','SPXS','UPRO','SPXU','SOXL','SOXS',
    'LABU','LABD','FNGU','FNGD','BULZ','BERZ',
    'UVXY','SVXY','VXX','VIXY',
    # International
    'EWJ','EWZ','EWC','EWA','EWU','EWG','EWY','EWT','MCHI','KWEB',
    'FXI','ASHR','CQQQ','EWH','EWS','EWW','EWP','EWQ','EWI','EWN',
    # Dividend
    'SCHD','VYM','DVY','HDV','DGRO','NOBL','SDY','VIG','DGRW',
]

# Popular ADRs — foreign stocks listed on US exchanges
ADR_TICKERS = [
    # China Tech
    'BABA','BIDU','JD','PDD','TCOM','NTES','BILI','IQ','VIPS','TIGR',
    'TME','HUYA','DOYU','YMM','BZ','XPEV','NIO','LI','NIO',
    # Taiwan / Korea / Japan
    'TSM','SNE','SONY','TM','HMC','NTDOY','SFTBY','FUJHY','KYOCY',
    # Europe
    'ASML','SAP','NVO','AZN','GSK','BP','SHEL','RIO','BHP','BTI',
    'LVMUY','MC','HESAY','RNLSY','BMWYY','VLKAF',
    # Canada
    'SHOP','LSPD','SPOT','BB','CNQ','SU','ENB','TD','RY','BMO',
    # Southeast Asia / Emerging
    'SE','GRAB','GOTO','BEKE','KGWY','ZTO','YSX','TIGR',
    # Latin America
    'MELI','NU','STNE','PAGS','VTEX','ARCO','DESP',
    # India
    'INFY','WIT','HDB','IBN','SIFY','YTRA',
    # Israel Tech
    'CHKP','CYBR','NICE','MNDO','GILT','NNDM',
]

# Popular individual stocks outside S&P500/NASDAQ100 — mid/large cap
POPULAR_STOCKS = [
    # Tech / SaaS
    'UBER','LYFT','ABNB','DASH','SNAP','PINS','BMBL','MTCH',
    'SPOT','RBLX','U','HOOD','SOFI','AFRM','UPST','SQ','PYPL',
    'TWLO','ZM','DOCN','DDOG','NET','MDB','ESTC','GTLB','BILL',
    'HUBS','SPRK','VEEV','CDAY','PCTY','PAYC','WK','APPN',
    'ASAN','MNDY','ZI','SEMR','S','JAMF','BRZE','AMPL',
    # Cloud / Infrastructure
    'SNOW','PLTR','PATH','AI','BBAI','SOUN','GFAI',
    'IONQ','QUBT','RGTI','IBM',
    # Fintech / Crypto
    'COIN','MSTR','RIOT','MARA','HUT','BITF','CLSK','WULF',
    'IREN','CORZ','BTDR','CIFR',
    # EV / Clean Energy
    'RIVN','LCID','NIO','XPEV','LI','TSLA','FFIE','MULN','EVGO',
    'BLNK','CHPT','PLUG','FCEL','BE','ENPH','SEDG','NOVA','RUN',
    # Healthcare / Biotech
    'MRNA','BNTX','NVAX','NTLA','CRSP','BEAM','EDIT',
    'RXRX','SEER','PACB','ILMN','VEEV','TDOC','HIMS','ACCD',
    # Consumer / Retail
    'DUOL','ABNB','DASH','LYFT','UBER','ETSY','W','CHWY','PRTS',
    'RH','FIVE','OLLI','BJ','COST','TJX','ROST','BURL',
    # Aerospace / Defense
    'RKLB','ASTS','SPCE','LUNR','ACHR','JOBY','KTOS','LOAR',
    # Entertainment
    'NFLX','DIS','PARA','WBD','FOXA','LGF','IMAX','CNK',
    # Real Estate Tech
    'OPEN','RDFN','ZG','Z','EXPI','COMP',
    # Finance
    'SCHW','IBKR','RJF','SF','LPLA','MKTX','MSGE',
]

# Common name / alias → real yfinance ticker
# Use this to normalize user input before any data fetch
TICKER_ALIASES: dict = {
    # Taiwan Semi — common name vs US ADR
    "TSMC":   "TSM",
    # Berkshire
    "BRKB":   "BRK-B",
    "BRKA":   "BRK-A",
    "BRK.B":  "BRK-B",
    "BRK.A":  "BRK-A",
    # Google
    "GOOGLE": "GOOGL",
    # Meta / Facebook
    "FB":     "META",
    "FACEBOOK": "META",
    # Twitter/X
    "TWTR":   "X",
    # Alibaba
    "ALIBABA": "BABA",
    # Tencent (HK → ADR)
    "TENCENT": "TCEHY",
    "700.HK":  "TCEHY",
    # Samsung (KRX → ADR)
    "SAMSUNG": "SSNLF",
    # Toyota
    "TOYOTA":  "TM",
    # Sony
    "SONY":    "SONY",
    # Nvidia common spellings
    "NVIDIA":  "NVDA",
    # Apple
    "APPLE":   "AAPL",
    # Microsoft
    "MICROSOFT": "MSFT",
    # Amazon
    "AMAZON":  "AMZN",
    # Tesla
    "TESLA":   "TSLA",
    # Netflix
    "NETFLIX": "NFLX",
    # Shopify
    "SHOPIFY": "SHOP",
    # Palantir
    "PALANTIR": "PLTR",
    # Coinbase
    "COINBASE": "COIN",
    # Robinhood
    "ROBINHOOD": "HOOD",
    # Sea Limited
    "SEA":     "SE",
    # NuBank
    "NUBANK":  "NU",
    # Grab
    "GRABCAR": "GRAB",
    # Novo Nordisk
    "NOVONORDISK": "NVO",
    # ASML (Dutch) — already correct as ASML on NASDAQ
    # Spotify
    "SPOTIFY": "SPOT",
    # Snowflake
    "SNOWFLAKE": "SNOW",
    # Roblox
    "ROBLOX":  "RBLX",
    # Rocket Lab
    "ROCKETLAB": "RKLB",
    # IonQ
    "IONQUANTUM": "IONQ",
    # Crypto → yfinance suffix
    "BTC":     "BTC-USD",
    "ETH":     "ETH-USD",
    "SOL":     "SOL-USD",
    "BNB":     "BNB-USD",
    "XRP":     "XRP-USD",
    "DOGE":    "DOGE-USD",
    "AVAX":    "AVAX-USD",
    "LINK":    "LINK-USD",
    "ADA":     "ADA-USD",
    "DOT":     "DOT-USD",
    "MATIC":   "MATIC-USD",
    "SHIB":    "SHIB-USD",
    "PEPE":    "PEPE-USD",
    "TON":     "TON-USD",
    # Commodities
    "GOLD":    "GC=F",
    "XAU":     "GC=F",
    "SILVER":  "SI=F",
    "XAG":     "SI=F",
    "OIL":     "CL=F",
    "CRUDE":   "CL=F",
    "NATGAS":  "NG=F",
    "COPPER":  "HG=F",
    # Indices
    "NASDAQ":  "^IXIC",
    "SP500":   "^GSPC",
    "DOW":     "^DJI",
    "VIX":     "^VIX",
    "DXY":     "DX-Y.NYB",
}

# TradingView exchange prefix per ticker
# Stocks not listed here default to NASDAQ (correct for all NASDAQ100 members)
TV_EXCHANGE_MAP: dict = {
    # ── NYSE-listed stocks ──────────────────────────────────────────────────
    # ADRs (foreign companies on NYSE)
    "TSM":  "NYSE", "NVO":  "NYSE", "TM":   "NYSE", "HMC":  "NYSE",
    "BABA": "NYSE", "JD":   "NYSE", "TCOM": "NYSE", "ZTO":  "NYSE",
    "NIO":  "NYSE", "XPEV": "NYSE", "LI":   "NYSE", "YMM":  "NYSE",
    "SE":   "NYSE", "GRAB": "NASDAQ", "NU":  "NYSE", "MELI": "NASDAQ",
    "STNE": "NYSE", "PAGS": "NYSE",
    "BP":   "NYSE", "SHEL": "NYSE", "RIO":  "NYSE", "BHP":  "NYSE",
    "BTI":  "NYSE", "AZN":  "NASDAQ", "GSK": "NYSE", "NVS": "NYSE",
    "SAP":  "NYSE", "SONY": "NYSE", "SNE":  "NYSE",
    # US Financials (NYSE)
    "JPM":  "NYSE", "BAC":  "NYSE", "WFC":  "NYSE", "C":    "NYSE",
    "GS":   "NYSE", "MS":   "NYSE", "BLK":  "NYSE", "BX":   "NYSE",
    "AXP":  "NYSE", "V":    "NYSE", "MA":   "NYSE", "COF":  "NYSE",
    "USB":  "NYSE", "TFC":  "NYSE", "PNC":  "NYSE", "SCHW": "NYSE",
    "BK":   "NYSE", "STT":  "NYSE", "RF":   "NYSE", "KEY":  "NYSE",
    "HBAN": "NYSE", "MTB":  "NYSE", "CFG":  "NYSE", "SYF":  "NYSE",
    "AIG":  "NYSE", "MET":  "NYSE", "PRU":  "NYSE", "AFL":  "NYSE",
    "ALL":  "NYSE", "CB":   "NYSE", "TRV":  "NYSE", "HIG":  "NYSE",
    "ICE":  "NYSE", "CME":  "NASDAQ", "SPGI": "NYSE", "MCO": "NYSE",
    # US Healthcare (NYSE)
    "JNJ":  "NYSE", "PFE":  "NYSE", "MRK":  "NYSE", "ABT":  "NYSE",
    "BMY":  "NYSE", "LLY":  "NYSE", "UNH":  "NYSE", "CVS":  "NYSE",
    "MDT":  "NYSE", "SYK":  "NYSE", "BSX":  "NYSE", "EW":   "NYSE",
    "ZBH":  "NYSE", "BDX":  "NYSE", "DHR":  "NYSE", "TMO":  "NYSE",
    "IQV":  "NYSE", "CRL":  "NYSE", "RMD":  "NYSE", "HCA":  "NYSE",
    # US Energy (NYSE)
    "XOM":  "NYSE", "CVX":  "NYSE", "COP":  "NYSE", "EOG":  "NYSE",
    "SLB":  "NYSE", "HAL":  "NYSE", "OXY":  "NYSE", "PSX":  "NYSE",
    "MPC":  "NYSE", "VLO":  "NYSE", "DVN":  "NYSE", "FANG": "NASDAQ",
    # US Industrials (NYSE)
    "BA":   "NYSE", "GE":   "NYSE", "CAT":  "NYSE", "MMM":  "NYSE",
    "RTX":  "NYSE", "LMT":  "NYSE", "NOC":  "NYSE", "GD":   "NYSE",
    "UPS":  "NYSE", "FDX":  "NYSE", "DE":   "NYSE", "EMR":  "NYSE",
    "ETN":  "NYSE", "ITW":  "NYSE", "PH":   "NYSE", "ROK":  "NYSE",
    "DOV":  "NYSE", "SWK":  "NYSE", "GWW":  "NYSE", "WAB":  "NYSE",
    # US Consumer (NYSE)
    "KO":   "NYSE", "PG":   "NYSE", "WMT":  "NYSE", "HD":   "NYSE",
    "MCD":  "NYSE", "PM":   "NYSE", "MO":   "NYSE", "KMB":  "NYSE",
    "CL":   "NYSE", "CHD":  "NYSE", "CLX":  "NYSE", "HRL":  "NYSE",
    "GIS":  "NYSE", "CPB":  "NYSE", "K":    "NYSE", "CAG":  "NYSE",
    "LUV":  "NYSE", "DAL":  "NYSE", "UAL":  "NYSE", "AAL":  "NYSE",
    "CCL":  "NYSE", "RCL":  "NYSE", "NCLH": "NYSE", "MAR":  "NASDAQ",
    "HLT":  "NYSE", "MGM":  "NYSE", "WYNN": "NASDAQ","LVS":  "NYSE",
    # US Real Estate / Utilities (NYSE)
    "AMT":  "NYSE", "PLD":  "NYSE", "CCI":  "NYSE", "SPG":  "NYSE",
    "O":    "NYSE", "DLR":  "NYSE", "EQIX": "NASDAQ","PSA":  "NYSE",
    "NEE":  "NYSE", "DUK":  "NYSE", "SO":   "NYSE",  "D":   "NYSE",
    "AEP":  "NYSE", "EXC":  "NASDAQ","XEL":  "NASDAQ","ED":  "NYSE",
    # US Materials (NYSE)
    "LIN":  "NASDAQ","APD": "NYSE",  "ECL":  "NYSE",  "SHW": "NYSE",
    "FCX":  "NYSE", "NEM":  "NYSE",  "NUE":  "NYSE",  "VMC": "NYSE",
    # Telecom (NYSE)
    "T":    "NYSE", "VZ":   "NYSE",
    # Media (NYSE / NASDAQ)
    "DIS":  "NYSE", "CMCSA":"NASDAQ","PARA": "NASDAQ","WBD": "NASDAQ",
    # ETFs
    "SPY":  "AMEX", "IVV":  "NYSE",  "VOO":  "NYSE",  "VTI": "NYSE",
    "QQQ":  "NASDAQ","IWM": "NYSE",  "DIA":  "AMEX",
    "GLD":  "NYSE",  "IAU": "NYSE",  "SLV":  "NYSE",  "USO": "NYSE",
    "TLT":  "NASDAQ","AGG": "NYSE",  "HYG":  "NYSE",  "LQD": "NYSE",
    "XLK":  "NYSE",  "XLF": "NYSE",  "XLV":  "NYSE",  "XLE": "NYSE",
    "XLI":  "NYSE",  "XLY": "NYSE",  "XLP":  "NYSE",
    "TQQQ": "NASDAQ","SQQQ":"NASDAQ","SPXL": "NYSE",  "SOXL":"NYSE",
    "ARKK": "NYSE",  "ARKG":"NYSE",  "ARKW": "NYSE",
    "VGT":  "NYSE",  "SOXX":"NASDAQ","SMH":  "NASDAQ",
    # Crypto (Binance)
    "BTC":  "BINANCE","ETH": "BINANCE","SOL":  "BINANCE",
    "BNB":  "BINANCE","XRP": "BINANCE","DOGE": "BINANCE",
}

MACRO_MAPPING = {
    # Commodities
    "GOLD":   "GC=F",
    "SILVER": "SI=F",
    "OIL":    "CL=F",
    "COPPER": "HG=F",
    "NATGAS": "NG=F",
    # Indices
    "NASDAQ": "^IXIC",
    "SP500":  "^GSPC",
    "DOW":    "^DJI",
    # Crypto (yfinance tickers)
    "BTC":    "BTC-USD",
    "ETH":    "ETH-USD",
    "SOL":    "SOL-USD",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "SOLUSD": "SOL-USD",
    "XRPUSD": "XRP-USD",
    # Forex
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "USDCHF": "CHF=X",
    "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
}

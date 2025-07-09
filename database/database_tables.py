from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import DatabaseException

logger = get_logger(__name__)


class DatabaseTables:
    """Создание и управление таблицами базы данных"""
    
    def __init__(self, db_connection):
        self.db_connection = db_connection
    
    async def create_all_tables(self):
        """Создание всех таблиц"""
        try:
            await self._create_watchlist_table()
            await self._create_kline_data_table()
            await self._create_alerts_table()
            await self._create_favorites_table()
            await self._create_trading_settings_table()
            await self._create_paper_trades_table()
            await self._create_social_ratings_table()
            await self._create_streaming_candles_table()
            
            logger.info("✅ Все таблицы созданы успешно")
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания таблиц: {e}")
            raise DatabaseException(f"Ошибка создания таблиц: {e}")
    
    async def _create_watchlist_table(self):
        """Создание таблицы watchlist"""
        query = """
        CREATE TABLE IF NOT EXISTS watchlist (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) UNIQUE NOT NULL,
            price_drop FLOAT DEFAULT 0,
            current_price FLOAT DEFAULT 0,
            historical_price FLOAT DEFAULT 0,
            is_active BOOLEAN DEFAULT true,
            added_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
        await self.db_connection.execute_command(query)
        
        # Создаем индексы
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlist(is_active)"
        )
    
    async def _create_kline_data_table(self):
        """Создание таблицы kline_data"""
        query = """
        CREATE TABLE IF NOT EXISTS kline_data (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            start_time BIGINT NOT NULL,
            end_time BIGINT NOT NULL,
            open_price DECIMAL(20, 8) NOT NULL,
            high_price DECIMAL(20, 8) NOT NULL,
            low_price DECIMAL(20, 8) NOT NULL,
            close_price DECIMAL(20, 8) NOT NULL,
            volume DECIMAL(20, 8) NOT NULL,
            is_closed BOOLEAN DEFAULT false,
            is_long BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(symbol, start_time)
        )
        """
        await self.db_connection.execute_command(query)
        
        # Создаем индексы
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_kline_symbol_time ON kline_data(symbol, start_time)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_kline_closed ON kline_data(is_closed)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_kline_long ON kline_data(is_long)"
        )
    
    async def _create_alerts_table(self):
        """Создание таблицы alerts"""
        query = """
        CREATE TABLE IF NOT EXISTS alerts (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            alert_type VARCHAR(50) NOT NULL,
            price DECIMAL(20, 8) NOT NULL,
            volume_ratio FLOAT,
            current_volume_usdt BIGINT,
            average_volume_usdt BIGINT,
            consecutive_count INTEGER,
            alert_timestamp_ms BIGINT NOT NULL,
            close_timestamp_ms BIGINT,
            is_closed BOOLEAN DEFAULT false,
            is_true_signal BOOLEAN,
            has_imbalance BOOLEAN DEFAULT false,
            imbalance_data JSONB,
            candle_data JSONB,
            order_book_snapshot JSONB,
            message TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
        await self.db_connection.execute_command(query)
        
        # Создаем индексы
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(alert_timestamp_ms)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status)"
        )
    
    async def _create_favorites_table(self):
        """Создание таблицы favorites"""
        query = """
        CREATE TABLE IF NOT EXISTS favorites (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) UNIQUE NOT NULL,
            notes TEXT,
            color VARCHAR(7) DEFAULT '#FFD700',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
        await self.db_connection.execute_command(query)
        
        # Создаем индексы
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_favorites_symbol ON favorites(symbol)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_favorites_sort ON favorites(sort_order)"
        )
    
    async def _create_trading_settings_table(self):
        """Создание таблицы trading_settings"""
        query = """
        CREATE TABLE IF NOT EXISTS trading_settings (
            id SERIAL PRIMARY KEY,
            account_balance DECIMAL(20, 2) DEFAULT 10000,
            max_risk_per_trade DECIMAL(5, 2) DEFAULT 2.0,
            max_open_trades INTEGER DEFAULT 5,
            default_stop_loss_percentage DECIMAL(5, 2) DEFAULT 2.0,
            default_take_profit_percentage DECIMAL(5, 2) DEFAULT 4.0,
            auto_calculate_quantity BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
        await self.db_connection.execute_command(query)
        
        # Вставляем настройки по умолчанию если таблица пуста
        check_query = "SELECT COUNT(*) as count FROM trading_settings"
        result = await self.db_connection.execute_query(check_query)
        
        if result[0]['count'] == 0:
            insert_query = "INSERT INTO trading_settings DEFAULT VALUES"
            await self.db_connection.execute_command(insert_query)
    
    async def _create_paper_trades_table(self):
        """Создание таблицы paper_trades"""
        query = """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            trade_type VARCHAR(10) NOT NULL,
            entry_price DECIMAL(20, 8) NOT NULL,
            exit_price DECIMAL(20, 8),
            quantity DECIMAL(20, 8) NOT NULL,
            stop_loss DECIMAL(20, 8),
            take_profit DECIMAL(20, 8),
            risk_amount DECIMAL(20, 2),
            risk_percentage DECIMAL(5, 2),
            potential_profit DECIMAL(20, 2),
            potential_loss DECIMAL(20, 2),
            actual_profit DECIMAL(20, 2),
            risk_reward_ratio DECIMAL(10, 2),
            status VARCHAR(20) DEFAULT 'open',
            exit_reason VARCHAR(50),
            notes TEXT,
            alert_id INTEGER,
            entry_time TIMESTAMPTZ DEFAULT NOW(),
            exit_time TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
        await self.db_connection.execute_command(query)
        
        # Создаем индексы
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol ON paper_trades(symbol)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_paper_trades_entry_time ON paper_trades(entry_time)"
        )
    
    async def _create_social_ratings_table(self):
        """Создание таблицы social_ratings"""
        query = """
        CREATE TABLE IF NOT EXISTS social_ratings (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            overall_score FLOAT NOT NULL,
            mention_count INTEGER NOT NULL,
            positive_mentions INTEGER NOT NULL,
            negative_mentions INTEGER NOT NULL,
            neutral_mentions INTEGER NOT NULL,
            trending_score FLOAT NOT NULL,
            volume_score FLOAT NOT NULL,
            sentiment_trend VARCHAR(20) NOT NULL,
            last_updated TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
        await self.db_connection.execute_command(query)
        
        # Создаем индексы
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_social_ratings_symbol ON social_ratings(symbol)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_social_ratings_updated ON social_ratings(last_updated)"
        )
    
    async def _create_streaming_candles_table(self):
        """Создание таблицы streaming_candles для потоковых данных"""
        query = """
        CREATE TABLE IF NOT EXISTS streaming_candles (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            start_time BIGINT NOT NULL,
            end_time BIGINT NOT NULL,
            open_price DECIMAL(20, 8) NOT NULL,
            high_price DECIMAL(20, 8) NOT NULL,
            low_price DECIMAL(20, 8) NOT NULL,
            close_price DECIMAL(20, 8) NOT NULL,
            volume DECIMAL(20, 8) NOT NULL,
            is_closed BOOLEAN DEFAULT false,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(symbol, start_time)
        )
        """
        await self.db_connection.execute_command(query)
        
        # Создаем индексы
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_streaming_symbol_time ON streaming_candles(symbol, start_time)"
        )
        await self.db_connection.execute_command(
            "CREATE INDEX IF NOT EXISTS idx_streaming_updated ON streaming_candles(updated_at)"
        )
    
    async def drop_table(self, table_name: str):
        """Удаление таблицы"""
        try:
            query = f"DROP TABLE IF EXISTS {table_name} CASCADE"
            await self.db_connection.execute_command(query)
            logger.info(f"✅ Таблица {table_name} удалена")
        except Exception as e:
            logger.error(f"❌ Ошибка удаления таблицы {table_name}: {e}")
            raise DatabaseException(f"Ошибка удаления таблицы: {e}")
    
    async def truncate_table(self, table_name: str):
        """Очистка таблицы"""
        try:
            query = f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE"
            await self.db_connection.execute_command(query)
            logger.info(f"✅ Таблица {table_name} очищена")
        except Exception as e:
            logger.error(f"❌ Ошибка очистки таблицы {table_name}: {e}")
            raise DatabaseException(f"Ошибка очистки таблицы: {e}")
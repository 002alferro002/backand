import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import TimeSyncException
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class ExchangeTimeSync:
    """Синхронизация времени с биржей"""
    
    def __init__(self, time_server_sync):
        self.time_server_sync = time_server_sync
        self.exchange_time_offset = 0  # Разница между локальным и биржевым временем в мс
        self.last_exchange_sync = None
        self.is_exchange_synced = False
        
        # Настройки синхронизации
        self.exchange_sync_interval = get_setting('TIME_SYNC_INTERVAL', 300)  # 5 минут
        self.base_url = "https://api.bybit.com"
    
    async def sync_exchange_time(self) -> bool:
        """Синхронизация времени с биржей"""
        try:
            url = f"{self.base_url}/v5/market/time"

            # Используем точное UTC время для измерения задержки
            accurate_time_before = self.time_server_sync.get_accurate_utc_timestamp_ms()

            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Засекаем время после получения ответа
                        accurate_time_after = self.time_server_sync.get_accurate_utc_timestamp_ms()

                        if data.get('retCode') == 0:
                            # Получаем время биржи
                            exchange_time_seconds = int(data['result']['timeSecond'])
                            exchange_time_nanos = int(data['result']['timeNano'])

                            # Преобразуем в миллисекунды
                            exchange_time = exchange_time_seconds * 1000 + (exchange_time_nanos // 1_000_000) % 100

                            # Учитываем задержку сети
                            network_delay = (accurate_time_after - accurate_time_before) / 2
                            adjusted_accurate_time = accurate_time_before + network_delay

                            # Рассчитываем смещение биржи относительно точного UTC
                            self.exchange_time_offset = exchange_time - adjusted_accurate_time
                            self.last_exchange_sync = datetime.now(timezone.utc)
                            self.is_exchange_synced = True

                            # Проверяем корректность времени
                            expected_range_min = 1700000000000  # 2023 год
                            expected_range_max = 2000000000000  # 2033 год

                            if expected_range_min <= exchange_time <= expected_range_max:
                                logger.info(
                                    f"✅ Время синхронизировано с биржей Bybit. Смещение биржи: {self.exchange_time_offset:.0f}мс")
                                return True
                            else:
                                logger.error(f"❌ Некорректное время биржи: {exchange_time}")
                                self.is_exchange_synced = False
                                return False
                        else:
                            logger.error(f"❌ Ошибка API биржи при синхронизации времени: {data.get('retMsg')}")
                    else:
                        logger.error(f"❌ HTTP ошибка при синхронизации времени: {response.status}")

        except asyncio.TimeoutError:
            logger.error("⏰ Таймаут при синхронизации времени с биржей")
        except Exception as e:
            logger.error(f"❌ Ошибка синхронизации времени с биржей: {e}")

        self.is_exchange_synced = False
        return False
    
    def get_exchange_timestamp_ms(self) -> int:
        """Получить timestamp биржи в миллисекундах"""
        if self.is_exchange_synced:
            accurate_time = self.time_server_sync.get_accurate_utc_timestamp_ms()
            return int(accurate_time + self.exchange_time_offset)
        else:
            # Fallback на точное UTC время
            return self.time_server_sync.get_accurate_utc_timestamp_ms()
    
    def get_sync_status(self) -> Dict:
        """Получить статус синхронизации с биржей"""
        return {
            'is_synced': self.is_exchange_synced,
            'last_sync': self.last_exchange_sync.isoformat() if self.last_exchange_sync else None,
            'time_offset_ms': self.exchange_time_offset,
            'sync_age_seconds': (datetime.now(timezone.utc) - self.last_exchange_sync).total_seconds() if self.last_exchange_sync else None,
            'exchange_time': self.get_exchange_timestamp_ms(),
            'status': 'synced' if self.is_exchange_synced else 'not_synced'
        }
    
    def is_sync_valid(self, max_age_seconds: int = None) -> bool:
        """Проверка актуальности синхронизации с биржей"""
        if max_age_seconds is None:
            max_age_seconds = self.exchange_sync_interval * 2  # Двойной интервал
        
        if not self.is_exchange_synced or not self.last_exchange_sync:
            return False
        
        age_seconds = (datetime.now(timezone.utc) - self.last_exchange_sync).total_seconds()
        return age_seconds < max_age_seconds
    
    def is_candle_closed(self, kline_data: dict) -> bool:
        """Проверка закрытия свечи относительно времени биржи"""
        exchange_time = self.get_exchange_timestamp_ms()
        candle_end_time = int(kline_data['end'])

        # Свеча считается закрытой, если время биржи >= времени окончания свечи
        return exchange_time >= candle_end_time
    
    def get_candle_close_time_utc(self, kline_start_time: int) -> datetime:
        """Получить время закрытия свечи в UTC"""
        return datetime.utcfromtimestamp((kline_start_time + 60000) / 1000)
import asyncio
from datetime import datetime, timezone
from typing import Dict
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import TimeSyncException
from .times_server_sync import TimeServerSync
from .times_exchange_sync import ExchangeTimeSync
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class TimeManager:
    """Главный менеджер синхронизации времени"""

    def __init__(self):
        # Инициализация компонентов синхронизации
        self.time_server_sync = TimeServerSync()
        self.exchange_sync = ExchangeTimeSync(self.time_server_sync)
        
        # Настройки
        self.time_server_sync_interval = get_setting('TIME_SERVER_SYNC_INTERVAL', 3600)  # 1 час
        self.exchange_sync_interval = get_setting('TIME_SYNC_INTERVAL', 300)  # 5 минут
        self.sync_method = 'auto'  # 'auto', 'exchange_only', 'time_servers_only'
        
        # Состояние
        self.is_running = False
        self.sync_task = None

    async def start(self):
        """Запуск системы синхронизации времени"""
        self.is_running = True
        logger.info("🕐 Запуск системы синхронизации времени UTC")

        try:
            # Первоначальная синхронизация с серверами точного времени
            await self.time_server_sync.sync_with_time_servers()

            # Первоначальная синхронизация с биржей
            await self.exchange_sync.sync_exchange_time()

            # Запускаем периодическую синхронизацию
            self.sync_task = asyncio.create_task(self._periodic_sync())
            
            logger.info("✅ Система синхронизации времени запущена")

        except Exception as e:
            logger.error(f"❌ Ошибка запуска системы синхронизации времени: {e}")
            raise TimeSyncException(f"Ошибка запуска синхронизации времени: {e}")

    async def stop(self):
        """Остановка синхронизации"""
        self.is_running = False
        if self.sync_task:
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass
        logger.info("🕐 Синхронизация времени остановлена")

    async def _periodic_sync(self):
        """Периодическая синхронизация времени"""
        last_time_server_sync = datetime.now(timezone.utc)()
        last_exchange_sync = datetime.now(timezone.utc)()
        
        while self.is_running:
            try:
                current_time = datetime.now(timezone.utc)()
                
                # Синхронизация с серверами времени каждый час
                if (current_time - last_time_server_sync).total_seconds() > self.time_server_sync_interval:
                    await self.time_server_sync.sync_with_time_servers()
                    last_time_server_sync = current_time
                
                # Синхронизация с биржей каждые 5 минут
                if (current_time - last_exchange_sync).total_seconds() > self.exchange_sync_interval:
                    await self.exchange_sync.sync_exchange_time()
                    last_exchange_sync = current_time
                
                # Ждем до следующей проверки
                await asyncio.sleep(60)  # Проверяем каждую минуту
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Ошибка периодической синхронизации времени: {e}")
                await asyncio.sleep(60)  # Повторить через минуту при ошибке

    def get_utc_timestamp_ms(self) -> int:
        """Получить точный UTC timestamp в миллисекундах"""
        if self.sync_method == 'time_servers_only' or not self.exchange_sync.is_exchange_synced:
            # Используем серверы точного времени
            return self.time_server_sync.get_accurate_utc_timestamp_ms()
        elif self.sync_method == 'exchange_only':
            # Используем только биржевое время
            return self.exchange_sync.get_exchange_timestamp_ms()
        else:
            # Автоматический режим - приоритет серверам точного времени
            if self.time_server_sync.is_synced:
                return self.time_server_sync.get_accurate_utc_timestamp_ms()
            elif self.exchange_sync.is_exchange_synced:
                return self.exchange_sync.get_exchange_timestamp_ms()
            else:
                # Fallback на локальное UTC время
                return int(datetime.now(timezone.utc).timestamp() * 1000)

    def get_exchange_timestamp_ms(self) -> int:
        """Получить timestamp биржи в миллисекундах"""
        return self.exchange_sync.get_exchange_timestamp_ms()

    def get_sync_status(self) -> Dict:
        """Получить полный статус синхронизации"""
        utc_time = self.get_utc_timestamp_ms()
        
        return {
            'is_synced': self.time_server_sync.is_synced or self.exchange_sync.is_exchange_synced,
            'time_servers': self.time_server_sync.get_sync_status(),
            'exchange_sync': self.exchange_sync.get_sync_status(),
            'sync_method': self.sync_method,
            'utc_time': utc_time,
            'utc_time_iso': datetime.utcfromtimestamp(utc_time / 1000).isoformat() + 'Z',
            'serverTime': utc_time,  # Для совместимости с клиентом
            'status': 'active' if (self.time_server_sync.is_synced or self.exchange_sync.is_exchange_synced) else 'not_synced'
        }

    def set_sync_method(self, method: str):
        """Установить метод синхронизации"""
        if method in ['auto', 'exchange_only', 'time_servers_only']:
            self.sync_method = method
            logger.info(f"🔧 Метод синхронизации изменен на: {method}")
        else:
            logger.error(f"❌ Неизвестный метод синхронизации: {method}")
            raise TimeSyncException(f"Неизвестный метод синхронизации: {method}")

    def is_candle_closed(self, kline_data: dict) -> bool:
        """Проверка закрытия свечи"""
        if self.sync_method == 'exchange_only' and self.exchange_sync.is_exchange_synced:
            return self.exchange_sync.is_candle_closed(kline_data)
        else:
            # Используем UTC время
            utc_time = self.get_utc_timestamp_ms()
            candle_end_time = int(kline_data['end'])
            return utc_time >= candle_end_time

    def get_time_info(self) -> Dict:
        """Получить информацию о времени для API"""
        try:
            if self.time_server_sync.is_synced or self.exchange_sync.is_exchange_synced:
                return self.get_sync_status()
            else:
                # Fallback на локальное UTC время
                current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                return {
                    "is_synced": False,
                    "serverTime": current_time_ms,
                    "local_time": datetime.now(timezone.utc).isoformat(),
                    "utc_time": datetime.now(timezone.utc).isoformat(),
                    "time_offset_ms": 0,
                    "status": "not_synced"
                }
        except Exception as e:
            logger.error(f"Ошибка получения информации о времени: {e}")
            # Аварийный fallback
            current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            return {
                "is_synced": False,
                "serverTime": current_time_ms,
                "local_time": datetime.now(timezone.utc).isoformat(),
                "utc_time": datetime.now(timezone.utc).isoformat(),
                "time_offset_ms": 0,
                "status": "error",
                "error": str(e)
            }

    def is_time_synced(self) -> bool:
        """Проверка состояния синхронизации"""
        return self.time_server_sync.is_synced or self.exchange_sync.is_exchange_synced
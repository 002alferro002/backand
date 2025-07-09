import asyncio
import aiohttp
import time
from datetime import datetime
from typing import Optional, Dict, List
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import TimeSyncException

logger = get_logger(__name__)


class TimeServerSync:
    """Синхронизация с серверами точного времени"""
    
    def __init__(self):
        # Список серверов точного времени
        self.time_servers = [
            "http://worldtimeapi.org/api/timezone/UTC",
            "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
            "http://worldclockapi.com/api/json/utc/now"
        ]
        self.last_sync = None
        self.time_offset_ms = 0  # Смещение локального времени относительно точного UTC
        self.is_synced = False
        
    async def sync_with_time_servers(self) -> bool:
        """Синхронизация с серверами точного времени"""
        for server_url in self.time_servers:
            try:
                success = await self._sync_with_server(server_url)
                if success:
                    self.is_synced = True
                    self.last_sync = datetime.now(timezone.utc)
                    logger.info(f"✅ Синхронизация с сервером времени успешна: {server_url}")
                    logger.info(f"⏰ Смещение времени: {self.time_offset_ms}мс")
                    return True
            except Exception as e:
                logger.warning(f"⚠️ Ошибка синхронизации с {server_url}: {e}")
                continue
        
        logger.error("❌ Не удалось синхронизироваться ни с одним сервером времени")
        return False
    
    async def _sync_with_server(self, server_url: str) -> bool:
        """Синхронизация с конкретным сервером"""
        try:
            # Засекаем время до запроса
            local_time_before = time.time() * 1000
            
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(server_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Засекаем время после получения ответа
                        local_time_after = time.time() * 1000
                        
                        # Извлекаем UTC время из ответа
                        server_time_ms = self._extract_utc_time(data, server_url)
                        if server_time_ms is None:
                            return False
                        
                        # Учитываем задержку сети
                        network_delay = (local_time_after - local_time_before) / 2
                        adjusted_local_time = local_time_before + network_delay
                        
                        # Рассчитываем смещение
                        self.time_offset_ms = server_time_ms - adjusted_local_time
                        
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка синхронизации с {server_url}: {e}")
            return False
    
    def _extract_utc_time(self, data: Dict, server_url: str) -> Optional[int]:
        """Извлечение UTC времени из ответа сервера"""
        try:
            if "worldtimeapi.org" in server_url:
                # WorldTimeAPI
                utc_datetime = data.get('utc_datetime')
                if utc_datetime:
                    dt = datetime.fromisoformat(utc_datetime.replace('Z', '+00:00'))
                    return int(dt.timestamp() * 1000)
            
            elif "timeapi.io" in server_url:
                # TimeAPI.io
                date_time = data.get('dateTime')
                if date_time:
                    dt = datetime.fromisoformat(date_time.replace('Z', '+00:00'))
                    return int(dt.timestamp() * 1000)
            
            elif "worldclockapi.com" in server_url:
                # WorldClockAPI
                current_date_time = data.get('currentDateTime')
                if current_date_time:
                    dt = datetime.fromisoformat(current_date_time.replace('Z', '+00:00'))
                    return int(dt.timestamp() * 1000)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка извлечения времени из ответа {server_url}: {e}")
            return None
    
    def get_accurate_utc_timestamp_ms(self) -> int:
        """Получить точный UTC timestamp в миллисекундах"""
        if self.is_synced:
            local_time_ms = time.time() * 1000
            return int(local_time_ms + self.time_offset_ms)
        else:
            # Fallback на локальное UTC время
            return int(datetime.now(timezone.utc)().timestamp() * 1000)
    
    def get_sync_status(self) -> Dict:
        """Получить статус синхронизации"""
        return {
            'is_synced': self.is_synced,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'time_offset_ms': self.time_offset_ms,
            'sync_age_seconds': (datetime.now(timezone.utc) - self.last_sync).total_seconds() if self.last_sync else None,
            'accurate_utc_time': self.get_accurate_utc_timestamp_ms(),
            'status': 'synced' if self.is_synced else 'not_synced'
        }
    
    def is_sync_valid(self, max_age_seconds: int = 3600) -> bool:
        """Проверка актуальности синхронизации"""
        if not self.is_synced or not self.last_sync:
            return False
        
        age_seconds = (datetime.now(timezone.utc) - self.last_sync).total_seconds()
        return age_seconds < max_age_seconds
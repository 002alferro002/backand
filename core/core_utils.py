import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union
from cryptoscan.backand.core.core_logger import get_logger

logger = get_logger(__name__)


class CoreUtils:
    """Утилиты общего назначения"""
    
    @staticmethod
    def safe_float(value: Any, default: float = 0.0) -> float:
        """Безопасное преобразование в float"""
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def safe_int(value: Any, default: int = 0) -> int:
        """Безопасное преобразование в int"""
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def safe_bool(value: Any, default: bool = False) -> bool:
        """Безопасное преобразование в bool"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        try:
            return bool(int(value))
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def format_timestamp(timestamp: Union[int, float, datetime], format_str: str = '%H:%M:%S UTC') -> str:
        """Форматирование timestamp"""
        try:
            if isinstance(timestamp, (int, float)):
                # Если timestamp в миллисекундах
                if timestamp > 1e12:
                    timestamp = timestamp / 1000
                dt = datetime.utcfromtimestamp(timestamp)
            elif isinstance(timestamp, datetime):
                dt = timestamp
            else:
                dt = datetime.now(timezone.utc)()
            
            return dt.strftime(format_str)
        except Exception:
            return datetime.now(timezone.utc)().strftime(format_str)
    
    @staticmethod
    def get_utc_timestamp_ms() -> int:
        """Получение UTC timestamp в миллисекундах"""
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    
    @staticmethod
    def serialize_for_json(obj: Any) -> Any:
        """Сериализация объекта для JSON"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        else:
            return str(obj)
    
    @staticmethod
    def safe_json_dumps(data: Dict, default=None) -> str:
        """Безопасная сериализация в JSON"""
        try:
            return json.dumps(data, default=default or CoreUtils.serialize_for_json)
        except Exception as e:
            logger.error(f"Ошибка сериализации JSON: {e}")
            return "{}"
    
    @staticmethod
    def safe_json_loads(data: str, default: Dict = None) -> Dict:
        """Безопасная десериализация из JSON"""
        try:
            return json.loads(data)
        except Exception as e:
            logger.error(f"Ошибка десериализации JSON: {e}")
            return default or {}
    
    @staticmethod
    async def safe_async_call(coro, default=None, log_errors=True):
        """Безопасный вызов асинхронной функции"""
        try:
            return await coro
        except Exception as e:
            if log_errors:
                logger.error(f"Ошибка в асинхронном вызове: {e}")
            return default
    
    @staticmethod
    def calculate_percentage_change(old_value: float, new_value: float) -> float:
        """Расчет процентного изменения"""
        if old_value == 0:
            return 0.0
        return ((new_value - old_value) / old_value) * 100
    
    @staticmethod
    def round_to_precision(value: float, precision: int = 8) -> float:
        """Округление до заданной точности"""
        return round(value, precision)
    
    @staticmethod
    def validate_symbol(symbol: str) -> bool:
        """Валидация торгового символа"""
        if not symbol or not isinstance(symbol, str):
            return False
        
        # Базовая валидация для Bybit символов
        if not symbol.endswith('USDT'):
            return False
        
        if len(symbol) < 5 or len(symbol) > 20:
            return False
        
        return True
    
    @staticmethod
    def format_volume(volume: float) -> str:
        """Форматирование объема для отображения"""
        if volume >= 1_000_000:
            return f"{volume / 1_000_000:.1f}M"
        elif volume >= 1_000:
            return f"{volume / 1_000:.1f}K"
        else:
            return f"{volume:.0f}"
    
    @staticmethod
    def format_price(price: float, precision: int = 8) -> str:
        """Форматирование цены для отображения"""
        if price >= 1:
            return f"${price:,.{min(precision, 4)}f}"
        else:
            return f"${price:.{precision}f}"
    
    @staticmethod
    async def retry_async(func, max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
        """Повторные попытки выполнения асинхронной функции"""
        last_exception = None
        
        for attempt in range(max_attempts):
            try:
                return await func()
            except Exception as e:
                last_exception = e
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delay * (backoff ** attempt))
                    logger.warning(f"Попытка {attempt + 1} неудачна, повторяем через {delay * (backoff ** attempt)}с: {e}")
        
        raise last_exception
    
    @staticmethod
    def chunk_list(lst: list, chunk_size: int) -> list:
        """Разбивка списка на части"""
        return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]
    
    @staticmethod
    def merge_dicts(*dicts) -> Dict:
        """Объединение словарей"""
        result = {}
        for d in dicts:
            if isinstance(d, dict):
                result.update(d)
        return result
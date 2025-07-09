import logging
import sys
from pathlib import Path
from typing import Optional
from cryptoscan.backand.settings import get_setting


class CoreLogger:
    """Централизованная система логирования"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._setup_logging()
            self._initialized = True
    
    def _setup_logging(self):
        """Настройка системы логирования"""
        log_level = get_setting('LOG_LEVEL', 'INFO')
        log_file = get_setting('LOG_FILE', 'cryptoscan.log')
        
        # Создаем директорию для логов если её нет
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Настройка форматирования
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Настройка корневого логгера
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))
        
        # Очищаем существующие обработчики
        root_logger.handlers.clear()
        
        # Консольный обработчик
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # Файловый обработчик
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"Не удалось создать файловый обработчик логов: {e}")
    
    def get_logger(self, name: str) -> logging.Logger:
        """Получение логгера для модуля"""
        return logging.getLogger(name)
    
    def set_level(self, level: str):
        """Изменение уровня логирования"""
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, level.upper()))
        
        # Обновляем настройку
        from settings import update_setting
        update_setting('LOG_LEVEL', level)


# Глобальный экземпляр логгера
logger_instance = CoreLogger()

def get_logger(name: str) -> logging.Logger:
    """Функция для получения логгера"""
    return logger_instance.get_logger(name)
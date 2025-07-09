import asyncio
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from typing import Optional, Dict, Any
from contextlib import contextmanager
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import DatabaseException
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class DatabaseConnection:
    """Управление подключениями к базе данных"""
    
    def __init__(self):
        self.connection_pool: Optional[ThreadedConnectionPool] = None
        self.connection: Optional[psycopg2.extensions.connection] = None
        self._is_initialized = False
    
    async def initialize(self):
        """Инициализация подключения к базе данных"""
        if self._is_initialized:
            return
        
        try:
            # Получаем настройки подключения
            db_config = self._get_db_config()
            
            # Создаем пул подключений
            self.connection_pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=20,
                **db_config
            )
            
            # Создаем основное подключение
            self.connection = self.connection_pool.getconn()
            self.connection.autocommit = True
            
            # Проверяем подключение
            await self._test_connection()
            
            self._is_initialized = True
            logger.info("✅ Подключение к базе данных установлено")
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к базе данных: {e}")
            raise DatabaseException(f"Не удалось подключиться к базе данных: {e}")
    
    def _get_db_config(self) -> Dict[str, Any]:
        """Получение конфигурации базы данных"""
        # Пробуем использовать DATABASE_URL
        database_url = get_setting('DATABASE_URL')
        if database_url and database_url != 'postgresql://user:password@localhost:5432/cryptoscan':
            return {'dsn': database_url}
        
        # Используем отдельные параметры
        return {
            'host': get_setting('DB_HOST', 'localhost'),
            'port': get_setting('DB_PORT', 5432),
            'database': get_setting('DB_NAME', 'cryptoscan'),
            'user': get_setting('DB_USER', 'user'),
            'password': get_setting('DB_PASSWORD', 'password'),
            'cursor_factory': RealDictCursor
        }
    
    async def _test_connection(self):
        """Тестирование подключения к базе данных"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            
            if not result:
                raise DatabaseException("Тест подключения не прошел")
                
        except Exception as e:
            raise DatabaseException(f"Ошибка тестирования подключения: {e}")
    
    @contextmanager
    def get_cursor(self):
        """Контекстный менеджер для получения курсора"""
        if not self._is_initialized:
            raise DatabaseException("База данных не инициализирована")
        
        cursor = None
        try:
            cursor = self.connection.cursor()
            yield cursor
        except Exception as e:
            if cursor:
                cursor.close()
            logger.error(f"Ошибка работы с курсором: {e}")
            raise DatabaseException(f"Ошибка работы с базой данных: {e}")
        finally:
            if cursor:
                cursor.close()
    
    @contextmanager
    def get_connection_from_pool(self):
        """Контекстный менеджер для получения подключения из пула"""
        if not self.connection_pool:
            raise DatabaseException("Пул подключений не инициализирован")
        
        conn = None
        try:
            conn = self.connection_pool.getconn()
            yield conn
        except Exception as e:
            logger.error(f"Ошибка работы с подключением из пула: {e}")
            raise DatabaseException(f"Ошибка работы с базой данных: {e}")
        finally:
            if conn:
                self.connection_pool.putconn(conn)
    
    async def execute_query(self, query: str, params: tuple = None) -> list:
        """Выполнение SELECT запроса"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка выполнения запроса: {e}")
            raise DatabaseException(f"Ошибка выполнения запроса: {e}")
    
    async def execute_command(self, command: str, params: tuple = None) -> int:
        """Выполнение INSERT/UPDATE/DELETE команды"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(command, params)
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Ошибка выполнения команды: {e}")
            raise DatabaseException(f"Ошибка выполнения команды: {e}")
    
    async def execute_command_with_return(self, command: str, params: tuple = None):
        """Выполнение команды с возвратом значения"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(command, params)
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Ошибка выполнения команды с возвратом: {e}")
            raise DatabaseException(f"Ошибка выполнения команды: {e}")
    
    def close(self):
        """Закрытие подключений"""
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
            
            if self.connection_pool:
                self.connection_pool.closeall()
                self.connection_pool = None
            
            self._is_initialized = False
            logger.info("🔌 Подключения к базе данных закрыты")
            
        except Exception as e:
            logger.error(f"Ошибка закрытия подключений: {e}")
    
    def is_connected(self) -> bool:
        """Проверка состояния подключения"""
        try:
            if not self.connection or self.connection.closed:
                return False
            
            # Быстрая проверка подключения
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True
            
        except Exception:
            return False
    
    async def reconnect(self):
        """Переподключение к базе данных"""
        logger.info("🔄 Переподключение к базе данных...")
        self.close()
        await self.initialize()
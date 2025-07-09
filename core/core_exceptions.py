"""
Пользовательские исключения для системы CryptoScan
"""


class CryptoScanException(Exception):
    """Базовое исключение для CryptoScan"""
    pass


class DatabaseException(CryptoScanException):
    """Исключения связанные с базой данных"""
    pass


class APIException(CryptoScanException):
    """Исключения связанные с API"""
    pass


class WebSocketException(CryptoScanException):
    """Исключения связанные с WebSocket"""
    pass


class AlertException(CryptoScanException):
    """Исключения связанные с алертами"""
    pass


class TimeSyncException(CryptoScanException):
    """Исключения связанные с синхронизацией времени"""
    pass


class TradingException(CryptoScanException):
    """Исключения связанные с торговлей"""
    pass


class ConfigurationException(CryptoScanException):
    """Исключения связанные с конфигурацией"""
    pass


class ValidationException(CryptoScanException):
    """Исключения связанные с валидацией данных"""
    pass


class NetworkException(CryptoScanException):
    """Исключения связанные с сетевыми операциями"""
    pass
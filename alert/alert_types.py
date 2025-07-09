from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


class AlertType(Enum):
    VOLUME_SPIKE = "volume_spike"
    CONSECUTIVE_LONG = "consecutive_long"
    PRIORITY = "priority"


class AlertStatus(Enum):
    PENDING = "pending"
    TRUE_SIGNAL = "true_signal"
    FALSE_SIGNAL = "false_signal"
    CLOSED = "closed"


@dataclass
class AlertData:
    """Структура данных алерта"""
    symbol: str
    alert_type: str
    price: float
    timestamp: int
    close_timestamp: Optional[int] = None
    is_closed: bool = False
    is_true_signal: Optional[bool] = None
    has_imbalance: bool = False
    imbalance_data: Optional[Dict] = None
    candle_data: Optional[Dict] = None
    order_book_snapshot: Optional[Dict] = None
    message: str = ""
    
    # Специфичные поля для разных типов алертов
    volume_ratio: Optional[float] = None
    current_volume_usdt: Optional[int] = None
    average_volume_usdt: Optional[int] = None
    consecutive_count: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь"""
        result = {
            'symbol': self.symbol,
            'alert_type': self.alert_type,
            'price': self.price,
            'timestamp': self.timestamp,
            'close_timestamp': self.close_timestamp,
            'is_closed': self.is_closed,
            'is_true_signal': self.is_true_signal,
            'has_imbalance': self.has_imbalance,
            'imbalance_data': self.imbalance_data,
            'candle_data': self.candle_data,
            'order_book_snapshot': self.order_book_snapshot,
            'message': self.message
        }
        
        # Добавляем специфичные поля если они есть
        if self.volume_ratio is not None:
            result['volume_ratio'] = self.volume_ratio
        if self.current_volume_usdt is not None:
            result['current_volume_usdt'] = self.current_volume_usdt
        if self.average_volume_usdt is not None:
            result['average_volume_usdt'] = self.average_volume_usdt
        if self.consecutive_count is not None:
            result['consecutive_count'] = self.consecutive_count
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AlertData':
        """Создание из словаря"""
        return cls(
            symbol=data['symbol'],
            alert_type=data['alert_type'],
            price=data['price'],
            timestamp=data['timestamp'],
            close_timestamp=data.get('close_timestamp'),
            is_closed=data.get('is_closed', False),
            is_true_signal=data.get('is_true_signal'),
            has_imbalance=data.get('has_imbalance', False),
            imbalance_data=data.get('imbalance_data'),
            candle_data=data.get('candle_data'),
            order_book_snapshot=data.get('order_book_snapshot'),
            message=data.get('message', ''),
            volume_ratio=data.get('volume_ratio'),
            current_volume_usdt=data.get('current_volume_usdt'),
            average_volume_usdt=data.get('average_volume_usdt'),
            consecutive_count=data.get('consecutive_count')
        )


@dataclass
class ImbalanceData:
    """Данные об имбалансе"""
    type: str  # 'fair_value_gap', 'order_block', 'breaker_block'
    direction: str  # 'bullish', 'bearish'
    strength: float
    top: float
    bottom: float
    timestamp: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'direction': self.direction,
            'strength': self.strength,
            'top': self.top,
            'bottom': self.bottom,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImbalanceData':
        return cls(
            type=data['type'],
            direction=data['direction'],
            strength=data['strength'],
            top=data['top'],
            bottom=data['bottom'],
            timestamp=data['timestamp']
        )


@dataclass
class CandleData:
    """Данные свечи для алерта"""
    open: float
    high: float
    low: float
    close: float
    volume: float
    alert_level: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'alert_level': self.alert_level
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CandleData':
        return cls(
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            volume=data['volume'],
            alert_level=data.get('alert_level')
        )


@dataclass
class OrderBookSnapshot:
    """Снимок стакана заявок"""
    bids: list  # [[price, quantity], ...]
    asks: list  # [[price, quantity], ...]
    timestamp: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'bids': self.bids,
            'asks': self.asks,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OrderBookSnapshot':
        return cls(
            bids=data['bids'],
            asks=data['asks'],
            timestamp=data['timestamp']
        )
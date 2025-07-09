from typing import Dict, Optional, List
from datetime import datetime, timezone
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class AlertValidators:
    """Валидаторы для алертов"""
    
    def __init__(self):
        self.min_volume_usdt = get_setting('MIN_VOLUME_USDT', 1000)
        self.volume_multiplier = get_setting('VOLUME_MULTIPLIER', 2.0)
        self.consecutive_long_count = get_setting('CONSECUTIVE_LONG_COUNT', 5)
        self.alert_grouping_minutes = get_setting('ALERT_GROUPING_MINUTES', 5)
    
    def validate_volume_alert(self, symbol: str, kline_data: Dict, 
                            historical_volumes: List[float], 
                            last_alert_timestamp: Optional[int] = None) -> Dict:
        """Валидация алерта по объему"""
        try:
            # Проверяем, является ли свеча LONG
            is_long = float(kline_data['close']) > float(kline_data['open'])
            if not is_long:
                return {'valid': False, 'reason': 'Свеча не является LONG'}
            
            # Рассчитываем объем в USDT
            current_volume_usdt = float(kline_data['volume']) * float(kline_data['close'])
            
            # Проверяем минимальный объем
            if current_volume_usdt < self.min_volume_usdt:
                return {
                    'valid': False, 
                    'reason': f'Объем {current_volume_usdt:.0f} меньше минимального {self.min_volume_usdt}'
                }
            
            # Проверяем кулдаун
            if last_alert_timestamp:
                current_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
                cooldown_period_ms = self.alert_grouping_minutes * 60 * 1000
                if (current_timestamp - last_alert_timestamp) < cooldown_period_ms:
                    return {
                        'valid': False,
                        'reason': f'Кулдаун не истек ({self.alert_grouping_minutes} мин)'
                    }
            
            # Проверяем достаточность исторических данных
            if len(historical_volumes) < 10:
                return {
                    'valid': False,
                    'reason': f'Недостаточно исторических данных: {len(historical_volumes)}'
                }
            
            # Рассчитываем средний объем и коэффициент
            average_volume = sum(historical_volumes) / len(historical_volumes)
            volume_ratio = current_volume_usdt / average_volume if average_volume > 0 else 0
            
            # Проверяем превышение объема
            if volume_ratio < self.volume_multiplier:
                return {
                    'valid': False,
                    'reason': f'Коэффициент объема {volume_ratio:.2f} меньше требуемого {self.volume_multiplier}'
                }
            
            return {
                'valid': True,
                'current_volume_usdt': int(current_volume_usdt),
                'average_volume_usdt': int(average_volume),
                'volume_ratio': round(volume_ratio, 2)
            }
            
        except Exception as e:
            logger.error(f"Ошибка валидации алерта по объему для {symbol}: {e}")
            return {'valid': False, 'reason': f'Ошибка валидации: {e}'}
    
    def validate_consecutive_alert(self, symbol: str, recent_candles: List[Dict]) -> Dict:
        """Валидация алерта по подряд идущим LONG свечам"""
        try:
            if len(recent_candles) < self.consecutive_long_count:
                return {
                    'valid': False,
                    'reason': f'Недостаточно данных: {len(recent_candles)} < {self.consecutive_long_count}'
                }
            
            # Считаем последовательные LONG свечи с конца
            consecutive_count = 0
            for candle in reversed(recent_candles):
                if candle.get('is_long', False) and candle.get('is_closed', False):
                    consecutive_count += 1
                else:
                    break
            
            # Проверяем достижение нужного количества
            if consecutive_count < self.consecutive_long_count:
                return {
                    'valid': False,
                    'reason': f'Недостаточно последовательных LONG свечей: {consecutive_count} < {self.consecutive_long_count}'
                }
            
            return {
                'valid': True,
                'consecutive_count': consecutive_count
            }
            
        except Exception as e:
            logger.error(f"Ошибка валидации алерта по последовательности для {symbol}: {e}")
            return {'valid': False, 'reason': f'Ошибка валидации: {e}'}
    
    def validate_priority_alert(self, symbol: str, volume_alert: Optional[Dict], 
                              consecutive_alert: Optional[Dict], 
                              recent_volume_alert: bool = False) -> Dict:
        """Валидация приоритетного алерта"""
        try:
            # Приоритетный сигнал требует наличия алерта по последовательности
            if not consecutive_alert or not consecutive_alert.get('valid'):
                return {
                    'valid': False,
                    'reason': 'Нет валидного алерта по последовательности'
                }
            
            # И наличия объемного алерта (текущего или недавнего)
            has_volume_signal = (
                (volume_alert and volume_alert.get('valid')) or 
                recent_volume_alert
            )
            
            if not has_volume_signal:
                return {
                    'valid': False,
                    'reason': 'Нет объемного сигнала'
                }
            
            return {
                'valid': True,
                'consecutive_count': consecutive_alert.get('consecutive_count', 0),
                'volume_data': volume_alert if volume_alert and volume_alert.get('valid') else None
            }
            
        except Exception as e:
            logger.error(f"Ошибка валидации приоритетного алерта для {symbol}: {e}")
            return {'valid': False, 'reason': f'Ошибка валидации: {e}'}
    
    def validate_symbol(self, symbol: str) -> bool:
        """Валидация торгового символа"""
        if not symbol or not isinstance(symbol, str):
            return False
        
        # Базовая валидация для Bybit символов
        if not symbol.endswith('USDT'):
            return False
        
        if len(symbol) < 5 or len(symbol) > 20:
            return False
        
        return True
    
    def validate_kline_data(self, kline_data: Dict) -> Dict:
        """Валидация данных свечи"""
        try:
            required_fields = ['start', 'end', 'open', 'high', 'low', 'close', 'volume']
            
            for field in required_fields:
                if field not in kline_data:
                    return {'valid': False, 'reason': f'Отсутствует поле {field}'}
            
            # Проверяем числовые значения
            try:
                open_price = float(kline_data['open'])
                high_price = float(kline_data['high'])
                low_price = float(kline_data['low'])
                close_price = float(kline_data['close'])
                volume = float(kline_data['volume'])
            except (ValueError, TypeError):
                return {'valid': False, 'reason': 'Некорректные числовые значения'}
            
            # Проверяем логику цен
            if not (low_price <= open_price <= high_price and low_price <= close_price <= high_price):
                return {'valid': False, 'reason': 'Некорректные соотношения цен'}
            
            # Проверяем положительность объема
            if volume < 0:
                return {'valid': False, 'reason': 'Отрицательный объем'}
            
            # Проверяем временные метки
            start_time = int(kline_data['start'])
            end_time = int(kline_data['end'])
            
            if start_time >= end_time:
                return {'valid': False, 'reason': 'Некорректные временные метки'}
            
            return {'valid': True}
            
        except Exception as e:
            logger.error(f"Ошибка валидации данных свечи: {e}")
            return {'valid': False, 'reason': f'Ошибка валидации: {e}'}
    
    def validate_imbalance_data(self, imbalance_data: Dict) -> bool:
        """Валидация данных имбаланса"""
        try:
            if not isinstance(imbalance_data, dict):
                return False
            
            required_fields = ['type', 'direction', 'strength', 'top', 'bottom', 'timestamp']
            
            for field in required_fields:
                if field not in imbalance_data:
                    return False
            
            # Проверяем типы
            valid_types = ['fair_value_gap', 'order_block', 'breaker_block']
            if imbalance_data['type'] not in valid_types:
                return False
            
            valid_directions = ['bullish', 'bearish']
            if imbalance_data['direction'] not in valid_directions:
                return False
            
            # Проверяем числовые значения
            try:
                strength = float(imbalance_data['strength'])
                top = float(imbalance_data['top'])
                bottom = float(imbalance_data['bottom'])
                timestamp = int(imbalance_data['timestamp'])
            except (ValueError, TypeError):
                return False
            
            # Проверяем логику
            if strength <= 0 or top <= bottom or timestamp <= 0:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка валидации данных имбаланса: {e}")
            return False
    
    def update_settings(self, new_settings: Dict):
        """Обновление настроек валидаторов"""
        if 'MIN_VOLUME_USDT' in new_settings:
            self.min_volume_usdt = new_settings['MIN_VOLUME_USDT']
        
        if 'VOLUME_MULTIPLIER' in new_settings:
            self.volume_multiplier = new_settings['VOLUME_MULTIPLIER']
        
        if 'CONSECUTIVE_LONG_COUNT' in new_settings:
            self.consecutive_long_count = new_settings['CONSECUTIVE_LONG_COUNT']
        
        if 'ALERT_GROUPING_MINUTES' in new_settings:
            self.alert_grouping_minutes = new_settings['ALERT_GROUPING_MINUTES']
        
        logger.info("⚙️ Настройки валидаторов алертов обновлены")
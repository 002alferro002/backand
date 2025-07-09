from typing import Dict, Optional, List
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class ImbalanceAnalyzer:
    """Анализатор имбалансов на основе концепций Smart Money"""

    def __init__(self):
        self.min_gap_percentage = get_setting('MIN_GAP_PERCENTAGE', 0.1)
        self.min_strength = get_setting('MIN_STRENGTH', 0.5)
        self.fair_value_gap_enabled = get_setting('FAIR_VALUE_GAP_ENABLED', True)
        self.order_block_enabled = get_setting('ORDER_BLOCK_ENABLED', True)
        self.breaker_block_enabled = get_setting('BREAKER_BLOCK_ENABLED', True)

    def analyze_fair_value_gap(self, candles: List[Dict]) -> Optional[Dict]:
        """Анализ Fair Value Gap"""
        if not self.fair_value_gap_enabled or len(candles) < 3:
            return None

        try:
            # Берем последние 3 свечи
            prev_candle = candles[-3]
            current_candle = candles[-2]
            next_candle = candles[-1]

            # Bullish FVG: предыдущая свеча low > следующая свеча high
            if prev_candle['low'] > next_candle['high'] and current_candle['is_long']:
                gap_size = (prev_candle['low'] - next_candle['high']) / next_candle['high'] * 100
                if gap_size >= self.min_gap_percentage:
                    return {
                        'type': 'fair_value_gap',
                        'direction': 'bullish',
                        'strength': gap_size,
                        'top': prev_candle['low'],
                        'bottom': next_candle['high'],
                        'timestamp': current_candle['timestamp']
                    }

            # Bearish FVG: предыдущая свеча high < следующая свеча low
            if prev_candle['high'] < next_candle['low'] and not current_candle['is_long']:
                gap_size = (next_candle['low'] - prev_candle['high']) / prev_candle['high'] * 100
                if gap_size >= self.min_gap_percentage:
                    return {
                        'type': 'fair_value_gap',
                        'direction': 'bearish',
                        'strength': gap_size,
                        'top': next_candle['low'],
                        'bottom': prev_candle['high'],
                        'timestamp': current_candle['timestamp']
                    }

            return None

        except Exception as e:
            logger.error(f"Ошибка анализа Fair Value Gap: {e}")
            return None

    def analyze_order_block(self, candles: List[Dict]) -> Optional[Dict]:
        """Анализ Order Block"""
        if not self.order_block_enabled or len(candles) < 10:
            return None

        try:
            current_candle = candles[-1]
            window = candles[-10:-1]  # Последние 9 свечей перед текущей

            # Bullish Order Block: последняя медвежья свеча перед сильным восходящим движением
            last_bearish = None
            for candle in reversed(window):
                if not candle['is_long']:
                    last_bearish = candle
                    break

            if last_bearish and current_candle['is_long']:
                price_move = (current_candle['close'] - last_bearish['high']) / last_bearish['high'] * 100
                if price_move >= 2.0:  # Движение минимум на 2%
                    return {
                        'type': 'order_block',
                        'direction': 'bullish',
                        'strength': price_move,
                        'top': last_bearish['high'],
                        'bottom': last_bearish['low'],
                        'timestamp': last_bearish['timestamp']
                    }

            # Bearish Order Block: последняя бычья свеча перед сильным нисходящим движением
            last_bullish = None
            for candle in reversed(window):
                if candle['is_long']:
                    last_bullish = candle
                    break

            if last_bullish and not current_candle['is_long']:
                price_move = (last_bullish['low'] - current_candle['close']) / last_bullish['low'] * 100
                if price_move >= 2.0:  # Движение минимум на 2%
                    return {
                        'type': 'order_block',
                        'direction': 'bearish',
                        'strength': price_move,
                        'top': last_bullish['high'],
                        'bottom': last_bullish['low'],
                        'timestamp': last_bullish['timestamp']
                    }

            return None

        except Exception as e:
            logger.error(f"Ошибка анализа Order Block: {e}")
            return None

    def analyze_breaker_block(self, candles: List[Dict]) -> Optional[Dict]:
        """Анализ Breaker Block (пробитый Order Block)"""
        if not self.breaker_block_enabled or len(candles) < 15:
            return None

        try:
            # Ищем пробитые уровни поддержки/сопротивления
            current_candle = candles[-1]
            window = candles[-15:-1]

            # Находим значимые уровни
            highs = [c['high'] for c in window]
            lows = [c['low'] for c in window]

            max_high = max(highs)
            min_low = min(lows)

            # Bullish Breaker: пробитие вниз с последующим возвратом вверх
            if current_candle['close'] > max_high and current_candle['is_long']:
                strength = (current_candle['close'] - max_high) / max_high * 100
                if strength >= 1.0:
                    return {
                        'type': 'breaker_block',
                        'direction': 'bullish',
                        'strength': strength,
                        'top': max_high,
                        'bottom': min_low,
                        'timestamp': current_candle['timestamp']
                    }

            # Bearish Breaker: пробитие вверх с последующим возвратом вниз
            if current_candle['close'] < min_low and not current_candle['is_long']:
                strength = (min_low - current_candle['close']) / min_low * 100
                if strength >= 1.0:
                    return {
                        'type': 'breaker_block',
                        'direction': 'bearish',
                        'strength': strength,
                        'top': max_high,
                        'bottom': min_low,
                        'timestamp': current_candle['timestamp']
                    }

            return None

        except Exception as e:
            logger.error(f"Ошибка анализа Breaker Block: {e}")
            return None

    def analyze_all_imbalances(self, candles: List[Dict]) -> Optional[Dict]:
        """Анализ всех типов имбалансов"""
        try:
            # Проверяем Fair Value Gap
            if self.fair_value_gap_enabled:
                fvg = self.analyze_fair_value_gap(candles)
                if fvg and fvg['strength'] >= self.min_strength:
                    return fvg

            # Проверяем Order Block
            if self.order_block_enabled:
                ob = self.analyze_order_block(candles)
                if ob and ob['strength'] >= self.min_strength:
                    return ob

            # Проверяем Breaker Block
            if self.breaker_block_enabled:
                bb = self.analyze_breaker_block(candles)
                if bb and bb['strength'] >= self.min_strength:
                    return bb

            return None

        except Exception as e:
            logger.error(f"Ошибка анализа имбалансов: {e}")
            return None

    def get_imbalance_summary(self, candles: List[Dict]) -> Dict:
        """Получение сводки по всем имбалансам"""
        try:
            summary = {
                'has_imbalance': False,
                'imbalance_count': 0,
                'strongest_imbalance': None,
                'imbalances': []
            }

            # Анализируем все типы
            imbalances = []

            if self.fair_value_gap_enabled:
                fvg = self.analyze_fair_value_gap(candles)
                if fvg:
                    imbalances.append(fvg)

            if self.order_block_enabled:
                ob = self.analyze_order_block(candles)
                if ob:
                    imbalances.append(ob)

            if self.breaker_block_enabled:
                bb = self.analyze_breaker_block(candles)
                if bb:
                    imbalances.append(bb)

            # Фильтруем по минимальной силе
            valid_imbalances = [
                imb for imb in imbalances 
                if imb['strength'] >= self.min_strength
            ]

            if valid_imbalances:
                summary['has_imbalance'] = True
                summary['imbalance_count'] = len(valid_imbalances)
                summary['imbalances'] = valid_imbalances
                
                # Находим самый сильный имбаланс
                strongest = max(valid_imbalances, key=lambda x: x['strength'])
                summary['strongest_imbalance'] = strongest

            return summary

        except Exception as e:
            logger.error(f"Ошибка получения сводки имбалансов: {e}")
            return {
                'has_imbalance': False,
                'imbalance_count': 0,
                'strongest_imbalance': None,
                'imbalances': []
            }

    def update_settings(self, new_settings: Dict):
        """Обновление настроек анализатора"""
        if 'MIN_GAP_PERCENTAGE' in new_settings:
            self.min_gap_percentage = new_settings['MIN_GAP_PERCENTAGE']
        
        if 'MIN_STRENGTH' in new_settings:
            self.min_strength = new_settings['MIN_STRENGTH']
        
        if 'FAIR_VALUE_GAP_ENABLED' in new_settings:
            self.fair_value_gap_enabled = new_settings['FAIR_VALUE_GAP_ENABLED']
        
        if 'ORDER_BLOCK_ENABLED' in new_settings:
            self.order_block_enabled = new_settings['ORDER_BLOCK_ENABLED']
        
        if 'BREAKER_BLOCK_ENABLED' in new_settings:
            self.breaker_block_enabled = new_settings['BREAKER_BLOCK_ENABLED']
        
        logger.info("⚙️ Настройки анализатора имбалансов обновлены")

    def get_settings(self) -> Dict:
        """Получение текущих настроек"""
        return {
            'min_gap_percentage': self.min_gap_percentage,
            'min_strength': self.min_strength,
            'fair_value_gap_enabled': self.fair_value_gap_enabled,
            'order_block_enabled': self.order_block_enabled,
            'breaker_block_enabled': self.breaker_block_enabled
        }
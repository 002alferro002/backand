import asyncio
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import AlertException
from cryptoscan.backand.alert.alert_types import AlertType, AlertData, AlertStatus
from cryptoscan.backand.alert.alert_validators import AlertValidators
from cryptoscan.backand.alert.alert_imbalance import ImbalanceAnalyzer
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class AlertManager:
    """Менеджер алертов"""
    
    def __init__(self, db_queries, telegram_bot=None, connection_manager=None, time_manager=None):
        self.db_queries = db_queries
        self.telegram_bot = telegram_bot
        self.connection_manager = connection_manager
        self.time_manager = time_manager

        # Настройки из конфигурации
        self.settings = {
            'volume_alerts_enabled': get_setting('VOLUME_ALERTS_ENABLED', True),
            'consecutive_alerts_enabled': get_setting('CONSECUTIVE_ALERTS_ENABLED', True),
            'priority_alerts_enabled': get_setting('PRIORITY_ALERTS_ENABLED', True),
            'analysis_hours': get_setting('ANALYSIS_HOURS', 1),
            'offset_minutes': get_setting('OFFSET_MINUTES', 0),
            'volume_multiplier': get_setting('VOLUME_MULTIPLIER', 2.0),
            'min_volume_usdt': get_setting('MIN_VOLUME_USDT', 1000),
            'consecutive_long_count': get_setting('CONSECUTIVE_LONG_COUNT', 5),
            'alert_grouping_minutes': get_setting('ALERT_GROUPING_MINUTES', 5),
            'data_retention_hours': get_setting('DATA_RETENTION_HOURS', 2),
            'update_interval_seconds': get_setting('UPDATE_INTERVAL_SECONDS', 1),
            'notification_enabled': get_setting('NOTIFICATION_ENABLED', True),
            'volume_type': get_setting('VOLUME_TYPE', 'long'),
            'orderbook_enabled': get_setting('ORDERBOOK_ENABLED', False),
            'orderbook_snapshot_on_alert': get_setting('ORDERBOOK_SNAPSHOT_ON_ALERT', False),
            'imbalance_enabled': get_setting('IMBALANCE_ENABLED', True),
            'fair_value_gap_enabled': get_setting('FAIR_VALUE_GAP_ENABLED', True),
            'order_block_enabled': get_setting('ORDER_BLOCK_ENABLED', True),
            'breaker_block_enabled': get_setting('BREAKER_BLOCK_ENABLED', True),
            'pairs_check_interval_minutes': get_setting('PAIRS_CHECK_INTERVAL_MINUTES', 30)
        }

        # Инициализация компонентов
        self.validators = AlertValidators()
        self.imbalance_analyzer = ImbalanceAnalyzer()

        # Кэш для отслеживания состояния алертов (timestamp в миллисекундах UTC)
        self.alert_cooldowns = {}  # symbol -> last alert timestamp_ms
        
        # Счетчики подряд идущих LONG свечей
        self.consecutive_long_counters = {}  # symbol -> count
        
        # Кэш предварительных сигналов
        self.preliminary_signals = {}  # symbol -> signal_data

        logger.info(f"AlertManager инициализирован с синхронизацией времени UTC: {self.time_manager is not None}")

    def _get_current_timestamp_ms(self) -> int:
        """Получить текущий UTC timestamp в миллисекундах"""
        if self.time_manager:
            timestamp = self.time_manager.get_utc_timestamp_ms()
            logger.debug(f"⏰ Используется синхронизированное UTC время: {timestamp}")
            return timestamp
        else:
            # Fallback на локальное UTC время
            timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
            logger.debug(f"⏰ Используется локальное UTC время (fallback): {timestamp}")
            return timestamp

    async def process_kline_data(self, symbol: str, kline_data: Dict) -> List[Dict]:
        """Обработка данных свечи и генерация алертов"""
        alerts = []

        try:
            # Проверяем предварительный сигнал для незакрытых свечей
            if not kline_data.get('confirm', False):
                preliminary_alert = await self._check_preliminary_volume_signal(symbol, kline_data)
                if preliminary_alert:
                    alerts.append(preliminary_alert)
                    # Сохраняем предварительный сигнал
                    self.preliminary_signals[symbol] = preliminary_alert
                return alerts
            
            # Проверка закрытия свечи
            if self.time_manager and hasattr(self.time_manager, 'is_candle_closed'):
                is_closed = self.time_manager.is_candle_closed(kline_data)
                logger.debug(f"🕐 Проверка закрытия свечи {symbol} через time_manager: {is_closed}")
            else:
                is_closed = kline_data.get('confirm', False)
                logger.debug(f"🕐 Проверка закрытия свечи {symbol} через confirm: {is_closed}")

            # Обрабатываем алерты только для закрытых свечей
            if is_closed:
                logger.debug(f"📊 Обработка закрытой свечи {symbol}")
                alerts = await self._process_closed_candle(symbol, kline_data)

            # Отправляем алерты
            for alert in alerts:
                await self._send_alert(alert)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки данных свечи для {symbol}: {e}")

        return alerts

    async def _process_closed_candle(self, symbol: str, kline_data: Dict) -> List[Dict]:
        """Обработка закрытой свечи - генерация алертов"""
        alerts = []

        try:
            # Обновляем счетчик подряд идущих LONG свечей
            await self._update_consecutive_long_counter(symbol, kline_data)
            
            # Проверяем финальный объемный сигнал (если был предварительный)
            if symbol in self.preliminary_signals:
                final_alert = await self._check_final_volume_signal(symbol, kline_data)
                if final_alert:
                    alerts.append(final_alert)
                # Удаляем предварительный сигнал
                del self.preliminary_signals[symbol]
            
            # Проверяем алерт по объему
            if self.settings['volume_alerts_enabled']:
                volume_alert = await self._check_volume_alert(symbol, kline_data)
                if volume_alert:
                    alerts.append(volume_alert)

            # Проверяем последовательные LONG свечи
            if self.settings['consecutive_alerts_enabled']:
                consecutive_alert = await self._check_consecutive_long_alert(symbol, kline_data)
                if consecutive_alert:
                    alerts.append(consecutive_alert)

            # Проверяем приоритетные сигналы
            if self.settings['priority_alerts_enabled']:
                priority_alert = await self._check_priority_signal(symbol, alerts)
                if priority_alert:
                    alerts.append(priority_alert)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки закрытой свечи для {symbol}: {e}")

        return alerts

    async def _check_volume_alert(self, symbol: str, kline_data: Dict) -> Optional[Dict]:
        """Проверка алерта по превышению объема"""
        try:
            # Получаем исторические объемы
            historical_volumes = await self.db_queries.get_historical_long_volumes(
                symbol,
                self.settings['analysis_hours'],
                offset_minutes=self.settings['offset_minutes'],
                volume_type=self.settings['volume_type']
            )

            # Валидация алерта
            last_alert_timestamp = self.alert_cooldowns.get(symbol)
            validation_result = self.validators.validate_volume_alert(
                symbol, kline_data, historical_volumes, last_alert_timestamp
            )

            if not validation_result['valid']:
                logger.debug(f"Алерт по объему для {symbol} не прошел валидацию: {validation_result['reason']}")
                return None

            # Создаем данные алерта
            current_timestamp_ms = self._get_current_timestamp_ms()
            current_price = float(kline_data['close'])

            # Создаем данные свечи для алерта
            candle_data = {
                'open': float(kline_data['open']),
                'high': float(kline_data['high']),
                'low': float(kline_data['low']),
                'close': current_price,
                'volume': float(kline_data['volume']),
                'alert_level': current_price
            }

            # Анализируем имбаланс
            imbalance_data = None
            has_imbalance = False
            if self.settings.get('imbalance_enabled', False):
                imbalance_data = await self._analyze_imbalance(symbol)
                has_imbalance = imbalance_data is not None

            # Получаем снимок стакана, если включено
            order_book_snapshot = None
            if self.settings.get('orderbook_snapshot_on_alert', False):
                order_book_snapshot = await self._get_order_book_snapshot(symbol)

            alert_data = {
                'symbol': symbol,
                'alert_type': AlertType.VOLUME_SPIKE.value,
                'price': current_price,
                'volume_ratio': validation_result['volume_ratio'],
                'current_volume_usdt': validation_result['current_volume_usdt'],
                'average_volume_usdt': validation_result['average_volume_usdt'],
                'timestamp': current_timestamp_ms,
                'close_timestamp': current_timestamp_ms,
                'is_closed': True,
                'is_true_signal': True,
                'has_imbalance': has_imbalance,
                'imbalance_data': imbalance_data,
                'candle_data': candle_data,
                'order_book_snapshot': order_book_snapshot,
                'message': f"Объем превышен в {validation_result['volume_ratio']}x раз (истинный сигнал)"
            }

            # Обновляем кулдаун
            self.alert_cooldowns[symbol] = current_timestamp_ms

            logger.info(f"✅ Создан алерт по объему для {symbol}: {validation_result['volume_ratio']}x")
            return alert_data

        except Exception as e:
            logger.error(f"❌ Ошибка проверки алерта по объему для {symbol}: {e}")
            return None

    async def _check_preliminary_volume_signal(self, symbol: str, kline_data: Dict) -> Optional[Dict]:
        """Проверка предварительного сигнала по объему для незакрытой свечи"""
        try:
            # Проверяем, является ли текущая свеча LONG
            current_price = float(kline_data['close'])
            open_price = float(kline_data['open'])
            
            if current_price <= open_price:
                return None  # Свеча не LONG
            
            # Рассчитываем объем в USDT
            current_volume_usdt = float(kline_data['volume']) * current_price
            
            # Проверяем минимальный объем
            if current_volume_usdt < self.settings['min_volume_usdt']:
                return None
            
            # Получаем исторические объемы
            historical_volumes = await self.db_queries.get_historical_long_volumes(
                symbol,
                self.settings['analysis_hours'],
                offset_minutes=self.settings['offset_minutes'],
                volume_type=self.settings['volume_type']
            )
            
            if len(historical_volumes) < 10:
                return None
            
            # Рассчитываем средний объем и коэффициент
            average_volume = sum(historical_volumes) / len(historical_volumes)
            volume_ratio = current_volume_usdt / average_volume if average_volume > 0 else 0
            
            # Проверяем превышение объема
            if volume_ratio < self.settings['volume_multiplier']:
                return None
            
            current_timestamp_ms = self._get_current_timestamp_ms()
            
            # Создаем данные свечи для алерта
            candle_data = {
                'open': open_price,
                'high': float(kline_data['high']),
                'low': float(kline_data['low']),
                'close': current_price,
                'volume': float(kline_data['volume']),
                'alert_level': current_price
            }
            
            alert_data = {
                'symbol': symbol,
                'alert_type': 'preliminary_volume_spike',
                'price': current_price,
                'volume_ratio': round(volume_ratio, 2),
                'current_volume_usdt': int(current_volume_usdt),
                'average_volume_usdt': int(average_volume),
                'timestamp': current_timestamp_ms,
                'is_closed': False,
                'is_preliminary': True,
                'candle_data': candle_data,
                'message': f"Предварительный сигнал: объем превышен в {volume_ratio:.2f}x раз"
            }
            
            logger.info(f"⚡ Предварительный сигнал по объему для {symbol}: {volume_ratio:.2f}x")
            return alert_data
            
        except Exception as e:
            logger.error(f"❌ Ошибка проверки предварительного сигнала для {symbol}: {e}")
            return None
    
    async def _check_final_volume_signal(self, symbol: str, kline_data: Dict) -> Optional[Dict]:
        """Проверка финального сигнала по объему для закрытой свечи"""
        try:
            preliminary_signal = self.preliminary_signals.get(symbol)
            if not preliminary_signal:
                return None
            
            # Проверяем, закрылась ли свеча в LONG
            close_price = float(kline_data['close'])
            open_price = float(kline_data['open'])
            is_true_long = close_price > open_price
            
            current_timestamp_ms = self._get_current_timestamp_ms()
            
            # Обновляем данные свечи
            candle_data = {
                'open': open_price,
                'high': float(kline_data['high']),
                'low': float(kline_data['low']),
                'close': close_price,
                'volume': float(kline_data['volume']),
                'alert_level': close_price
            }
            
            alert_data = {
                'symbol': symbol,
                'alert_type': 'final_volume_spike',
                'price': close_price,
                'volume_ratio': preliminary_signal['volume_ratio'],
                'current_volume_usdt': preliminary_signal['current_volume_usdt'],
                'average_volume_usdt': preliminary_signal['average_volume_usdt'],
                'timestamp': current_timestamp_ms,
                'close_timestamp': current_timestamp_ms,
                'is_closed': True,
                'is_true_signal': is_true_long,
                'is_preliminary': False,
                'candle_data': candle_data,
                'preliminary_timestamp': preliminary_signal['timestamp'],
                'message': f"Финальный сигнал: {'истинный' if is_true_long else 'ложный'} LONG (объем {preliminary_signal['volume_ratio']}x)"
            }
            
            logger.info(f"✅ Финальный сигнал для {symbol}: {'истинный' if is_true_long else 'ложный'} LONG")
            return alert_data
            
        except Exception as e:
            logger.error(f"❌ Ошибка проверки финального сигнала для {symbol}: {e}")
            return None
    
    async def _update_consecutive_long_counter(self, symbol: str, kline_data: Dict):
        """Обновление счетчика подряд идущих LONG свечей"""
        try:
            close_price = float(kline_data['close'])
            open_price = float(kline_data['open'])
            is_long = close_price > open_price
            
            if is_long:
                # Увеличиваем счетчик
                self.consecutive_long_counters[symbol] = self.consecutive_long_counters.get(symbol, 0) + 1
                logger.debug(f"📈 {symbol}: подряд LONG свечей = {self.consecutive_long_counters[symbol]}")
            else:
                # Сбрасываем счетчик
                if symbol in self.consecutive_long_counters:
                    logger.debug(f"📉 {symbol}: счетчик LONG свечей сброшен (была SHORT)")
                    del self.consecutive_long_counters[symbol]
                    
        except Exception as e:
            logger.error(f"❌ Ошибка обновления счетчика LONG свечей для {symbol}: {e}")

    async def _check_consecutive_long_alert(self, symbol: str, kline_data: Dict) -> Optional[Dict]:
        """Проверка алерта по подряд идущим LONG свечам"""
        try:
            # Используем счетчик вместо проверки базы данных
            consecutive_count = self.consecutive_long_counters.get(symbol, 0)
            
            if consecutive_count < self.settings['consecutive_long_count']:
                return None
            
            # Проверяем кулдаун для consecutive алертов
            last_alert_key = f"{symbol}_consecutive"
            last_alert_timestamp = self.alert_cooldowns.get(last_alert_key)
            current_timestamp_ms = self._get_current_timestamp_ms()
            
            if last_alert_timestamp:
                cooldown_period_ms = self.settings['alert_grouping_minutes'] * 60 * 1000
                if (current_timestamp_ms - last_alert_timestamp) < cooldown_period_ms:
                    # Обновляем только счетчик в существующем алерте
                    return None

            current_price = float(kline_data['close'])

            # Создаем данные свечи
            candle_data = {
                'open': float(kline_data['open']),
                'high': float(kline_data['high']),
                'low': float(kline_data['low']),
                'close': current_price,
                'volume': float(kline_data['volume'])
            }

            # Анализируем имбаланс
            imbalance_data = await self._analyze_imbalance(symbol)
            has_imbalance = imbalance_data is not None

            alert_data = {
                'symbol': symbol,
                'alert_type': AlertType.CONSECUTIVE_LONG.value,
                'price': current_price,
                'consecutive_count': consecutive_count,
                'timestamp': current_timestamp_ms,
                'close_timestamp': current_timestamp_ms,
                'is_closed': True,
                'has_imbalance': has_imbalance,
                'imbalance_data': imbalance_data,
                'candle_data': candle_data,
                'message': f"{consecutive_count} подряд идущих LONG свечей (закрытых)"
            }

            # Обновляем кулдаун
            self.alert_cooldowns[last_alert_key] = current_timestamp_ms
            
            logger.info(f"✅ Алерт по последовательности для {symbol}: {consecutive_count} LONG свечей")
            return alert_data

        except Exception as e:
            logger.error(f"❌ Ошибка проверки последовательных LONG свечей для {symbol}: {e}")
            return None

    async def _check_priority_signal(self, symbol: str, current_alerts: List[Dict]) -> Optional[Dict]:
        """Проверка приоритетного сигнала"""
        try:
            # Находим алерты в текущем списке
            volume_alert = None
            consecutive_alert = None

            for alert in current_alerts:
                if alert['alert_type'] in [AlertType.VOLUME_SPIKE.value, 'final_volume_spike']:
                    volume_alert = alert
                elif alert['alert_type'] == AlertType.CONSECUTIVE_LONG.value:
                    consecutive_alert = alert

            # Проверяем недавний объемный алерт в диапазоне consecutive свечей
            recent_volume_alert = False
            if consecutive_alert:
                recent_volume_alert = await self._check_recent_volume_alert_in_range(
                    symbol, consecutive_alert['consecutive_count']
                )

            # Валидация приоритетного алерта
            validation_result = self.validators.validate_priority_alert(
                symbol, 
                {'valid': volume_alert is not None} if volume_alert else None,
                {'valid': consecutive_alert is not None, 'consecutive_count': consecutive_alert.get('consecutive_count', 0)} if consecutive_alert else None,
                recent_volume_alert
            )

            if not validation_result['valid']:
                logger.debug(f"Приоритетный алерт для {symbol} не прошел валидацию: {validation_result['reason']}")
                return None

            candle_data = consecutive_alert.get('candle_data', {})
            if volume_alert and volume_alert.get('candle_data'):
                candle_data.update(volume_alert['candle_data'])

            # Проверяем имбаланс для приоритетного сигнала
            has_imbalance = False
            imbalance_data = None
            if volume_alert and volume_alert.get('has_imbalance'):
                has_imbalance = True
                imbalance_data = volume_alert.get('imbalance_data')
            elif consecutive_alert and consecutive_alert.get('has_imbalance'):
                has_imbalance = True
                imbalance_data = consecutive_alert.get('imbalance_data')

            current_timestamp_ms = self._get_current_timestamp_ms()

            priority_data = {
                'symbol': symbol,
                'alert_type': AlertType.PRIORITY.value,
                'price': consecutive_alert['price'],
                'consecutive_count': consecutive_alert['consecutive_count'],
                'timestamp': current_timestamp_ms,
                'close_timestamp': current_timestamp_ms,
                'is_closed': True,
                'has_imbalance': has_imbalance,
                'imbalance_data': imbalance_data,
                'candle_data': candle_data,
                'message': f"Приоритетный сигнал: {consecutive_alert['consecutive_count']} LONG свечей + всплеск объема{' + имбаланс' if has_imbalance else ''}"
            }

            if volume_alert:
                priority_data.update({
                    'volume_ratio': volume_alert['volume_ratio'],
                    'current_volume_usdt': volume_alert['current_volume_usdt'],
                    'average_volume_usdt': volume_alert['average_volume_usdt']
                })

            logger.info(f"✅ Приоритетный алерт для {symbol}")
            return priority_data

        except Exception as e:
            logger.error(f"❌ Ошибка проверки приоритетного сигнала для {symbol}: {e}")
            return None

    async def _check_recent_volume_alert_in_range(self, symbol: str, candles_back: int) -> bool:
        """Проверка, был ли объемный алерт в последних N свечах"""
        try:
            # Проверяем кулдауны объемных алертов
            current_timestamp_ms = self._get_current_timestamp_ms()
            
            # Проверяем обычные объемные алерты
            last_volume_alert = self.alert_cooldowns.get(symbol)
            if last_volume_alert:
                # Проверяем, был ли алерт в последние N минут (примерно N свечей)
                time_range_ms = candles_back * 60 * 1000  # N минут в миллисекундах
                if (current_timestamp_ms - last_volume_alert) <= time_range_ms:
                    return True
            
            # Проверяем предварительные сигналы
            if symbol in self.preliminary_signals:
                preliminary_time = self.preliminary_signals[symbol]['timestamp']
                time_range_ms = candles_back * 60 * 1000
                if (current_timestamp_ms - preliminary_time) <= time_range_ms:
                    return True
            
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка проверки недавних объемных алертов в диапазоне для {symbol}: {e}")
            return False

    async def _analyze_imbalance(self, symbol: str) -> Optional[Dict]:
        """Анализ имбаланса для символа"""
        try:
            # Получаем последние свечи для анализа
            candles = await self.db_queries.get_recent_candles(symbol, 20)

            if len(candles) < 15:
                return None

            # Используем анализатор имбалансов
            return self.imbalance_analyzer.analyze_all_imbalances(candles)

        except Exception as e:
            logger.error(f"❌ Ошибка анализа имбаланса для {symbol}: {e}")
            return None

    async def _get_order_book_snapshot(self, symbol: str) -> Optional[Dict]:
        """Получение снимка стакана заявок"""
        try:
            if not self.settings.get('orderbook_enabled', False):
                return None

            # Здесь должна быть реализация получения стакана через Bybit API
            # Пока возвращаем None
            return None

        except Exception as e:
            logger.error(f"❌ Ошибка получения стакана для {symbol}: {e}")
            return None

    async def _send_alert(self, alert_data: Dict):
        """Отправка алерта"""
        try:
            # Логируем временные метки алерта
            logger.info(f"📤 Отправка алерта {alert_data['alert_type']} для {alert_data['symbol']}")
            logger.info(f"⏰ Время алерта (UTC timestamp_ms): {alert_data.get('timestamp')}")

            # Сохраняем в базу данных (будет реализовано в database_queries)
            # alert_id = await self.db_queries.save_alert(alert_data)
            # alert_data['id'] = alert_id

            # Отправляем в WebSocket
            if self.connection_manager:
                websocket_data = {
                    'type': 'new_alert',
                    'alert': self._serialize_alert(alert_data),
                    'server_timestamp': self._get_current_timestamp_ms(),
                    'utc_synced': self.time_manager.is_time_synced() if self.time_manager else False
                }
                await self.connection_manager.broadcast_json(websocket_data)

            # Отправляем в Telegram
            if self.telegram_bot:
                if alert_data['alert_type'] == 'preliminary_volume_spike':
                    await self.telegram_bot.send_preliminary_alert(alert_data)
                elif alert_data['alert_type'] == 'final_volume_spike':
                    await self.telegram_bot.send_final_alert(alert_data)
                elif alert_data['alert_type'] == AlertType.VOLUME_SPIKE.value:
                    await self.telegram_bot.send_volume_alert(alert_data)
                elif alert_data['alert_type'] == AlertType.CONSECUTIVE_LONG.value:
                    await self.telegram_bot.send_consecutive_alert(alert_data)
                elif alert_data['alert_type'] == AlertType.PRIORITY.value:
                    await self.telegram_bot.send_priority_alert(alert_data)

            logger.info(f"✅ Алерт отправлен: {alert_data['symbol']} - {alert_data['alert_type']}")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки алерта: {e}")

    def _serialize_alert(self, alert_data: Dict) -> Dict:
        """Сериализация алерта для JSON"""
        return alert_data.copy()

    def update_settings(self, new_settings: Dict):
        """Обновление настроек"""
        self.settings.update(new_settings)
        
        # Обновляем настройки компонентов
        self.validators.update_settings(new_settings)
        self.imbalance_analyzer.update_settings(new_settings)
        
        logger.info(f"⚙️ Настройки AlertManager обновлены")

    def get_settings(self) -> Dict:
        """Получение текущих настроек"""
        return self.settings.copy()

    async def cleanup_old_data(self):
        """Очистка старых данных"""
        try:
            # Очищаем кулдауны (старше часа)
            current_timestamp_ms = self._get_current_timestamp_ms()
            cooldown_cutoff_ms = current_timestamp_ms - (60 * 60 * 1000)  # 1 час в мс

            for symbol in list(self.alert_cooldowns.keys()):
                if self.alert_cooldowns[symbol] < cooldown_cutoff_ms:
                    del self.alert_cooldowns[symbol]

            logger.info("🧹 Очистка старых данных завершена")

        except Exception as e:
            logger.error(f"❌ Ошибка очистки старых данных: {e}")
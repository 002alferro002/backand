import asyncio
import json
import logging
import websockets
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta, timezone
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import WebSocketException
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class BybitWebSocketManager:
    """Менеджер WebSocket соединения с Bybit"""

    def __init__(self, alert_manager, connection_manager):
        self.alert_manager = alert_manager
        self.connection_manager = connection_manager
        self.websocket = None
        self.is_running = False
        self.websocket_connected = False
        self.streaming_active = False

        # Настройки WebSocket
        self.ws_url = "wss://stream.bybit.com/v5/public/linear"
        self.ping_interval = get_setting('WS_PING_INTERVAL', 20)
        self.ping_timeout = get_setting('WS_PING_TIMEOUT', 10)
        self.close_timeout = get_setting('WS_CLOSE_TIMEOUT', 10)
        self.max_size = get_setting('WS_MAX_SIZE', 10000000)

        # Управление подписками
        self.subscribed_pairs = set()
        self.subscription_pending = set()
        self.trading_pairs = set()

        # Мониторинг соединения
        self.last_message_time = None
        self.messages_received = 0
        self.last_stats_log = datetime.now(timezone.utc)
        self.ping_task = None

        # Настройки переподключения
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5
        self.connection_stable_time = 60

        # Кэш обработанных свечей
        self.processed_candles = {}

    async def connect(self):
        """Подключение к WebSocket"""
        try:
            logger.info(f"🔌 Подключение к WebSocket: {self.ws_url}")

            async with websockets.connect(
                    self.ws_url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    close_timeout=self.close_timeout,
                    max_size=self.max_size,
                    compression=None
            ) as websocket:
                self.websocket = websocket
                self.websocket_connected = True
                self.last_message_time = datetime.now(timezone.utc)

                # Сбрасываем отслеживание подписок
                self.subscribed_pairs.clear()
                self.subscription_pending.clear()

                # Подписываемся на торговые пары
                if self.trading_pairs:
                    await self._subscribe_to_pairs(self.trading_pairs)

                logger.info(f"✅ WebSocket подключен, подписка на {len(self.trading_pairs)} пар")

                # Отправляем статус подключения
                await self._send_connection_status("connected")

                # Запускаем мониторинг соединения
                self.ping_task = asyncio.create_task(self._monitor_connection())
                self.streaming_active = True

                # Обработка входящих сообщений
                async for message in websocket:
                    if not self.is_running:
                        break

                    try:
                        await self._handle_message(message)
                    except Exception as e:
                        logger.error(f"❌ Ошибка обработки сообщения: {e}")
                        continue

        except websockets.exceptions.ConnectionClosedError as e:
            logger.warning(f"⚠️ WebSocket соединение закрыто: {e}")
            raise WebSocketException(f"Соединение закрыто: {e}")
        except Exception as e:
            logger.error(f"❌ Ошибка WebSocket соединения: {e}")
            raise WebSocketException(f"Ошибка подключения: {e}")
        finally:
            self.websocket_connected = False
            self.streaming_active = False
            if self.ping_task:
                self.ping_task.cancel()

    async def _subscribe_to_pairs(self, pairs: Set[str]):
        """Подписка на торговые пары"""
        if not pairs:
            return

        # Разбиваем на группы по 50 пар
        batch_size = 50
        pairs_list = list(pairs)

        for i in range(0, len(pairs_list), batch_size):
            batch = pairs_list[i:i + batch_size]
            subscribe_message = {
                "op": "subscribe",
                "args": [f"kline.1.{pair}" for pair in batch]
            }

            try:
                await self.websocket.send(json.dumps(subscribe_message))
                logger.info(f"📡 Подписка на пакет {i // batch_size + 1}: {len(batch)} пар")

                # Добавляем в ожидающие подписки
                self.subscription_pending.update(batch)

                # Задержка между пакетами
                if i + batch_size < len(pairs_list):
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"❌ Ошибка подписки на пакет {i // batch_size + 1}: {e}")
                continue

    async def _handle_message(self, message: str):
        """Обработка входящих сообщений"""
        try:
            self.last_message_time = datetime.now(timezone.utc)
            self.messages_received += 1

            data = json.loads(message)

            # Обрабатываем системные сообщения
            if 'success' in data:
                if data['success']:
                    logger.debug("✅ Успешная подписка на WebSocket пакет")
                else:
                    logger.error(f"❌ Ошибка подписки WebSocket: {data}")
                return

            if 'op' in data:
                logger.debug(f"📡 Системное сообщение WebSocket: {data}")
                return

            # Обрабатываем данные свечей
            if data.get('topic', '').startswith('kline.1.'):
                await self._handle_kline_data(data)

            # Логируем статистику каждые 5 минут
            if (datetime.now(timezone.utc) - self.last_stats_log).total_seconds() > 300:
                logger.info(f"📊 WebSocket статистика: {self.messages_received} сообщений, "
                           f"подписано на {len(self.subscribed_pairs)} пар")

        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Некорректный JSON от WebSocket: {e}")
        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")

    async def _handle_kline_data(self, data: Dict):
        """Обработка данных свечей"""
        try:
            kline_data = data['data'][0]
            symbol = data['topic'].split('.')[-1]

            # Проверяем, что символ в нашем списке
            if symbol not in self.trading_pairs:
                logger.debug(f"📊 Получены данные для символа {symbol}, которого нет в watchlist")
                return

            # Добавляем символ в подписанные
            if symbol in self.subscription_pending:
                self.subscription_pending.remove(symbol)
            self.subscribed_pairs.add(symbol)

            # Обновляем время последних потоковых данных
            # (это будет обрабатываться в основном клиенте)

            # Преобразуем данные в нужный формат
            start_time_ms = int(kline_data['start'])
            end_time_ms = int(kline_data['end'])
            is_closed = kline_data.get('confirm', False)

            # Для закрытых свечей округляем до минут
            if is_closed:
                start_time_ms = (start_time_ms // 60000) * 60000
                end_time_ms = (end_time_ms // 60000) * 60000

            formatted_data = {
                'start': start_time_ms,
                'end': end_time_ms,
                'open': kline_data['open'],
                'high': kline_data['high'],
                'low': kline_data['low'],
                'close': kline_data['close'],
                'volume': kline_data['volume'],
                'confirm': is_closed
            }

            # Обрабатываем закрытые свечи
            if is_closed:
                await self._process_closed_candle(symbol, formatted_data)

            # Отправляем обновление клиентам
            await self._send_kline_update(symbol, formatted_data, is_closed)

        except Exception as e:
            logger.error(f"❌ Ошибка обработки kline данных: {e}")

    async def _process_closed_candle(self, symbol: str, formatted_data: Dict):
        """Обработка закрытой свечи"""
        try:
            start_time_ms = formatted_data['start']

            # Проверка на дублирование
            last_processed = self.processed_candles.get(symbol, 0)
            if start_time_ms > last_processed:
                # Обрабатываем через менеджер алертов
                if self.alert_manager:
                    await self.alert_manager.process_kline_data(symbol, formatted_data)

                # Помечаем свечу как обработанную
                self.processed_candles[symbol] = start_time_ms

                logger.debug(f"📊 Обработана закрытая свеча {symbol} в {start_time_ms}")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки закрытой свечи для {symbol}: {e}")

    async def _send_kline_update(self, symbol: str, formatted_data: Dict, is_closed: bool):
        """Отправка обновления данных клиентам"""
        try:
            if self.connection_manager:
                stream_item = {
                    "type": "kline_update",
                    "symbol": symbol,
                    "data": formatted_data,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "is_closed": is_closed,
                    "streaming_active": self.streaming_active,
                    "server_timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)
                }

                await self.connection_manager.broadcast_json(stream_item)

        except Exception as e:
            logger.error(f"❌ Ошибка отправки обновления kline: {e}")

    async def _send_connection_status(self, status: str, reason: str = None):
        """Отправка статуса подключения"""
        try:
            if self.connection_manager:
                status_data = {
                    "type": "connection_status",
                    "status": status,
                    "pairs_count": len(self.trading_pairs),
                    "subscribed_count": len(self.subscribed_pairs),
                    "pending_count": len(self.subscription_pending),
                    "streaming_active": self.streaming_active,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

                if reason:
                    status_data["reason"] = reason

                await self.connection_manager.broadcast_json(status_data)

        except Exception as e:
            logger.error(f"❌ Ошибка отправки статуса подключения: {e}")

    async def _monitor_connection(self):
        """Мониторинг состояния WebSocket соединения"""
        connection_start_time = datetime.now(timezone.utc)

        while self.is_running and self.websocket_connected:
            try:
                await asyncio.sleep(30)

                if not self.websocket_connected:
                    break

                current_time = datetime.now(timezone.utc)

                # Проверяем время последнего сообщения
                if self.last_message_time:
                    time_since_last_message = (current_time - self.last_message_time).total_seconds()

                    if time_since_last_message > 90:
                        logger.warning(f"⚠️ Нет сообщений от WebSocket уже {time_since_last_message:.0f} секунд")

                        await self._send_connection_status(
                            "warning", 
                            f"No messages for {time_since_last_message:.0f} seconds"
                        )

                        # Принудительное переподключение
                        if time_since_last_message > 120:
                            logger.error("❌ Принудительное переподключение из-за отсутствия сообщений")
                            self.streaming_active = False
                            break

                # Проверяем стабильность соединения
                connection_duration = (current_time - connection_start_time).total_seconds()
                if connection_duration > self.connection_stable_time:
                    self.reconnect_attempts = 0

            except Exception as e:
                logger.error(f"❌ Ошибка мониторинга соединения: {e}")
                break

    def update_trading_pairs(self, new_pairs: Set[str], removed_pairs: Set[str]):
        """Обновление списка торговых пар"""
        self.trading_pairs.update(new_pairs)
        self.trading_pairs -= removed_pairs

    async def subscribe_to_new_pairs(self, new_pairs: Set[str]):
        """Подписка на новые пары"""
        if new_pairs and self.websocket_connected:
            await self._subscribe_to_pairs(new_pairs)

    async def unsubscribe_from_pairs(self, removed_pairs: Set[str]):
        """Отписка от пар"""
        if removed_pairs and self.websocket_connected:
            try:
                unsubscribe_message = {
                    "op": "unsubscribe",
                    "args": [f"kline.1.{pair}" for pair in removed_pairs]
                }
                await self.websocket.send(json.dumps(unsubscribe_message))
                logger.info(f"📡 Отписка от {len(removed_pairs)} пар")

                # Обновляем отслеживание подписок
                self.subscribed_pairs -= removed_pairs

            except Exception as e:
                logger.error(f"❌ Ошибка отписки от пар: {e}")

    def get_connection_stats(self) -> Dict:
        """Получение статистики подключения"""
        return {
            'websocket_connected': self.websocket_connected,
            'streaming_active': self.streaming_active,
            'total_pairs': len(self.trading_pairs),
            'subscribed_pairs': len(self.subscribed_pairs),
            'pending_pairs': len(self.subscription_pending),
            'messages_received': self.messages_received,
            'reconnect_attempts': self.reconnect_attempts,
            'last_message_time': self.last_message_time.isoformat() if self.last_message_time else None
        }

    async def close(self):
        """Закрытие WebSocket соединения"""
        self.is_running = False
        self.websocket_connected = False
        self.streaming_active = False

        if self.ping_task:
            self.ping_task.cancel()
            try:
                await self.ping_task
            except asyncio.CancelledError:
                pass

        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.debug(f"Ошибка при закрытии WebSocket: {e}")

        logger.info("🛑 WebSocket соединение закрыто")
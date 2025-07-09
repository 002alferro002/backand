import asyncio
import json
from typing import List, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_utils import CoreUtils

logger = get_logger(__name__)


class ConnectionManager:
    """Менеджер WebSocket соединений"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Подключение нового WebSocket клиента"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket подключен. Всего подключений: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Отключение WebSocket клиента"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket отключен. Всего подключений: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """Отправка личного сообщения конкретному клиенту"""
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Ошибка отправки личного сообщения: {e}")
            self.disconnect(websocket)

    async def send_personal_json(self, data: Dict[str, Any], websocket: WebSocket):
        """Отправка JSON данных конкретному клиенту"""
        try:
            message = CoreUtils.safe_json_dumps(data)
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Ошибка отправки личного JSON сообщения: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: str):
        """Рассылка текстового сообщения всем подключенным клиентам"""
        if not self.active_connections:
            return

        disconnected = []
        
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения: {e}")
                disconnected.append(connection)

        # Удаляем отключенные соединения
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_json(self, data: Dict[str, Any]):
        """Рассылка JSON данных всем подключенным клиентам"""
        if not self.active_connections:
            return

        try:
            message = CoreUtils.safe_json_dumps(data)
            await self.broadcast(message)
        except Exception as e:
            logger.error(f"Ошибка сериализации JSON для рассылки: {e}")

    async def broadcast_to_group(self, message: str, group_filter: callable = None):
        """Рассылка сообщения группе клиентов с фильтром"""
        if not self.active_connections:
            return

        disconnected = []
        
        for connection in self.active_connections:
            try:
                # Применяем фильтр если он задан
                if group_filter and not group_filter(connection):
                    continue
                    
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Ошибка отправки группового сообщения: {e}")
                disconnected.append(connection)

        # Удаляем отключенные соединения
        for connection in disconnected:
            self.disconnect(connection)

    async def send_system_notification(self, notification_type: str, data: Dict[str, Any]):
        """Отправка системного уведомления"""
        system_message = {
            "type": "system_notification",
            "notification_type": notification_type,
            "data": data,
            "timestamp": CoreUtils.get_utc_timestamp_ms()
        }
        
        await self.broadcast_json(system_message)

    async def send_error_notification(self, error_type: str, error_message: str, details: Dict = None):
        """Отправка уведомления об ошибке"""
        error_notification = {
            "type": "error_notification",
            "error_type": error_type,
            "error_message": error_message,
            "details": details or {},
            "timestamp": CoreUtils.get_utc_timestamp_ms()
        }
        
        await self.broadcast_json(error_notification)

    async def send_status_update(self, component: str, status: str, details: Dict = None):
        """Отправка обновления статуса компонента"""
        status_update = {
            "type": "status_update",
            "component": component,
            "status": status,
            "details": details or {},
            "timestamp": CoreUtils.get_utc_timestamp_ms()
        }
        
        await self.broadcast_json(status_update)

    def get_connection_count(self) -> int:
        """Получение количества активных соединений"""
        return len(self.active_connections)

    def get_connection_stats(self) -> Dict[str, Any]:
        """Получение статистики соединений"""
        return {
            "active_connections": len(self.active_connections),
            "connection_ids": [id(conn) for conn in self.active_connections]
        }

    async def ping_all_connections(self):
        """Ping всех активных соединений для проверки состояния"""
        if not self.active_connections:
            return

        disconnected = []
        
        for connection in self.active_connections:
            try:
                ping_message = {
                    "type": "ping",
                    "timestamp": CoreUtils.get_utc_timestamp_ms()
                }
                await connection.send_text(CoreUtils.safe_json_dumps(ping_message))
            except Exception as e:
                logger.warning(f"Соединение не отвечает на ping: {e}")
                disconnected.append(connection)

        # Удаляем неотвечающие соединения
        for connection in disconnected:
            self.disconnect(connection)

    async def handle_client_message(self, websocket: WebSocket, message: str):
        """Обработка сообщения от клиента"""
        try:
            data = CoreUtils.safe_json_loads(message)
            message_type = data.get('type')
            
            if message_type == 'ping':
                # Отвечаем на ping от клиента
                pong_message = {
                    "type": "pong",
                    "timestamp": CoreUtils.get_utc_timestamp_ms()
                }
                await self.send_personal_json(pong_message, websocket)
                
            elif message_type == 'subscribe':
                # Обработка подписки на определенные типы данных
                await self._handle_subscription(websocket, data)
                
            elif message_type == 'unsubscribe':
                # Обработка отписки
                await self._handle_unsubscription(websocket, data)
                
            else:
                logger.debug(f"Неизвестный тип сообщения от клиента: {message_type}")
                
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения от клиента: {e}")

    async def _handle_subscription(self, websocket: WebSocket, data: Dict):
        """Обработка подписки клиента"""
        # Здесь можно реализовать логику подписки на определенные типы данных
        # Например, подписка на алерты определенных символов
        subscription_type = data.get('subscription_type')
        params = data.get('params', {})
        
        logger.info(f"Клиент подписался на {subscription_type} с параметрами {params}")
        
        # Подтверждение подписки
        confirmation = {
            "type": "subscription_confirmed",
            "subscription_type": subscription_type,
            "params": params,
            "timestamp": CoreUtils.get_utc_timestamp_ms()
        }
        await self.send_personal_json(confirmation, websocket)

    async def _handle_unsubscription(self, websocket: WebSocket, data: Dict):
        """Обработка отписки клиента"""
        subscription_type = data.get('subscription_type')
        
        logger.info(f"Клиент отписался от {subscription_type}")
        
        # Подтверждение отписки
        confirmation = {
            "type": "unsubscription_confirmed",
            "subscription_type": subscription_type,
            "timestamp": CoreUtils.get_utc_timestamp_ms()
        }
        await self.send_personal_json(confirmation, websocket)

    async def cleanup_inactive_connections(self):
        """Очистка неактивных соединений"""
        if not self.active_connections:
            return

        initial_count = len(self.active_connections)
        
        # Проверяем все соединения
        await self.ping_all_connections()
        
        final_count = len(self.active_connections)
        
        if initial_count != final_count:
            logger.info(f"Очищено {initial_count - final_count} неактивных соединений")

    async def start_periodic_cleanup(self, interval_seconds: int = 300):
        """Запуск периодической очистки соединений"""
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                await self.cleanup_inactive_connections()
            except Exception as e:
                logger.error(f"Ошибка периодической очистки соединений: {e}")
                await asyncio.sleep(60)  # Повторить через минуту при ошибке
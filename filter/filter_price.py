import asyncio
from typing import List, Dict, Set
from datetime import datetime
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import APIException
from cryptoscan.backand.bybit.bybit_rest_api import BybitRestAPI
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class PriceFilter:
    """Фильтр торговых пар по изменению цены"""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.bybit_api = BybitRestAPI()
        
        # Настройки фильтра
        self.price_history_days = get_setting('PRICE_HISTORY_DAYS', 1000)
        self.price_drop_percentage = get_setting('PRICE_DROP_PERCENTAGE', 10.0)
        self.pairs_check_interval_minutes = get_setting('PAIRS_CHECK_INTERVAL_MINUTES', 30)
        
        # Состояние
        self.is_running = False
        self.on_pairs_updated_callback = None

    async def start(self):
        """Запуск фильтрации торговых пар"""
        self.is_running = True
        logger.info("🔍 Запуск фильтрации торговых пар по цене")

        # Инициализируем API
        await self.bybit_api.start()

        # Первоначальное обновление
        await self.update_watchlist()

        # Периодическое обновление
        while self.is_running:
            try:
                await asyncio.sleep(self.pairs_check_interval_minutes * 60)

                if self.is_running:
                    logger.info(f"🔄 Периодическая проверка торговых пар (каждые {self.pairs_check_interval_minutes} мин)")
                    await self.update_watchlist()
            except Exception as e:
                logger.error(f"❌ Ошибка при обновлении watchlist: {e}")
                await asyncio.sleep(60)  # Ждем минуту перед повторной попыткой

    async def stop(self):
        """Остановка фильтрации"""
        self.is_running = False
        await self.bybit_api.stop()
        logger.info("🛑 Фильтрация торговых пар остановлена")

    def set_pairs_updated_callback(self, callback):
        """Установить callback для уведомления о новых парах"""
        self.on_pairs_updated_callback = callback

    async def get_perpetual_pairs(self) -> List[str]:
        """Получение списка бессрочных фьючерсных контрактов"""
        try:
            return await self.bybit_api.get_perpetual_pairs()
        except Exception as e:
            logger.error(f"❌ Ошибка получения торговых пар: {e}")
            return []

    async def analyze_price_changes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Анализ изменений цен для списка символов"""
        results = {}
        
        # Обрабатываем символы пакетами
        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            # Получаем текущие цены пакетом
            current_prices = await self.bybit_api.batch_get_current_prices(batch)
            
            # Получаем исторические цены для каждого символа
            for symbol in batch:
                try:
                    current_price = current_prices.get(symbol, 0)
                    if current_price <= 0:
                        continue
                    
                    historical_price = await self.bybit_api.get_historical_price(
                        symbol, self.price_history_days
                    )
                    
                    if historical_price > 0:
                        price_drop = ((historical_price - current_price) / historical_price) * 100
                        
                        results[symbol] = {
                            'current_price': current_price,
                            'historical_price': historical_price,
                            'price_drop': price_drop,
                            'meets_criteria': price_drop >= self.price_drop_percentage
                        }
                    
                    # Небольшая задержка между запросами
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка анализа цены для {symbol}: {e}")
                    continue
            
            # Задержка между пакетами
            if i + batch_size < len(symbols):
                await asyncio.sleep(1)
        
        return results

    async def update_watchlist(self):
        """Обновление watchlist на основе критериев цены"""
        try:
            logger.info("🔍 Начало обновления watchlist...")
            
            # Получаем все торговые пары
            all_pairs = await self.get_perpetual_pairs()
            if not all_pairs:
                logger.warning("⚠️ Не удалось получить список торговых пар")
                return []
            
            # Получаем текущий watchlist
            current_watchlist = await self.db_manager.get_watchlist()
            
            logger.info(f"📊 Анализ {len(all_pairs)} торговых пар...")
            
            # Анализируем изменения цен
            price_analysis = await self.analyze_price_changes(all_pairs)
            
            # Формируем новый watchlist
            new_watchlist = []
            added_count = 0
            removed_count = 0
            new_pairs = set()
            
            for symbol, analysis in price_analysis.items():
                if analysis['meets_criteria']:
                    new_watchlist.append(symbol)
                    
                    if symbol not in current_watchlist:
                        # Добавляем новую пару
                        await self.db_manager.add_to_watchlist(
                            symbol, 
                            analysis['price_drop'], 
                            analysis['current_price'], 
                            analysis['historical_price']
                        )
                        added_count += 1
                        new_pairs.add(symbol)
                        logger.info(f"➕ Добавлена пара {symbol} в watchlist (падение цены: {analysis['price_drop']:.2f}%)")

            # Удаляем пары, которые больше не соответствуют критериям
            for symbol in current_watchlist:
                if symbol not in new_watchlist:
                    await self.db_manager.remove_from_watchlist(symbol)
                    removed_count += 1
                    logger.info(f"➖ Удалена пара {symbol} из watchlist (не соответствует критериям)")

            logger.info(f"✅ Watchlist обновлен: {len(new_watchlist)} активных пар (+{added_count}, -{removed_count})")

            # Уведомляем о новых парах через callback
            if new_pairs and self.on_pairs_updated_callback:
                logger.info(f"📢 Уведомляем о {len(new_pairs)} новых парах через callback")
                try:
                    await self.on_pairs_updated_callback(new_pairs, set())
                except Exception as e:
                    logger.error(f"❌ Ошибка вызова callback для новых пар: {e}")

            return new_watchlist

        except Exception as e:
            logger.error(f"❌ Ошибка обновления watchlist: {e}")
            return []

    async def get_price_statistics(self) -> Dict:
        """Получение статистики по ценам"""
        try:
            watchlist = await self.db_manager.get_watchlist_details()
            
            if not watchlist:
                return {
                    'total_pairs': 0,
                    'average_drop': 0,
                    'max_drop': 0,
                    'min_drop': 0
                }
            
            drops = [pair['price_drop'] for pair in watchlist if pair['price_drop']]
            
            return {
                'total_pairs': len(watchlist),
                'average_drop': sum(drops) / len(drops) if drops else 0,
                'max_drop': max(drops) if drops else 0,
                'min_drop': min(drops) if drops else 0,
                'pairs_with_data': len(drops)
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики цен: {e}")
            return {
                'total_pairs': 0,
                'average_drop': 0,
                'max_drop': 0,
                'min_drop': 0,
                'error': str(e)
            }

    def update_settings(self, new_settings: Dict):
        """Обновление настроек фильтра"""
        if 'PRICE_CHECK_INTERVAL_MINUTES' in new_settings:
            self.price_check_interval_minutes = new_settings['PRICE_CHECK_INTERVAL_MINUTES']
        
        if 'PRICE_HISTORY_DAYS' in new_settings:
            self.price_history_days = new_settings['PRICE_HISTORY_DAYS']
        
        if 'PRICE_DROP_PERCENTAGE' in new_settings:
            self.price_drop_percentage = new_settings['PRICE_DROP_PERCENTAGE']
        
        if 'PAIRS_CHECK_INTERVAL_MINUTES' in new_settings:
            self.pairs_check_interval_minutes = new_settings['PAIRS_CHECK_INTERVAL_MINUTES']
        
        logger.info("⚙️ Настройки фильтра цен обновлены")

    def get_settings(self) -> Dict:
        """Получение текущих настроек"""
        return {
            'price_check_interval_minutes': self.price_check_interval_minutes,
            'price_history_days': self.price_history_days,
            'price_drop_percentage': self.price_drop_percentage,
            'pairs_check_interval_minutes': self.pairs_check_interval_minutes
        }
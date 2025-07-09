import asyncio
import aiohttp
import requests
from typing import List, Dict, Optional
from datetime import datetime
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.core.core_exceptions import APIException
from cryptoscan.backand.core.core_utils import CoreUtils

logger = get_logger(__name__)


class BybitRestAPI:
    """Клиент для работы с REST API Bybit"""

    def __init__(self):
        self.base_url = "https://api.bybit.com"
        self.session = None

    async def start(self):
        """Инициализация HTTP сессии"""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    'User-Agent': 'CryptoScan/1.0',
                    'Content-Type': 'application/json'
                }
            )
            logger.info("🌐 HTTP сессия для Bybit API инициализирована")

    async def stop(self):
        """Закрытие HTTP сессии"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("🌐 HTTP сессия для Bybit API закрыта")

    async def get_server_time(self) -> Dict:
        """Получение времени сервера"""
        try:
            url = f"{self.base_url}/v5/market/time"
            
            if not self.session:
                await self.start()

            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('retCode') == 0:
                        result = data['result']
                        return {
                            'server_time_seconds': int(result['timeSecond']),
                            'server_time_nanos': int(result['timeNano']),
                            'server_time_ms': int(result['timeSecond']) * 1000 + (int(result['timeNano']) // 1_000_000) % 100
                        }
                    else:
                        raise APIException(f"API ошибка: {data.get('retMsg')}")
                else:
                    raise APIException(f"HTTP ошибка: {response.status}")

        except Exception as e:
            logger.error(f"❌ Ошибка получения времени сервера: {e}")
            raise APIException(f"Ошибка получения времени сервера: {e}")

    async def get_perpetual_pairs(self) -> List[str]:
        """Получение списка бессрочных фьючерсных контрактов"""
        try:
            url = f"{self.base_url}/v5/market/instruments-info"
            params = {'category': 'linear'}
            
            if not self.session:
                await self.start()

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('retCode') == 0:
                        pairs = []
                        for instrument in data['result']['list']:
                            if (instrument['contractType'] == 'LinearPerpetual' and
                                    instrument['status'] == 'Trading' and
                                    instrument['symbol'].endswith('USDT')):
                                pairs.append(instrument['symbol'])
                        
                        logger.info(f"📋 Получено {len(pairs)} торговых пар")
                        return pairs
                    else:
                        raise APIException(f"API ошибка: {data.get('retMsg')}")
                else:
                    raise APIException(f"HTTP ошибка: {response.status}")

        except Exception as e:
            logger.error(f"❌ Ошибка получения торговых пар: {e}")
            raise APIException(f"Ошибка получения торговых пар: {e}")

    async def get_current_price(self, symbol: str) -> float:
        """Получение текущей цены актива"""
        try:
            url = f"{self.base_url}/v5/market/tickers"
            params = {'category': 'linear', 'symbol': symbol}
            
            if not self.session:
                await self.start()

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('retCode') == 0 and data['result']['list']:
                        return float(data['result']['list'][0]['lastPrice'])
                    else:
                        logger.warning(f"⚠️ Не удалось получить цену для {symbol}")
                        return 0.0
                else:
                    logger.warning(f"⚠️ HTTP ошибка при получении цены {symbol}: {response.status}")
                    return 0.0

        except Exception as e:
            logger.error(f"❌ Ошибка получения текущей цены для {symbol}: {e}")
            return 0.0

    async def get_historical_price(self, symbol: str, days_ago: int) -> float:
        """Получение исторической цены актива"""
        try:
            url = f"{self.base_url}/v5/market/kline"
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = end_time - (days_ago * 24 * 60 * 60 * 1000)
            
            params = {
                'category': 'linear',
                'symbol': symbol,
                'interval': 'D',
                'start': start_time,
                'limit': 1
            }
            
            if not self.session:
                await self.start()

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('retCode') == 0 and data['result']['list']:
                        return float(data['result']['list'][0][4])  # Закрытие свечи
                    else:
                        logger.warning(f"⚠️ Не удалось получить историческую цену для {symbol}")
                        return 0.0
                else:
                    logger.warning(f"⚠️ HTTP ошибка при получении исторической цены {symbol}: {response.status}")
                    return 0.0

        except Exception as e:
            logger.error(f"❌ Ошибка получения исторической цены для {symbol}: {e}")
            return 0.0

    async def get_kline_data(self, symbol: str, start_time_ms: int, end_time_ms: int, limit: int = 1000) -> List[Dict]:
        """Получение данных свечей"""
        try:
            url = f"{self.base_url}/v5/market/kline"
            params = {
                'category': 'linear',
                'symbol': symbol,
                'interval': '1',
                'start': start_time_ms,
                'end': end_time_ms,
                'limit': limit
            }
            
            if not self.session:
                await self.start()

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('retCode') == 0:
                        klines = data['result']['list']
                        if klines:
                            # Bybit возвращает данные в обратном порядке
                            klines.reverse()
                            
                            processed_klines = []
                            for kline in klines:
                                processed_klines.append({
                                    'timestamp': int(kline[0]),
                                    'open': float(kline[1]),
                                    'high': float(kline[2]),
                                    'low': float(kline[3]),
                                    'close': float(kline[4]),
                                    'volume': float(kline[5])
                                })
                            
                            return processed_klines
                        else:
                            logger.debug(f"📊 Нет данных kline для {symbol} в указанном диапазоне")
                            return []
                    else:
                        raise APIException(f"API ошибка при получении kline для {symbol}: {data.get('retMsg')}")
                else:
                    raise APIException(f"HTTP ошибка при получении kline для {symbol}: {response.status}")

        except Exception as e:
            logger.error(f"❌ Ошибка получения kline данных для {symbol}: {e}")
            raise APIException(f"Ошибка получения kline данных: {e}")

    async def get_order_book(self, symbol: str, limit: int = 25) -> Optional[Dict]:
        """Получение стакана заявок"""
        try:
            url = f"{self.base_url}/v5/market/orderbook"
            params = {
                'category': 'linear',
                'symbol': symbol,
                'limit': limit
            }
            
            if not self.session:
                await self.start()

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('retCode') == 0:
                        result = data['result']
                        return {
                            'bids': [[float(bid[0]), float(bid[1])] for bid in result.get('b', [])],
                            'asks': [[float(ask[0]), float(ask[1])] for ask in result.get('a', [])],
                            'timestamp': CoreUtils.get_utc_timestamp_ms()
                        }
                    else:
                        logger.warning(f"⚠️ API ошибка при получении стакана для {symbol}: {data.get('retMsg')}")
                        return None
                else:
                    logger.warning(f"⚠️ HTTP ошибка при получении стакана для {symbol}: {response.status}")
                    return None

        except Exception as e:
            logger.error(f"❌ Ошибка получения стакана для {symbol}: {e}")
            return None

    async def batch_get_current_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Пакетное получение текущих цен"""
        try:
            url = f"{self.base_url}/v5/market/tickers"
            params = {'category': 'linear'}
            
            if not self.session:
                await self.start()

            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('retCode') == 0:
                        prices = {}
                        for ticker in data['result']['list']:
                            symbol = ticker['symbol']
                            if symbol in symbols:
                                prices[symbol] = float(ticker['lastPrice'])
                        
                        return prices
                    else:
                        raise APIException(f"API ошибка: {data.get('retMsg')}")
                else:
                    raise APIException(f"HTTP ошибка: {response.status}")

        except Exception as e:
            logger.error(f"❌ Ошибка пакетного получения цен: {e}")
            return {}

    def get_current_price_sync(self, symbol: str) -> float:
        """Синхронное получение текущей цены (для совместимости)"""
        try:
            url = f"{self.base_url}/v5/market/tickers"
            params = {'category': 'linear', 'symbol': symbol}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('retCode') == 0 and data['result']['list']:
                    return float(data['result']['list'][0]['lastPrice'])
                else:
                    logger.warning(f"⚠️ Не удалось получить цену для {symbol}")
                    return 0.0
            else:
                logger.warning(f"⚠️ HTTP ошибка при получении цены {symbol}: {response.status_code}")
                return 0.0

        except Exception as e:
            logger.error(f"❌ Ошибка получения текущей цены для {symbol}: {e}")
            return 0.0

    def get_historical_price_sync(self, symbol: str, days_ago: int) -> float:
        """Синхронное получение исторической цены (для совместимости)"""
        try:
            url = f"{self.base_url}/v5/market/kline"
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = end_time - (days_ago * 24 * 60 * 60 * 1000)
            
            params = {
                'category': 'linear',
                'symbol': symbol,
                'interval': 'D',
                'start': start_time,
                'limit': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('retCode') == 0 and data['result']['list']:
                    return float(data['result']['list'][0][4])  # Закрытие свечи
                else:
                    logger.warning(f"⚠️ Не удалось получить историческую цену для {symbol}")
                    return 0.0
            else:
                logger.warning(f"⚠️ HTTP ошибка при получении исторической цены {symbol}: {response.status_code}")
                return 0.0

        except Exception as e:
            logger.error(f"❌ Ошибка получения исторической цены для {symbol}: {e}")
            return 0.0
import asyncio
import aiohttp
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from enum import Enum
from cryptoscan.backand.core.core_logger import get_logger
from cryptoscan.backand.settings import get_setting

logger = get_logger(__name__)


class SentimentScore(Enum):
    VERY_NEGATIVE = -2
    NEGATIVE = -1
    NEUTRAL = 0
    POSITIVE = 1
    VERY_POSITIVE = 2


@dataclass
class SocialMention:
    platform: str
    text: str
    author: str
    timestamp: datetime
    url: Optional[str]
    engagement: int  # likes, retweets, views etc
    sentiment_score: float
    confidence: float


@dataclass
class SocialRating:
    symbol: str
    overall_score: float  # -100 to 100
    mention_count: int
    positive_mentions: int
    negative_mentions: int
    neutral_mentions: int
    trending_score: float  # 0 to 100
    volume_score: float  # 0 to 100
    sentiment_trend: str  # 'rising', 'falling', 'stable'
    last_updated: datetime
    top_mentions: List[SocialMention]


class SocialSentimentAnalyzer:
    """Анализатор социальных настроений для торговых пар"""

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.session = None

        # Настройки из конфигурации
        self.analysis_period_hours = get_setting('SOCIAL_ANALYSIS_PERIOD_HOURS', 72)
        self.min_mentions_for_rating = get_setting('SOCIAL_MIN_MENTIONS_FOR_RATING', 3)
        self.cache_duration_minutes = get_setting('SOCIAL_CACHE_DURATION_MINUTES', 30)

        # Ключевые слова для поиска
        self.crypto_keywords = {
            'positive': [
                'moon', 'bullish', 'pump', 'rocket', 'gem', 'buy', 'long',
                'breakout', 'rally', 'surge', 'explosion', 'massive', 'huge',
                'profit', 'gains', 'winner', 'golden', 'diamond', 'fire',
                'bull', 'up', 'rise', 'green', 'lambo', 'hodl'
            ],
            'negative': [
                'dump', 'crash', 'bearish', 'sell', 'short', 'scam', 'rug',
                'dead', 'rip', 'loss', 'down', 'fall', 'drop', 'disaster',
                'avoid', 'warning', 'danger', 'exit', 'liquidated', 'bear',
                'red', 'panic', 'fear'
            ],
            'neutral': [
                'analysis', 'chart', 'technical', 'support', 'resistance',
                'volume', 'price', 'market', 'trading', 'hodl', 'dyor',
                'watch', 'monitor', 'update'
            ]
        }

        # Кэш для избежания повторных запросов
        self.ratings_cache = {}
        self.last_cache_update = {}

    async def start(self):
        """Запуск анализатора"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        logger.info("Social sentiment analyzer started")

    async def stop(self):
        """Остановка анализатора"""
        if self.session:
            await self.session.close()
        logger.info("Social sentiment analyzer stopped")

    async def get_symbol_rating(self, symbol: str) -> Optional[SocialRating]:
        """Получить рейтинг для торговой пары"""
        try:
            # Проверяем кэш
            cache_key = symbol
            if (cache_key in self.ratings_cache and
                    cache_key in self.last_cache_update and
                    (datetime.now(timezone.utc) - self.last_cache_update[
                        cache_key]).total_seconds() < self.cache_duration_minutes * 60):
                return self.ratings_cache[cache_key]

            # Получаем упоминания из разных источников
            mentions = []

            # CoinGecko trending данные
            coingecko_data = await self._get_coingecko_trending(symbol)

            # Reddit данные
            reddit_mentions = await self._get_reddit_mentions(symbol)
            mentions.extend(reddit_mentions)

            # Новостные данные
            news_mentions = await self._get_news_mentions(symbol)
            mentions.extend(news_mentions)

            # Социальные данные из CoinGecko
            social_mentions = await self._get_coingecko_social(symbol)
            mentions.extend(social_mentions)

            if len(mentions) < self.min_mentions_for_rating:
                logger.debug(f"Недостаточно упоминаний для {symbol}: {len(mentions)}")
                # Создаем базовый рейтинг на основе CoinGecko
                rating = self._create_basic_rating(symbol, coingecko_data)
            else:
                # Анализируем настроения
                rating = await self._calculate_rating(symbol, mentions, coingecko_data)

            # Сохраняем в кэш
            self.ratings_cache[cache_key] = rating
            self.last_cache_update[cache_key] = datetime.now(timezone.utc)

            # Сохраняем в базу данных
            await self._save_rating_to_db(rating)

            return rating

        except Exception as e:
            logger.error(f"Ошибка получения рейтинга для {symbol}: {e}")
            return None

    def _create_basic_rating(self, symbol: str, coingecko_data: Dict) -> SocialRating:
        """Создает базовый рейтинг на основе CoinGecko данных"""
        trending_score = coingecko_data.get('trending_score', 0)

        # Базовый рейтинг на основе трендов
        overall_score = min(50, max(-50, trending_score * 10))

        return SocialRating(
            symbol=symbol,
            overall_score=overall_score,
            mention_count=coingecko_data.get('mentions', 0),
            positive_mentions=max(1, int(coingecko_data.get('mentions', 0) * 0.4)),
            negative_mentions=max(1, int(coingecko_data.get('mentions', 0) * 0.2)),
            neutral_mentions=max(1, int(coingecko_data.get('mentions', 0) * 0.4)),
            trending_score=trending_score,
            volume_score=min(100, trending_score * 20),
            sentiment_trend='stable',
            last_updated=datetime.now(timezone.utc),
            top_mentions=[]
        )

    async def _get_reddit_mentions(self, symbol: str) -> List[SocialMention]:
        """Получение упоминаний из Reddit"""
        mentions = []
        try:
            clean_symbol = symbol.replace('USDT', '').lower()
            subreddits = ['cryptocurrency', 'CryptoMoonShots', 'altcoin', 'Bitcoin']

            for subreddit in subreddits:
                try:
                    url = f"https://www.reddit.com/r/{subreddit}/search.json"
                    params = {
                        'q': clean_symbol,
                        'sort': 'new',
                        'limit': 10,
                        't': 'week'
                    }

                    if self.session:
                        async with self.session.get(url, params=params) as response:
                            if response.status == 200:
                                data = await response.json()

                                for post in data.get('data', {}).get('children', []):
                                    post_data = post.get('data', {})

                                    text = f"{post_data.get('title', '')} {post_data.get('selftext', '')}"
                                    if clean_symbol.lower() in text.lower():
                                        mention = SocialMention(
                                            platform='reddit',
                                            text=text[:200],
                                            author=post_data.get('author', 'unknown'),
                                            timestamp=datetime.fromtimestamp(post_data.get('created_utc', 0),
                                                                             timezone.utc),
                                            url=f"https://reddit.com{post_data.get('permalink', '')}",
                                            engagement=post_data.get('score', 0) + post_data.get('num_comments', 0),
                                            sentiment_score=self._analyze_text_sentiment(text),
                                            confidence=0.7
                                        )
                                        mentions.append(mention)

                    await asyncio.sleep(1)  # Задержка между запросами

                except Exception as e:
                    logger.error(f"Ошибка получения данных из r/{subreddit}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Ошибка получения Reddit упоминаний для {symbol}: {e}")

        return mentions

    async def _get_news_mentions(self, symbol: str) -> List[SocialMention]:
        """Получение новостных упоминаний"""
        mentions = []
        try:
            clean_symbol = symbol.replace('USDT', '')

            url = "https://min-api.cryptocompare.com/data/v2/news/"
            params = {
                'lang': 'EN',
                'sortOrder': 'latest',
                'categories': f'{clean_symbol}',
                'limit': 20
            }

            if self.session:
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()

                        for article in data.get('Data', []):
                            text = f"{article.get('title', '')} {article.get('body', '')}"

                            mention = SocialMention(
                                platform='news',
                                text=text[:300],
                                author=article.get('source_info', {}).get('name', 'unknown'),
                                timestamp=datetime.fromtimestamp(article.get('published_on', 0), timezone.utc),
                                url=article.get('url', ''),
                                engagement=1,  # Новости имеют базовый engagement
                                sentiment_score=self._analyze_text_sentiment(text),
                                confidence=0.8
                            )
                            mentions.append(mention)

        except Exception as e:
            logger.error(f"Ошибка получения новостей для {symbol}: {e}")

        return mentions

    async def _get_coingecko_social(self, symbol: str) -> List[SocialMention]:
        """Получение социальных данных из CoinGecko"""
        mentions = []
        try:
            clean_symbol = symbol.replace('USDT', '').lower()

            # Поиск монеты
            search_url = f"https://api.coingecko.com/api/v3/search?query={clean_symbol}"

            if self.session:
                async with self.session.get(search_url) as response:
                    if response.status == 200:
                        search_data = await response.json()

                        coin = None
                        for c in search_data.get('coins', []):
                            if c.get('symbol', '').lower() == clean_symbol:
                                coin = c
                                break

                        if coin:
                            # Получаем детальную информацию
                            coin_url = f"https://api.coingecko.com/api/v3/coins/{coin['id']}"

                            async with self.session.get(coin_url) as coin_response:
                                if coin_response.status == 200:
                                    coin_data = await coin_response.json()

                                    # Создаем упоминание на основе описания
                                    description = coin_data.get('description', {}).get('en', '')
                                    if description:
                                        mention = SocialMention(
                                            platform='coingecko',
                                            text=description[:200],
                                            author='CoinGecko',
                                            timestamp=datetime.now(timezone.utc),
                                            url=coin_data.get('links', {}).get('homepage', [''])[0],
                                            engagement=coin_data.get('community_score', 0),
                                            sentiment_score=self._analyze_text_sentiment(description),
                                            confidence=0.6
                                        )
                                        mentions.append(mention)

        except Exception as e:
            logger.error(f"Ошибка получения CoinGecko социальных данных для {symbol}: {e}")

        return mentions

    async def _get_coingecko_trending(self, symbol: str) -> Dict:
        """Получение данных о трендах с CoinGecko"""
        try:
            if not self.session:
                return {}

            # Получаем trending данные
            url = "https://api.coingecko.com/api/v3/search/trending"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()

                    # Ищем наш символ в трендах
                    clean_symbol = symbol.replace('USDT', '').lower()
                    for coin in data.get('coins', []):
                        if coin.get('item', {}).get('symbol', '').lower() == clean_symbol:
                            return {
                                'trending_score': min(10, coin.get('item', {}).get('score', 0) + 1),
                                'mentions': coin.get('item', {}).get('score', 0) * 10
                            }

            return {'trending_score': 0, 'mentions': 0}

        except Exception as e:
            logger.error(f"Ошибка получения CoinGecko данных для {symbol}: {e}")
            return {'trending_score': 0, 'mentions': 0}

    def _analyze_text_sentiment(self, text: str) -> float:
        """Анализ настроений текста"""
        try:
            # Простой анализ по ключевым словам
            text_lower = text.lower()

            positive_score = 0
            negative_score = 0

            # Подсчитываем позитивные слова
            for word in self.crypto_keywords['positive']:
                if word in text_lower:
                    positive_score += 1

            # Подсчитываем негативные слова
            for word in self.crypto_keywords['negative']:
                if word in text_lower:
                    negative_score += 1

            # Рассчитываем итоговый sentiment
            total_keywords = positive_score + negative_score
            if total_keywords > 0:
                sentiment = (positive_score - negative_score) / total_keywords
                return max(-1, min(1, sentiment))

            return 0.0

        except Exception as e:
            logger.error(f"Ошибка анализа настроений: {e}")
            return 0.0

    async def _calculate_rating(self, symbol: str, mentions: List[SocialMention], coingecko_data: Dict) -> SocialRating:
        """Расчет итогового рейтинга"""
        if not mentions:
            return self._create_basic_rating(symbol, coingecko_data)

        # Подсчитываем типы упоминаний
        positive_count = len([m for m in mentions if m.sentiment_score > 0.2])
        negative_count = len([m for m in mentions if m.sentiment_score < -0.2])
        neutral_count = len(mentions) - positive_count - negative_count

        # Рассчитываем общий счет настроений
        total_sentiment = sum(m.sentiment_score * m.confidence for m in mentions)
        avg_sentiment = total_sentiment / len(mentions) if mentions else 0
        overall_score = max(-100, min(100, avg_sentiment * 100))

        # Рассчитываем trending score
        trending_score = coingecko_data.get('trending_score', 0) * 10

        # Рассчитываем volume score на основе количества упоминаний
        volume_score = min(100, (len(mentions) / 20) * 100)

        # Определяем тренд настроений
        recent_mentions = [m for m in mentions if
                           (datetime.now(timezone.utc) - m.timestamp).total_seconds() < 24 * 3600]
        older_mentions = [m for m in mentions if
                          (datetime.now(timezone.utc) - m.timestamp).total_seconds() >= 24 * 3600]

        sentiment_trend = 'stable'
        if recent_mentions and older_mentions:
            recent_sentiment = sum(m.sentiment_score for m in recent_mentions) / len(recent_mentions)
            older_sentiment = sum(m.sentiment_score for m in older_mentions) / len(older_mentions)

            if recent_sentiment > older_sentiment + 0.1:
                sentiment_trend = 'rising'
            elif recent_sentiment < older_sentiment - 0.1:
                sentiment_trend = 'falling'

        # Топ упоминания (по engagement)
        top_mentions = sorted(mentions, key=lambda x: x.engagement, reverse=True)[:5]

        return SocialRating(
            symbol=symbol,
            overall_score=round(overall_score, 1),
            mention_count=len(mentions),
            positive_mentions=positive_count,
            negative_mentions=negative_count,
            neutral_mentions=neutral_count,
            trending_score=round(trending_score, 1),
            volume_score=round(volume_score, 1),
            sentiment_trend=sentiment_trend,
            last_updated=datetime.now(timezone.utc),
            top_mentions=top_mentions
        )

    async def _save_rating_to_db(self, rating: SocialRating):
        """Сохранение рейтинга в базу данных"""
        try:
            # Используем database queries для сохранения
            # Это будет реализовано в database_queries.py
            pass
        except Exception as e:
            logger.error(f"Ошибка сохранения рейтинга в БД: {e}")

    async def get_ratings_for_symbols(self, symbols: List[str]) -> Dict[str, SocialRating]:
        """Получить рейтинги для списка символов"""
        ratings = {}

        # Ограничиваем количество одновременных запросов
        semaphore = asyncio.Semaphore(3)

        async def get_rating_with_semaphore(symbol):
            async with semaphore:
                rating = await self.get_symbol_rating(symbol)
                if rating:
                    ratings[symbol] = rating
                await asyncio.sleep(0.5)  # Задержка между запросами

        # Запускаем задачи параллельно
        tasks = [get_rating_with_semaphore(symbol) for symbol in symbols]
        await asyncio.gather(*tasks, return_exceptions=True)

        return ratings

    def get_rating_emoji(self, score: float) -> str:
        """Получить эмодзи для рейтинга"""
        if score >= 70:
            return "🚀"  # Очень позитивно
        elif score >= 40:
            return "📈"  # Позитивно
        elif score >= 10:
            return "🟢"  # Слабо позитивно
        elif score >= -10:
            return "⚪"  # Нейтрально
        elif score >= -40:
            return "🟡"  # Слабо негативно
        elif score >= -70:
            return "📉"  # Негативно
        else:
            return "🔴"  # Очень негативно

    def get_trend_emoji(self, trend: str) -> str:
        """Получить эмодзи для тренда"""
        if trend == 'rising':
            return "⬆️"
        elif trend == 'falling':
            return "⬇️"
        else:
            return "➡️"
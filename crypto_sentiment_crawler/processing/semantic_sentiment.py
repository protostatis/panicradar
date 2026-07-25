"""
Semantic sentiment analysis using sentence transformers.

Uses example phrases as "lexicons" instead of individual words.
Computes cosine similarity to bullish/bearish/neutral anchor phrases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ..logging_config import logger

if TYPE_CHECKING:
    from .embedding_providers import EmbeddingProvider


# Bullish phrases - expressing optimism, gains, buying intent
BULLISH_PHRASES = [
    # Price action - positive
    "Bitcoin is breaking out to new all-time highs",
    "The price is pumping hard right now",
    "We're seeing a massive rally across the market",
    "This coin just broke major resistance",
    "The chart looks incredibly bullish",
    "New all time high, we're mooning",
    "Price just exploded upward",
    "Massive green candles across the board",
    "Breaking out of the consolidation pattern",
    "Higher highs and higher lows confirmed",

    # Buying/accumulation
    "I just bought more, this is a great entry point",
    "Accumulating heavily at these prices",
    "This dip is a gift, loading up my bags",
    "Smart money is buying right now",
    "Institutions are accumulating Bitcoin",
    "Adding to my position here",
    "Dollar cost averaging into this",
    "Buying the dip aggressively",
    "Whales are accumulating heavily",
    "This is the last chance to buy cheap",

    # Optimism/confidence
    "This project has incredible fundamentals",
    "The team is delivering exactly what they promised",
    "Adoption is growing rapidly",
    "This technology will change everything",
    "I'm extremely bullish on the long term",
    "The future looks incredibly bright",
    "This will be worth so much more",
    "Holding strong, never been more confident",
    "This is going to change the world",
    "So much potential for growth",

    # Gains/profits
    "Made huge profits on this trade",
    "My portfolio is up significantly",
    "Finally in the green after holding",
    "This investment paid off massively",
    "Best performing asset in my portfolio",
    "Made 10x gains on this investment",
    "Up 500 percent since I bought",
    "Took profits at the top",
    "Best trade I ever made",
    "Easy money, incredible returns",
    "Life changing gains from this trade",
    "Turned 1000 into 100000",
    "My investment multiplied many times over",
    "Paid off my mortgage with crypto gains",
    "Financial freedom achieved through crypto",

    # Community excitement
    "The community is stronger than ever",
    "Everyone is so excited about this launch",
    "Developers are building amazing things",
    "Partnership announcements are huge",
    "This is just the beginning of something big",
    "The hype is real and justified",
    "Mass adoption is coming",
    "Institutional money is flowing in",
    "This community is amazing",
    "So many exciting developments ahead",

    # Crypto slang - bullish
    "We're all gonna make it",
    "To the moon, let's go",
    "Diamond hands will be rewarded",
    "HODL and you will be rich",
    "This is the way to financial freedom",
    "Generational wealth opportunity",
    "Not selling until retirement",
    "Stacking sats for the future",
    "This is incredibly undervalued",
    "Easy 100x from here",

    # Technical analysis - bullish
    "Golden cross forming on the chart",
    "Accumulation zone confirmed",
    "Strong support holding perfectly",
    "Bullish divergence on the RSI",
    "Cup and handle pattern completing",
    "Breakout imminent from this range",
    "Volume confirming the uptrend",
    "Moving averages turning bullish",
]

# Bearish phrases - expressing pessimism, losses, selling intent
BEARISH_PHRASES = [
    # Price action - crash/dump/plunge/tank
    "The market is crashing hard",
    "Bitcoin is dumping to new lows",
    "This coin is bleeding out",
    "We're in a full bear market now",
    "The chart looks terrible, more downside coming",
    "Price is in freefall right now",
    "Massive red candles everywhere",
    "Breaking down below support",
    "Lower lows and lower highs",
    "Complete market collapse happening",
    "The price crashed overnight",
    "Crypto crashed and burned today",
    "Everything is crashing right now",
    "Market is dumping across the board",
    "Whales are dumping massive amounts",
    "Price is plunging rapidly",
    "The market is plunging into the abyss",
    "Bitcoin is tanking hard",
    "Everything is tanking today",
    "Price tanked after the announcement",
    "Market is bleeding heavily",
    "Portfolio bleeding for weeks now",
    "This bloodbath is devastating",
    "Absolute bloodbath in the market today",
    "It's a bloodbath out there",

    # Selling/exit - selloff/paper hands
    "I sold everything, this is going to zero",
    "Getting out before it crashes more",
    "Cut my losses and moved on",
    "Everyone is panic selling",
    "Whales are dumping their bags",
    "Time to exit this position",
    "Sold at a huge loss",
    "Exiting all crypto positions",
    "Taking the loss and moving on",
    "Paper handed and sold the bottom",
    "Massive selloff happening right now",
    "The selloff is accelerating",
    "Selloff triggered by bad news",
    "Paper hands everywhere selling",
    "Don't be a paper hands seller",
    "Paper hands will regret selling",
    "Weak hands are selling in panic",

    # Losses/rekt/down bad - crypto slang
    "Lost all my money on this",
    "My portfolio is down 80 percent",
    "Got completely rekt on this trade",
    "Worst investment I ever made",
    "Watching my savings disappear",
    "My money just disappeared from my account",
    "Funds are gone, lost everything",
    "Wiped out my entire investment",
    "Life savings destroyed by this crash",
    "Down so much I feel sick",
    "I got rekt so hard on this",
    "Absolutely rekt by this dump",
    "Everyone is getting rekt today",
    "Rekt beyond recovery",
    "I'm down bad on this investment",
    "So down bad right now",
    "Down bad and losing hope",
    "Taking massive losses here",
    "Huge losses on this trade",
    "The losses keep piling up",
    "Lost everything I invested",
    "Lost my entire portfolio",

    # Bagholding - stuck with losses
    "Stuck holding these heavy bags",
    "Became a bagholder overnight",
    "Bagholding this trash forever",
    "We're all bagholders now",
    "Don't want to be a bag holder",
    "Holding bags of worthless coins",

    # Liquidation - margin trading losses
    "Got liquidated on this position",
    "Liquidation cascade happening",
    "Massive liquidations across the board",
    "Millions in liquidations today",
    "Leveraged traders getting liquidated",
    "My position got liquidated",
    "Avoid getting liquidated",
    "Liquidation wiped out my account",

    # Theft/hacking/exploit/drain
    "My wallet was hacked and drained",
    "Someone stole all my crypto",
    "Funds disappeared from my account",
    "Exchange froze my withdrawals",
    "My money vanished without a trace",
    "Account compromised, everything gone",
    "Phishing scam took all my funds",
    "Lost access to my wallet forever",
    "Private keys stolen by hackers",
    "Exchange exit scammed everyone",
    "Protocol was exploited for millions",
    "Hackers exploited a vulnerability",
    "Smart contract exploit drained funds",
    "Bridge exploit lost user funds",
    "Wallet got drained by hackers",
    "Account drained in minutes",
    "Funds drained through exploit",
    "Hacked and lost everything",
    "Security breach drained the protocol",

    # Scams/fraud - rug/ponzi/honeypot
    "This project is a complete scam",
    "The team rugged everyone",
    "Another rug pull, lost everything",
    "Developers abandoned the project",
    "This is clearly a ponzi scheme",
    "Obvious pump and dump scheme",
    "Founders ran away with the money",
    "Fake project designed to steal funds",
    "This token is a honeypot scam",
    "Classic crypto fraud scheme",
    "Got rugged on this investment",
    "The rug pull was devastating",
    "Watch out for rug pulls",
    "This looks like a honeypot",
    "Honeypot contract detected",
    "Another ponzi scheme exposed",
    "Ponzi finally collapsed",
    "Scammers running rampant",
    "So many scams in crypto",
    "Beware of scammers everywhere",

    # Project death - dead/dying
    "This project is completely dead",
    "The coin is dead, abandon ship",
    "Dead project with no future",
    "This chain is dying slowly",
    "Dying ecosystem with no users",
    "Project is dead on arrival",
    "Dead coin walking",
    "No development, project is dead",

    # Frustration/complaints - expensive/fees/slow/broken/buggy
    "The fees are ridiculously expensive",
    "Network is completely unusable",
    "Customer support is non-existent",
    "This platform keeps having issues",
    "Worst experience with any crypto",
    "Transaction stuck for hours",
    "Terrible user experience overall",
    "Nothing works properly here",
    "Constant bugs and problems",
    "Completely disappointed with this",
    "Gas fees are way too expensive",
    "Overpriced garbage token",
    "This is overpriced junk",
    "High fees make it unusable",
    "Fees eating all my profits",
    "Network is too slow",
    "Transactions are painfully slow",
    "Everything is slow and broken",
    "The platform is completely broken",
    "Buggy software full of errors",
    "So buggy it's unusable",
    "This is absolutely terrible",
    "Horrible experience with this exchange",
    "Awful project with no future",
    "This sucks so much",
    "The platform really sucks",
    "It just sucks, avoid it",
    "So disappointing overall",
    "Very disappointed with the results",
    "Disappointing performance lately",
    "This is frustrating beyond belief",
    "Frustrated with the constant issues",
    "So annoyed with this platform",
    "Annoying bugs everywhere",
    "Completely useless product",
    "This is useless garbage",
    "Total waste of money",
    "Waste of time and money",
    "Unable to withdraw my funds",
    "Cannot access my account",
    "Can't believe I lost money on this",
    "Won't be using this again",
    "It doesn't work at all",
    "Nothing is working properly",
    "Not working as expected",

    # Warnings - beware/avoid/warning
    "Stay away from this project",
    "Do not invest in this scam",
    "Warning to all investors beware",
    "You will lose your money",
    "This is financial suicide",
    "Protect yourself from this fraud",
    "Run away as fast as you can",
    "This will go to zero",
    "Don't fall for this trap",
    "Avoid at all costs",
    "Beware of this project",
    "Beware of the risks involved",
    "Warning signs everywhere",
    "Major red flags here",

    # Fear/panic/capitulation - ngmi
    "The fear is overwhelming right now",
    "Panic selling across the market",
    "Everyone is terrified of more losses",
    "Extreme fear in the market",
    "Capitulation is happening",
    "Blood in the streets everywhere",
    "Despair and hopelessness",
    "No one believes anymore",
    "Complete loss of confidence",
    "Market sentiment is horrible",
    "We're not gonna make it",
    "NGMI with this investment",
    "Feeling NGMI right now",
    "This is looking very bearish",
    "Extremely bearish outlook",
    "Bearish sentiment dominating",
    "I'm bearish on the market",
    "The market looks bearish",

    # Technical analysis - bearish
    "Death cross forming on the chart",
    "Breaking down below major support",
    "Bearish divergence confirmed",
    "Head and shoulders pattern completing",
    "Distribution phase in progress",
    "Volume confirms the downtrend",
    "Moving averages turning bearish",
    "RSI showing extreme weakness",
    "Support levels breaking down",
    "Resistance rejected again",
    "Chart looks extremely bearish",
    "Bearish pattern confirmed",

    # Regulatory/external threats
    "SEC is going after this project",
    "Government crackdown on crypto",
    "New regulations will kill this",
    "Facing serious legal problems",
    "Banned in multiple countries",
    "Regulatory pressure mounting",
    "Legal action being taken",
    "Compliance issues everywhere",
]

# Neutral phrases - news, questions, factual statements
NEUTRAL_PHRASES = [
    # Questions - general (seeking information, not expressing sentiment)
    "What do you think about Bitcoin?",
    "Is now a good time to buy?",
    "How does this protocol work?",
    "Can someone explain the tokenomics?",
    "When is the next update scheduled?",
    "What are your thoughts on this coin?",
    "Has anyone used this exchange before?",
    "How do I stake my tokens?",
    "Where can I buy this cryptocurrency?",
    "What wallet should I use?",
    "How do taxes work for crypto?",
    "Is this a good project to research?",
    "What's the difference between these coins?",
    "Anyone have experience with this?",
    "Looking for opinions on this token",
    "What do you think about ETH?",
    "What do you think about Ethereum?",
    "What do you think about Solana?",
    "Opinions on this cryptocurrency?",
    "Thoughts on the current market?",
    "What are people saying about this?",
    "Should I look into this project?",
    "Curious about this coin",
    "Wondering about this token",
    "Need advice on cryptocurrency",
    "Seeking information about blockchain",
    "Can anyone help me understand this?",
    "Questions about this exchange",
    "Inquiry about trading fees",
    "How does this compare to others?",

    # Factual/news - price mentions without sentiment
    "Bitcoin traded at 100k today",
    "The protocol processed 1 million transactions",
    "New update was released yesterday",
    "The team announced a partnership",
    "Trading volume increased this week",
    "The price is currently at 50000 dollars",
    "Market cap reached 1 trillion",
    "Daily transactions hit a new record",
    "The token launched at this price",
    "Current trading price is shown here",
    "The market moved sideways today",
    "Price remained stable this week",
    "Volume was average for the day",
    "No significant price movement",
    "Trading within the usual range",

    # News headlines - factual
    "Bitcoin ETF approved by regulators",
    "New cryptocurrency exchange launched",
    "Protocol announces network upgrade",
    "Company adds Bitcoin to balance sheet",
    "Crypto legislation passed in congress",
    "Exchange lists new trading pairs",
    "Blockchain network reaches milestone",
    "Major bank offers crypto services",
    "New DeFi protocol goes live",
    "Stablecoin maintains its peg",

    # Governance/proposals (formal, procedural - not expressing sentiment)
    "This proposal seeks community approval",
    "Vote on the new treasury allocation",
    "The DAO is deciding on funding",
    "Governance discussion about protocol changes",
    "Community poll for the next feature",
    "Proposal to allocate tokens for development",
    "Discussion thread for protocol upgrade",
    "Voting period ends tomorrow",
    "Quorum reached for this proposal",
    "Community feedback requested",
    "Proposal submitted for review",
    "Governance vote is now live",
    "DAO proposal number 47",
    "Treasury management proposal",
    "Token allocation discussion",
    "Protocol parameter adjustment",
    "Community grant application",
    "Improvement proposal draft",
    "Request for comments on changes",
    "Formal proposal for consideration",
    "Seeking approval for funding allocation",
    "Budget proposal for next quarter",
    "Delegate voting instructions",
    "Snapshot vote is open",
    "On-chain governance update",

    # Technical/educational
    "The smart contract was audited",
    "Layer 2 solution uses optimistic rollups",
    "Staking rewards are distributed daily",
    "The bridge connects multiple chains",
    "Transaction fees vary by network congestion",
    "Here is how the technology works",
    "Explaining the consensus mechanism",
    "Guide to setting up a wallet",
    "Tutorial on using the platform",
    "Step by step instructions for beginners",
    "How to transfer between wallets",
    "Understanding blockchain technology",
    "Beginner's guide to cryptocurrency",
    "Technical documentation available",
    "Learn about smart contracts",

    # Discussion threads - neutral
    "Daily discussion thread",
    "Weekly discussion and questions",
    "General chat and conversation",
    "Monthly community roundup",
    "Open discussion for all topics",
    "Ask me anything thread",
    "Newcomer questions welcome",
    "Share your portfolio allocation",
    "What are you holding today",
    "Weekend discussion thread",

    # Meta/community
    "New rules for the subreddit",
    "Moderator announcement",
    "Community guidelines updated",
    "Welcome to the community",
    "Subreddit statistics for this month",
    "Introducing new community features",
    "Feedback on subreddit changes",
    "Community survey results",

    # Analysis without clear direction
    "Looking at the current market data",
    "Analyzing the price action",
    "Reviewing the fundamentals",
    "Chart analysis for today",
    "Market overview and summary",
    "Comparing different cryptocurrencies",
    "Research report on this project",
    "Due diligence on this token",
    "Evaluating the risk and reward",
    "Neutral perspective on the market",

    # Mixed/uncertain sentiment (neither clearly bullish nor bearish)
    "Not sure what to think about this",
    "Could go either way from here",
    "Mixed feelings about this project",
    "On the fence about investing",
    "Need more information before deciding",
    "Weighing the pros and cons",
    "Undecided about this opportunity",
    "Both bullish and bearish arguments exist",
    "The situation is unclear right now",
    "Too early to tell what will happen",
    "Market could go up or down",
    "Waiting to see how this plays out",
    "Taking a wait and see approach",
    "Neither optimistic nor pessimistic",
    "Cautiously observing the market",

    # Q&A / practical help-seeking (not sentiment, often mis-scored bearish)
    "How do I set up a hardware wallet",
    "What are the transaction fees for this",
    "Can someone explain how staking works",
    "Which exchange has the lowest fees",
    "How to transfer crypto between wallets",
    "What is the difference between these two tools",
    "Does anyone know the tax implications",
    "Step by step guide for beginners",
    "Comparing features of different wallets",
    "How to use a decentralized exchange",
    "What is the best way to store crypto safely",
    "How do gas fees work on this network",
    "Which wallet supports this token",
    "How to bridge tokens between chains",
    "What are the withdrawal fees",
    "How to set up two factor authentication",
    "What is the minimum deposit amount",
    "How do I claim my staking rewards",
    "Which tool should I use for this",
    "Where can I track my portfolio",

    # Tool/product comparisons (operational, not sentiment)
    "Comparing these two services side by side",
    "Which one has better features",
    "Looking for alternatives to this tool",
    "Has anyone tried both of these",
    "What are the pros and cons of each option",
    "Review of this wallet app",
    "Which platform is more user friendly",
    "Trying to decide between these options",

    # Token burns / mechanics (operational terms mis-read as bearish)
    "Token burn event scheduled for this month",
    "How does the burn mechanism work",
    "Tokens are burned with each transaction",
    "The burn rate for this token",
    "Explaining the deflationary burn model",
]


class SemanticSentimentAnalyzer:
    """
    Sentiment analyzer using sentence embeddings.

    Computes semantic similarity between input text and
    bullish/bearish/neutral anchor phrases.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        provider: "EmbeddingProvider | None" = None,
        backend: str | None = None,
    ):
        """Initialize with an embedding backend.

        Three ways to choose the backend (in priority order):

        1. ``provider=`` — pass a pre-built :class:`EmbeddingProvider`
           (e.g. an :class:`OpenRouterEmbeddingProvider`).
        2. ``backend=`` — ``"local"`` or ``"openrouter"``; the provider is
           constructed from environment / ``model_name``.
        3. ``model_name=`` — a local SentenceTransformer name (backwards-
           compatible with the original single-argument call).

        Args:
            model_name: HuggingFace model name for the *local* backend.
                Ignored if ``provider`` is given. Defaults to
                ``"all-MiniLM-L6-v2"``.
            provider: Pre-built embedding backend. Wins over everything else.
            backend: ``"local"`` | ``"openrouter"``. If unset, defaults to
                ``"local"`` unless ``model_name`` is a hosted slug.
        """
        from .embedding_providers import (
            LocalSentenceTransformerProvider,
            OpenRouterEmbeddingProvider,
            get_provider,
        )

        if provider is not None:
            self.provider = provider
        elif backend is not None:
            self.provider = get_provider(backend, model=model_name)
        else:
            # No explicit backend/model specified — fall back to settings or
            # the (deprecated) model_name positional argument.
            from ..config import settings

            cfg_backend = settings.embedding_backend or "local"
            cfg_model = model_name or settings.embedding_model or "all-MiniLM-L6-v2"

            # Determine whether this model slug implies OpenRouter.
            is_or_hosted = "/" in cfg_model and not cfg_model.startswith(
                ("all-", "paraphrase-", "BAAI", "baai", "sentence-transformers/")
            )
            if is_or_hosted or cfg_backend == "openrouter":
                try:
                    self.provider = OpenRouterEmbeddingProvider(
                        model=cfg_model, api_key=settings.openrouter_api_key
                    )
                except RuntimeError:
                    logger.warning(
                        "OpenRouter unavailable (no API key?); falling back to MiniLM"
                    )
                    self.provider = LocalSentenceTransformerProvider(
                        model_name="all-MiniLM-L6-v2"
                    )
            else:
                self.provider = LocalSentenceTransformerProvider(model_name=cfg_model)
        logger.info(
            "SemanticSentimentAnalyzer using provider=%s dim=%d",
            type(self.provider).__name__,
            self.provider.dim,
        )

        # Pre-compute anchor embeddings
        logger.info("Computing anchor phrase embeddings...")
        self.bullish_embeddings = self.provider.encode(BULLISH_PHRASES, normalize=True)
        self.bearish_embeddings = self.provider.encode(BEARISH_PHRASES, normalize=True)
        self.neutral_embeddings = self.provider.encode(NEUTRAL_PHRASES, normalize=True)

        # Compute centroid for each category
        self.bullish_centroid = np.mean(self.bullish_embeddings, axis=0)
        self.bearish_centroid = np.mean(self.bearish_embeddings, axis=0)
        self.neutral_centroid = np.mean(self.neutral_embeddings, axis=0)

        # Normalize centroids
        self.bullish_centroid /= np.linalg.norm(self.bullish_centroid)
        self.bearish_centroid /= np.linalg.norm(self.bearish_centroid)
        self.neutral_centroid /= np.linalg.norm(self.neutral_centroid)

        logger.info("Semantic sentiment analyzer ready")

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        return float(np.dot(a, b))

    def _get_top_k_similarity(
        self, embedding: np.ndarray, anchors: np.ndarray, k: int = 5
    ) -> float:
        """Get average similarity to top-k most similar anchors."""
        similarities = np.dot(anchors, embedding)
        top_k = np.sort(similarities)[-k:]
        return float(np.mean(top_k))

    def analyze(self, text: str, method: str = "asymmetric") -> dict:
        """
        Analyze sentiment of text.

        Args:
            text: Text to analyze
            method: Scoring method
                - "centroid": Compare to category centroids (fast)
                - "top_k": Average of top-k similar phrases (more nuanced)
                - "asymmetric": Blend that weights top-k more for bearish detection

        Returns:
            dict with 'score' (-1 to 1), 'bullish_sim', 'bearish_sim',
            'neutral_sim', 'confidence'
        """
        # Encode input text
        embedding = self.provider.encode_single(text, normalize=True)

        if method == "centroid":
            bullish_sim = self._cosine_similarity(embedding, self.bullish_centroid)
            bearish_sim = self._cosine_similarity(embedding, self.bearish_centroid)
            neutral_sim = self._cosine_similarity(embedding, self.neutral_centroid)
        elif method == "top_k":
            bullish_sim = self._get_top_k_similarity(embedding, self.bullish_embeddings, k=5)
            bearish_sim = self._get_top_k_similarity(embedding, self.bearish_embeddings, k=5)
            neutral_sim = self._get_top_k_similarity(embedding, self.neutral_embeddings, k=3)
        else:  # asymmetric - blend centroid and top_k
            # Centroid similarities
            bull_cent = self._cosine_similarity(embedding, self.bullish_centroid)
            bear_cent = self._cosine_similarity(embedding, self.bearish_centroid)
            neut_cent = self._cosine_similarity(embedding, self.neutral_centroid)

            # Top-k similarities (for bearish specificity)
            bear_topk = self._get_top_k_similarity(embedding, self.bearish_embeddings, k=5)

            # Use centroid for bullish/neutral, but boost bearish with top-k
            bullish_sim = bull_cent
            neutral_sim = neut_cent
            # If top-k finds strong bearish matches, weight it more
            if bear_topk > bear_cent:
                bearish_sim = 0.4 * bear_cent + 0.6 * bear_topk
            else:
                bearish_sim = bear_cent

        # Compute score: positive = bullish, negative = bearish
        # Scale by how much stronger one signal is vs the other
        raw_score = bullish_sim - bearish_sim

        # Confidence: how different are bullish/bearish from neutral
        sentiment_strength = max(bullish_sim, bearish_sim) - neutral_sim
        confidence = max(0.0, min(1.0, sentiment_strength * 2 + 0.5))

        # Scale score to [-1, 1] range
        # Typical similarity differences are small (0.0-0.3), so we amplify
        score = np.tanh(raw_score * 3)  # tanh scales and bounds to [-1, 1]

        return {
            "score": float(score),
            "bullish_sim": float(bullish_sim),
            "bearish_sim": float(bearish_sim),
            "neutral_sim": float(neutral_sim),
            "confidence": float(confidence),
            "method": f"semantic_{method}",
        }

    def get_score(self, text: str) -> float:
        """Get sentiment score from -1 (bearish) to 1 (bullish)."""
        return self.analyze(text)["score"]

    def analyze_batch(self, texts: list[str]) -> list[dict]:
        """Analyze multiple texts efficiently."""
        embeddings = self.provider.encode(texts, normalize=True)

        results = []
        for embedding in embeddings:
            bullish_sim = self._cosine_similarity(embedding, self.bullish_centroid)
            bearish_sim = self._cosine_similarity(embedding, self.bearish_centroid)
            neutral_sim = self._cosine_similarity(embedding, self.neutral_centroid)

            raw_score = bullish_sim - bearish_sim
            score = np.tanh(raw_score * 3)
            sentiment_strength = max(bullish_sim, bearish_sim) - neutral_sim
            confidence = max(0.0, min(1.0, sentiment_strength * 2 + 0.5))

            results.append({
                "score": float(score),
                "bullish_sim": float(bullish_sim),
                "bearish_sim": float(bearish_sim),
                "neutral_sim": float(neutral_sim),
                "confidence": float(confidence),
            })

        return results

    def get_scores_batch(self, texts: list[str]) -> list[float]:
        """Get sentiment scores for multiple texts."""
        return [r["score"] for r in self.analyze_batch(texts)]

    def find_similar_anchors(self, text: str, top_k: int = 3) -> dict:
        """
        Find most similar anchor phrases to understand the classification.

        Useful for debugging/explainability.
        """
        embedding = self.provider.encode_single(text, normalize=True)

        # Find top-k similar from each category
        bullish_sims = np.dot(self.bullish_embeddings, embedding)
        bearish_sims = np.dot(self.bearish_embeddings, embedding)
        neutral_sims = np.dot(self.neutral_embeddings, embedding)

        bullish_top = np.argsort(bullish_sims)[-top_k:][::-1]
        bearish_top = np.argsort(bearish_sims)[-top_k:][::-1]
        neutral_top = np.argsort(neutral_sims)[-top_k:][::-1]

        return {
            "bullish": [(BULLISH_PHRASES[i], float(bullish_sims[i])) for i in bullish_top],
            "bearish": [(BEARISH_PHRASES[i], float(bearish_sims[i])) for i in bearish_top],
            "neutral": [(NEUTRAL_PHRASES[i], float(neutral_sims[i])) for i in neutral_top],
        }


# Lazy singleton
_analyzer = None

def get_analyzer() -> SemanticSentimentAnalyzer:
    """Get or create the singleton analyzer."""
    global _analyzer
    if _analyzer is None:
        _analyzer = SemanticSentimentAnalyzer()
    return _analyzer


def test_analyzer():
    """Test the semantic analyzer on sample texts."""
    analyzer = SemanticSentimentAnalyzer()

    test_cases = [
        # Should be BULLISH
        ("Bitcoin is going to the moon! Just bought more!", "bullish"),
        ("This project has amazing fundamentals, very bullish", "bullish"),
        ("Made 10x gains on this trade, best investment ever", "bullish"),
        ("The chart is breaking out, we're going higher", "bullish"),

        # Should be BEARISH
        ("This coin is a complete scam, I lost everything", "bearish"),
        ("The market is crashing, sold all my positions", "bearish"),
        ("Got rugged, developers abandoned the project", "bearish"),
        ("Fees are way too high, this network is unusable", "bearish"),
        ("$75,000 just disappeared from my wallet", "bearish"),

        # Should be NEUTRAL
        ("What do you think about ETH?", "neutral"),
        ("Bitcoin traded at 100k yesterday", "neutral"),
        ("This proposal seeks DAO approval for funding", "neutral"),
        ("The network processed 1 million transactions", "neutral"),
    ]

    print("=" * 70)
    print("SEMANTIC SENTIMENT ANALYZER TEST")
    print("=" * 70)

    correct = 0
    for text, expected in test_cases:
        result = analyzer.analyze(text)
        score = result["score"]

        if score > 0.15:
            actual = "bullish"
        elif score < -0.15:
            actual = "bearish"
        else:
            actual = "neutral"

        match = "✓" if actual == expected else "✗"
        if actual == expected:
            correct += 1

        print(f"\n{match} Expected: {expected:8} | Got: {actual:8} | Score: {score:+.3f}")
        print(f"  Confidence: {result['confidence']:.2f}")
        print(f"  Text: {text[:60]}...")

    print(f"\n{'=' * 70}")
    print(f"Accuracy: {correct}/{len(test_cases)} ({100*correct/len(test_cases):.0f}%)")
    print("=" * 70)

    # Show explainability for a tricky case
    print("\n\nEXPLAINABILITY DEMO:")
    print("-" * 70)
    tricky = "$75,000 just disappeared from my Coinbase wallet"
    print(f"Text: {tricky}")
    similar = analyzer.find_similar_anchors(tricky, top_k=2)
    print("\nMost similar anchors:")
    print(f"  Bullish: {similar['bullish']}")
    print(f"  Bearish: {similar['bearish']}")
    print(f"  Neutral: {similar['neutral']}")


if __name__ == "__main__":
    test_analyzer()

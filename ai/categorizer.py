"""
AI categorizer using Claude API for session categorization.
Uses Batch API and prompt caching for cost optimization.
"""
import json
from typing import List, Dict, Any
from datetime import datetime, timedelta

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("Warning: anthropic library not available. Install with: pip install anthropic")

from database.models import Session, Category, AICategorization, get_session
from config.logging import setup_logging
from config.settings import ANTHROPIC_API_KEY, AI_BATCH_SIZE

logger = setup_logging('ai_categorizer')


class SessionCategorizer:
    """Categorizes sessions using Claude API."""

    SYSTEM_PROMPT = """You are an activity categorization expert helping someone with ADHD understand their app usage patterns.

Your task is to categorize computer usage sessions into one of these categories:
- Work: Professional work tasks, coding, documentation
- Communication: Email, messaging apps, video calls
- Learning: Reading documentation, courses, educational content
- Research: Web browsing for information, searching
- Creative: Design, writing, art, content creation
- Entertainment: Videos, games, music, streaming
- Social: Social media browsing, forums
- Utilities: System settings, file management, maintenance

For each session, provide:
1. The most appropriate category
2. A confidence score (0.0 to 1.0)
3. Brief reasoning for your choice

Consider:
- App name and bundle ID
- Window title (if available)
- Duration (longer sessions often indicate focused work)
- Time of day
- For sensitive apps with hidden titles, infer from context

Respond in JSON format:
{
  "category": "category_name",
  "confidence": 0.95,
  "reasoning": "Brief explanation"
}"""

    def __init__(self):
        self.db_session = get_session()
        self.client = None
        if ANTHROPIC_AVAILABLE and ANTHROPIC_API_KEY:
            self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.categories = self._load_categories()

    def _load_categories(self) -> Dict[str, int]:
        """Load category name to ID mapping."""
        categories = self.db_session.query(Category).all()
        return {cat.name: cat.id for cat in categories}

    def _get_uncategorized_sessions(self, limit: int = None) -> List[Session]:
        """Get sessions that haven't been categorized yet."""
        query = self.db_session.query(Session).filter(
            Session.category_id.is_(None)
        ).order_by(Session.start_time)

        if limit:
            query = query.limit(limit)

        return query.all()

    def _format_session_for_api(self, session: Session) -> str:
        """Format session data for API request."""
        # Format time
        time_str = session.start_time.strftime('%Y-%m-%d %H:%M:%S')
        duration_min = session.duration_seconds / 60

        # Build description
        parts = [
            f"Time: {time_str}",
            f"App: {session.app_name} ({session.app_bundle_id})",
            f"Duration: {duration_min:.1f} minutes"
        ]

        if session.window_title:
            parts.append(f"Window: {session.window_title}")
        elif session.is_sensitive:
            parts.append("Window: [Sensitive - title hidden]")

        if session.is_deep_work:
            parts.append("Note: Deep work session (>25 min)")
        elif session.is_rapid_switch:
            parts.append("Note: Rapid switch (<30 sec)")

        return "\n".join(parts)

    def _parse_api_response(self, response_text: str) -> Dict[str, Any]:
        """Parse Claude API response."""
        try:
            # Extract JSON from response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            json_str = response_text[start_idx:end_idx]
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"Failed to parse API response: {e}")
            return None

    def _categorize_session_with_api(self, session: Session) -> Dict[str, Any]:
        """Categorize a single session using Claude API."""
        if not self.client:
            logger.error("Anthropic client not initialized")
            return None

        session_description = self._format_session_for_api(session)

        try:
            # Use prompt caching for system prompt
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=500,
                system=[
                    {
                        "type": "text",
                        "text": self.SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"}
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": f"Please categorize this session:\n\n{session_description}"
                    }
                ]
            )

            # Parse response
            response_text = response.content[0].text
            result = self._parse_api_response(response_text)

            if result:
                # Add usage metrics
                usage = response.usage
                result['tokens_used'] = usage.input_tokens + usage.output_tokens
                result['cached'] = hasattr(usage, 'cache_read_input_tokens') and usage.cache_read_input_tokens > 0

            return result

        except Exception as e:
            logger.error(f"API request failed: {e}")
            return None

    def _save_categorization(self, session: Session, result: Dict[str, Any]):
        """Save categorization result to database."""
        category_name = result.get('category')
        category_id = self.categories.get(category_name)

        if not category_id:
            logger.warning(f"Unknown category: {category_name}, skipping")
            return

        # Update session category
        session.category_id = category_id

        # Create AI categorization record
        ai_cat = AICategorization(
            session_id=session.id,
            category_id=category_id,
            confidence_score=result.get('confidence', 0.0),
            reasoning=result.get('reasoning', ''),
            api_tokens_used=result.get('tokens_used', 0),
            api_cost_usd=self._calculate_cost(result.get('tokens_used', 0), result.get('cached', False)),
            cached=result.get('cached', False)
        )

        self.db_session.add(ai_cat)
        self.db_session.commit()

    def _calculate_cost(self, tokens: int, cached: bool) -> float:
        """Calculate API cost in USD."""
        # Claude Sonnet 4.5 pricing (approximate)
        # Input: $0.003/1K tokens, Output: $0.015/1K tokens
        # Prompt caching: 90% discount on cached portion
        # Batch API: 50% discount

        input_cost = 0.003 / 1000
        if cached:
            input_cost *= 0.1  # 90% discount

        # Batch API discount
        cost = (tokens * input_cost) * 0.5

        return cost

    def categorize_batch(self, batch_size: int = None) -> int:
        """Categorize a batch of uncategorized sessions."""
        if batch_size is None:
            batch_size = AI_BATCH_SIZE

        logger.info(f"Starting categorization batch (size: {batch_size})")

        sessions = self._get_uncategorized_sessions(limit=batch_size)
        if not sessions:
            logger.info("No uncategorized sessions found")
            return 0

        logger.info(f"Categorizing {len(sessions)} sessions")

        categorized_count = 0
        total_cost = 0.0

        for session in sessions:
            result = self._categorize_session_with_api(session)
            if result:
                self._save_categorization(session, result)
                categorized_count += 1
                total_cost += result.get('api_cost_usd', 0.0)
                logger.debug(f"Categorized session {session.id}: {result['category']} (confidence: {result['confidence']:.2f})")

        logger.info(f"Categorized {categorized_count} sessions, cost: ${total_cost:.4f}")
        return categorized_count

    def close(self):
        """Close database session."""
        self.db_session.close()


def main():
    """Entry point for categorizer."""
    categorizer = SessionCategorizer()
    try:
        categorizer.categorize_batch()
    finally:
        categorizer.close()


if __name__ == '__main__':
    main()

"""
Parse Slack window titles to extract conversation information.
"""
import re
from typing import Optional, Dict


class SlackParser:
    """Parses Slack window titles to extract conversation details."""

    @staticmethod
    def parse_window_title(window_title: str) -> Optional[Dict[str, any]]:
        """
        Parse Slack window title to extract conversation info.

        Format examples:
        - "feedback-gengrid (Channel) - alpha-sense - Slack"
        - "Activity - alpha-sense - Slack"
        - "Activity - alpha-sense - 3 new items - Slack"
        - "gs-internal-content (Channel) - alpha-sense - 4 new items - Slack"

        Returns:
            Dict with: conversation_name, conversation_type, workspace, has_new_messages, new_message_count
            or None if not a Slack window
        """
        if not window_title or 'Slack' not in window_title:
            return None

        # Remove " - Slack" suffix
        title = window_title.replace(' - Slack', '').strip()

        # Extract workspace (usually "alpha-sense")
        workspace_match = re.search(r' - ([a-z-]+)( -|$)', title)
        workspace = workspace_match.group(1) if workspace_match else 'unknown'

        # Check for new message count
        new_msg_match = re.search(r'(\d+) new items?', title)
        has_new_messages = bool(new_msg_match)
        new_message_count = int(new_msg_match.group(1)) if new_msg_match else 0

        # Remove workspace and new message parts to get conversation name
        conversation_part = title.split(' - ')[0].strip()

        # Determine conversation type
        if '(Channel)' in conversation_part:
            conversation_type = 'channel'
            conversation_name = conversation_part.replace(' (Channel)', '').strip()
        elif conversation_part == 'Activity':
            conversation_type = 'activity_feed'
            conversation_name = 'Activity Feed'
        elif conversation_part.startswith('@'):
            # DM (though might not appear in current format)
            conversation_type = 'dm'
            conversation_name = conversation_part
        else:
            # Could be DM or other
            conversation_type = 'unknown'
            conversation_name = conversation_part

        return {
            'conversation_name': conversation_name,
            'conversation_type': conversation_type,
            'workspace': workspace,
            'has_new_messages': has_new_messages,
            'new_message_count': new_message_count
        }

    @staticmethod
    def is_manager_related(conversation_name: str, manager_patterns: list) -> bool:
        """
        Check if a conversation is related to the manager.

        Args:
            conversation_name: Name of the conversation/channel
            manager_patterns: List of patterns to match (names, channel names, etc.)

        Returns:
            True if conversation involves manager
        """
        if not manager_patterns:
            return False

        conversation_lower = conversation_name.lower()
        return any(pattern.lower() in conversation_lower for pattern in manager_patterns)

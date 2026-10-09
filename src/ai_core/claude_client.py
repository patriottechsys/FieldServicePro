"""Claude API client for FieldServicePro AI Assistant."""

import os
import anthropic


class ClaudeClient:
    """Wrapper around the Anthropic Claude API."""

    def __init__(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5-5')

    def chat(self, system_prompt, messages, max_tokens=2048):
        """Send a chat request and return the full response."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text

    def chat_stream(self, system_prompt, messages, max_tokens=2048):
        """Send a chat request and yield streaming chunks."""
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
